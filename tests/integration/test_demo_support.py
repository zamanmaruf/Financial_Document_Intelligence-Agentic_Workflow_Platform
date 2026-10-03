"""Demo building blocks: sessions, rate limiter, LLM budget cap, retention, schema migration."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from starlette.requests import Request

from app.core.clock import utcnow
from app.core.errors import RateLimitedError
from app.demo.budget import BudgetedLLMProvider, DailyBudget
from app.demo.limits import RateLimiter, client_ip
from app.demo.retention import purge_expired
from app.demo.sessions import issue_session, verify_session
from app.domain.models import DEFAULT_WORKSPACE, Document, DocumentMetadata
from app.persistence.db import SCHEMA_VERSION, create_db_engine, make_session_factory
from app.persistence.repositories import DocumentRepository
from app.providers.llm.base import LLMRequest, LLMResponse
from app.providers.llm.mock import MockLLMProvider
from app.services.container import Container
from tests.support import make_settings, sample_pdf

SECRET = "k" * 40
LIVE_MODEL = "us.anthropic.claude-haiku-4-5-20251001-v1:0"


# --------------------------------------------------------------------------- sessions


def test_session_round_trip_and_rejections() -> None:
    ws, cookie = issue_session(SECRET, now=1_000_000)
    assert verify_session(SECRET, cookie, 3600, now=1_000_100) == ws
    assert verify_session("other" * 10, cookie, 3600, now=1_000_100) is None
    assert verify_session(SECRET, cookie, 3600, now=1_000_000 + 3601) is None  # expired
    assert verify_session(SECRET, cookie, 3600, now=999_000) is None  # issued in the future
    for bad in (None, "", "a.b", "a.b.c.d", f"{ws}.notanumber.{cookie.split('.')[2]}", "x" * 300):
        assert verify_session(SECRET, bad, 3600, now=1_000_100) is None


def test_demo_mode_requires_a_long_secret(tmp_path: Path) -> None:
    with pytest.raises(ValidationError, match="DEMO_SECRET"):
        make_settings(tmp_path, demo_mode=True)
    with pytest.raises(ValidationError, match="DEMO_SECRET"):
        make_settings(tmp_path, demo_mode=True, demo_secret="short")


# --------------------------------------------------------------------------- limits


def test_rate_limiter_sliding_window() -> None:
    limiter = RateLimiter()
    for i in range(3):
        limiter.hit("k", 3, 60, "things", now=100 + i)
    assert limiter.remaining("k", 3, 60, now=103) == 0
    with pytest.raises(RateLimitedError) as exc:
        limiter.hit("k", 3, 60, "things", now=110)
    assert exc.value.retry_after_s == 50
    assert limiter.remaining("k", 3, 60, now=161) == 2  # the first hit has aged out
    limiter.hit("k", 3, 60, "things", now=161)


def _request(peer: str, xff: str | None) -> Request:
    headers = [(b"x-forwarded-for", xff.encode())] if xff else []
    return Request({"type": "http", "headers": headers, "client": (peer, 1234)})


def test_client_ip_trusts_only_the_configured_proxy_hops() -> None:
    spoofed = "6.6.6.6, 1.2.3.4, 10.0.0.9"  # client-supplied, viewer seen by CDN, CDN seen by ALB
    assert client_ip(_request("10.0.0.2", spoofed), 0) == "10.0.0.2"
    assert client_ip(_request("10.0.0.2", spoofed), 2) == "1.2.3.4"
    assert client_ip(_request("10.0.0.2", None), 2) == "10.0.0.2"


# --------------------------------------------------------------------------- budget


class FakeLive:
    """A non-mock provider (priced model id) that answers with the mock handlers."""

    def __init__(self, inner: MockLLMProvider) -> None:
        self._inner = inner
        self.calls = 0

    provider_name = "bedrock"
    model_name = LIVE_MODEL
    is_mock = False

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        r = self._inner.generate(request)
        return r.model_copy(
            update={"provider": "bedrock", "model_name": LIVE_MODEL, "is_mock": False}
        )


def _demo_container(
    tmp_path: Path, factory: Callable[..., Container], **overrides: Any
) -> Container:
    settings = make_settings(tmp_path, demo_mode=True, demo_secret=SECRET, **overrides)
    return factory(settings=settings)


def test_budget_cap_falls_back_to_labelled_offline_engine(
    tmp_path: Path,
    container_factory: Callable[..., Container],
    mock_llm_factory: Callable[..., MockLLMProvider],
) -> None:
    live = FakeLive(mock_llm_factory())
    settings = make_settings(
        tmp_path, demo_mode=True, demo_secret=SECRET, demo_daily_budget_usd=0.000001
    )
    c = container_factory(settings=settings, llm=live)
    assert isinstance(c.llm, BudgetedLLMProvider)
    assert c.budget is not None

    doc = c.ingestion.upload("a.pdf", "application/pdf", sample_pdf("invoice_01_acme.pdf"))
    c.workflow.process(doc.document.document_id)
    first_calls = live.calls
    assert first_calls >= 1  # live until the first recorded spend crosses the tiny cap

    invocations = c.invocations.all()
    assert any(not i.is_mock and i.estimated_cost_usd for i in invocations)
    c.budget._cached = None  # spend is cached for a few seconds; force a fresh read
    assert c.budget.exhausted()
    answer = c.rag.ask("What is the total amount due?", document_id=doc.document.document_id)
    assert live.calls == first_calls  # no further live calls once the cap is reached
    assert answer.is_mock is True and answer.provider == "mock"
    latest = max(c.invocations.all(), key=lambda i: i.created_at)
    assert latest.is_mock is True and latest.provider == "mock"


def test_budget_wrapper_is_not_used_outside_demo_mode_or_in_mock_mode(
    tmp_path: Path,
    container_factory: Callable[..., Container],
    mock_llm_factory: Callable[..., MockLLMProvider],
) -> None:
    assert not isinstance(
        container_factory(llm=FakeLive(mock_llm_factory())).llm, BudgetedLLMProvider
    )
    demo_mock = _demo_container(tmp_path / "m", container_factory)
    assert demo_mock.budget is None and demo_mock.llm.is_mock


def test_daily_budget_counts_only_live_spend_since_midnight(container: Container) -> None:
    from app.domain.models import ModelInvocation

    def inv(cost: float, is_mock: bool, hours_ago: float) -> ModelInvocation:
        return ModelInvocation(
            invocation_id=f"inv_{cost}_{is_mock}_{hours_ago}",
            operation="rag_answer",
            provider="bedrock",
            model_name=LIVE_MODEL,
            prompt_name="p",
            prompt_version="1",
            prompt_hash="h",
            latency_ms=1.0,
            input_tokens=1,
            output_tokens=1,
            estimated_cost_usd=cost,
            retry_count=0,
            success=True,
            is_mock=is_mock,
            created_at=utcnow() - timedelta(hours=hours_ago),
        )

    now = utcnow()
    for i in (inv(0.5, False, 0), inv(9.0, True, 0)):
        container.invocations.save(i)
    if now.hour >= 1:  # a call from before midnight UTC is only possible after 01:00
        container.invocations.save(inv(7.0, False, now.hour + 1))
    budget = DailyBudget(container.invocations, 1.0)
    assert budget.spent_today() == pytest.approx(0.5)
    assert not budget.exhausted()


# --------------------------------------------------------------------------- retention


def test_retention_purges_only_expired_visitor_data(
    tmp_path: Path, container_factory: Callable[..., Container]
) -> None:
    c = _demo_container(tmp_path, container_factory)
    visitor = c.ingestion.upload(
        "v.pdf", "application/pdf", sample_pdf("invoice_01_acme.pdf"), workspace_id="ws_" + "1" * 24
    ).document
    own = c.ingestion.upload("o.pdf", "application/pdf", sample_pdf("invoice_01_acme.pdf")).document
    for d in (visitor, own):
        c.workflow.process(d.document_id)
    c.rag.ask("What is the total amount due?", workspace_id=visitor.workspace_id)
    assert c.vector_store.count() > 0

    assert purge_expired(c)["documents"] == 0  # nothing is old enough yet

    counts = purge_expired(c, now=utcnow() + timedelta(hours=25))
    assert counts["documents"] == 1 and counts["answers"] == 1
    assert [d.document_id for d in c.documents.all()] == [own.document_id]
    assert c.texts.get(visitor.document_id) is None
    assert c.extractions.list_for_document(visitor.document_id) == []
    assert all(a.workspace_id == DEFAULT_WORKSPACE for a in c.answers.all())
    assert not (tmp_path / "documents" / f"{visitor.document_id}.pdf").exists()
    assert (tmp_path / "documents" / f"{own.document_id}.pdf").exists()
    hits = c.retriever.retrieve("total amount due", min_score=-1.0, top_k=50)
    assert {r.chunk.document_id for r in hits.results} == {own.document_id}
    assert "demo.retention_purge" in {e.event_type for e in c.audit.history()}
    assert c.audit.verify_chain()[0]


# --------------------------------------------------------------------------- migration


def test_startup_migration_adds_workspaces_to_a_legacy_database(tmp_path: Path) -> None:
    db = tmp_path / "legacy.db"
    con = sqlite3.connect(db)
    con.executescript(
        """
        CREATE TABLE documents (document_id VARCHAR(64) PRIMARY KEY, sha256 VARCHAR(64) NOT NULL,
            status VARCHAR(32) NOT NULL, document_type VARCHAR(32), created_at DATETIME NOT NULL,
            updated_at DATETIME NOT NULL, payload JSON NOT NULL);
        CREATE UNIQUE INDEX ix_documents_sha256 ON documents (sha256);
        CREATE TABLE reviews (review_id VARCHAR(64) PRIMARY KEY, document_id VARCHAR(64),
            status VARCHAR(32) NOT NULL, target_type VARCHAR(32) NOT NULL,
            created_at DATETIME NOT NULL, payload JSON NOT NULL);
        CREATE TABLE answers (answer_id VARCHAR(64) PRIMARY KEY, document_id VARCHAR(64),
            created_at DATETIME NOT NULL, payload JSON NOT NULL);
        """
    )
    con.close()

    engine = create_db_engine(f"sqlite:///{db}")
    insp = inspect(engine)
    for table in ("documents", "reviews", "answers"):
        assert "workspace_id" in {col["name"] for col in insp.get_columns(table)}
    create_db_engine(f"sqlite:///{db}")  # idempotent
    with engine.connect() as conn:
        version = conn.execute(text("SELECT value FROM schema_meta")).scalar_one()
    assert version == str(SCHEMA_VERSION)

    repo = DocumentRepository(make_session_factory(engine))

    def doc(doc_id: str, ws: str) -> Document:
        meta = DocumentMetadata(
            filename="f.pdf",
            content_type="application/pdf",
            size_bytes=1,
            sha256="a" * 64,
            page_count=1,
            has_text_layer=True,
        )
        return Document(document_id=doc_id, metadata=meta, workspace_id=ws)

    repo.add(doc("doc_1", DEFAULT_WORKSPACE))
    repo.add(doc("doc_2", "ws_" + "2" * 24))  # same file, other workspace: allowed
    with pytest.raises(IntegrityError):
        repo.add(doc("doc_3", DEFAULT_WORKSPACE))  # same file, same workspace: rejected
    assert repo.find_by_sha256("a" * 64).document_id == "doc_1"  # type: ignore[union-attr]
