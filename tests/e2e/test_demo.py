"""Public demo mode over HTTP: visitor sessions, workspace isolation, samples, limits."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from app.demo.samples import SAMPLES
from app.demo.sessions import COOKIE_NAME, issue_session
from tests.support import GROUND_TRUTH, make_settings, sample_pdf

SECRET = "s" * 40
ADMIN = {"X-API-Key": "admin-key"}


def demo_settings(tmp_path: Path, **overrides: Any) -> Any:
    values: dict[str, Any] = {
        "demo_mode": True,
        "demo_secret": SECRET,
        "demo_cookie_secure": False,
        "api_keys_json": json.dumps({"admin-key": "admin"}),
    }
    values.update(overrides)
    return make_settings(tmp_path, **values)


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    with TestClient(create_app(demo_settings(tmp_path))) as c:
        yield c


def start(client: TestClient) -> str:
    """Start a fresh visitor session; returns the cookie value."""
    client.cookies.clear()
    r = client.post("/demo/session")
    assert r.status_code == 200, r.text
    assert r.json()["created"] is True
    return str(client.cookies[COOKIE_NAME])


def use(client: TestClient, cookie: str) -> None:
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, cookie)


def load(client: TestClient, sample_id: str = "clean-invoice") -> dict[str, Any]:
    r = client.post(f"/demo/samples/{sample_id}")
    assert r.status_code == 201, r.text
    body: dict[str, Any] = r.json()
    return body


def process(client: TestClient, doc_id: str) -> dict[str, Any]:
    r = client.post(f"/documents/{doc_id}/process")
    assert r.status_code == 200, r.text
    body: dict[str, Any] = r.json()
    return body


# --------------------------------------------------------------------------- sessions


def test_api_requires_a_session(client: TestClient) -> None:
    r = client.get("/documents")
    assert r.status_code == 401
    assert "demo session" in r.json()["error"]["message"]


def test_session_cookie_is_httponly_strict_and_reused(client: TestClient) -> None:
    r = client.post("/demo/session")
    header = r.headers["set-cookie"].lower()
    assert "httponly" in header and "samesite=strict" in header
    again = client.post("/demo/session")
    assert again.json()["created"] is False
    assert "set-cookie" not in again.headers
    assert client.get("/documents").status_code == 200


def test_tampered_and_expired_cookies_are_rejected(client: TestClient) -> None:
    cookie = start(client)
    ws, issued, sig = cookie.split(".")
    use(client, f"{ws}.{issued}.{'0' * len(sig)}")
    assert client.get("/documents").status_code == 401
    use(client, f"ws_{'a' * 24}.{issued}.{sig}")
    assert client.get("/documents").status_code == 401
    _, expired = issue_session(SECRET, now=time.time() - 25 * 3600)
    use(client, expired)
    assert client.get("/documents").status_code == 401


def test_visitors_cannot_reach_operator_endpoints(client: TestClient) -> None:
    start(client)
    for method, path in (
        ("GET", "/metrics"),
        ("GET", "/drift/report"),
        ("GET", "/evaluations"),
        ("POST", "/evaluations/run"),
        ("GET", "/audit/verify"),
    ):
        assert client.request(method, path).status_code == 403, path
    client.cookies.clear()
    assert client.get("/metrics", headers=ADMIN).status_code == 200
    assert client.get("/audit/verify", headers=ADMIN).json()["valid"] is True


def test_demo_routes_absent_when_demo_mode_is_off(tmp_path: Path) -> None:
    with TestClient(create_app(make_settings(tmp_path))) as c:
        assert c.post("/demo/session").status_code == 404
        assert c.get("/documents").status_code == 200  # local mode unchanged


# --------------------------------------------------------------------------- workspaces


def test_workspaces_are_isolated(client: TestClient) -> None:
    alice = start(client)
    doc_a = load(client, "conflicting-figures")["document"]["document_id"]
    processed = process(client, doc_a)
    assert processed["status"] == "NEEDS_REVIEW"
    review_a = processed["review_id"]

    start(client)  # bob
    assert client.get("/documents").json() == []
    assert client.get(f"/documents/{doc_a}").status_code == 404
    assert client.get(f"/documents/{doc_a}/extractions").status_code == 404
    assert client.get(f"/documents/{doc_a}/audit").status_code == 404
    assert client.post(f"/documents/{doc_a}/process").status_code == 404
    assert client.post(f"/documents/{doc_a}/ask", json={"question": "balance?"}).status_code == 404
    assert client.get("/reviews").json()["count"] == 0
    assert client.get(f"/reviews/{review_a}").status_code == 404
    assert client.post(f"/reviews/{review_a}/approve", json={}).status_code == 404

    # the corpus question cannot retrieve alice's statement
    ans = client.post("/ask", json={"question": "What are the total assets?"}).json()
    assert ans["refused"] is True and ans["citations"] == []

    # the same file is a new document in bob's workspace (dedup is per workspace)
    bob_upload = load(client, "conflicting-figures")
    assert bob_upload["duplicate"] is False
    assert bob_upload["document"]["document_id"] != doc_a

    use(client, alice)
    assert [d["document_id"] for d in client.get("/documents").json()] == [doc_a]
    approved = client.post(f"/reviews/{review_a}/approve", json={"comment": "checked"})
    assert approved.status_code == 200
    assert approved.json()["reviewer_id"].startswith(alice.split(".")[0].removeprefix("ws_")[:6])

    # operators still see every workspace
    client.cookies.clear()
    assert len(client.get("/documents", headers=ADMIN).json()) == 2


def test_visitor_answers_cite_only_their_own_documents(client: TestClient) -> None:
    start(client)
    doc = load(client)["document"]["document_id"]
    process(client, doc)
    ans = client.post("/ask", json={"question": "What is the total amount due?"}).json()
    assert not ans["refused"]
    assert {c["document_id"] for c in ans["citations"]} == {doc}


# --------------------------------------------------------------------------- samples


def test_samples_are_allow_listed(client: TestClient) -> None:
    samples = client.get("/demo/samples").json()
    assert {s["sample_id"] for s in samples} >= {
        "clean-invoice",
        "conflicting-figures",
        "hidden-instructions",
    }
    pdf = client.get("/demo/samples/clean-invoice/file")
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.content.startswith(b"%PDF")
    assert client.get("/demo/samples/..%2F..%2Fetc%2Fpasswd/file").status_code == 404
    start(client)
    assert client.post("/demo/samples/not-a-sample").status_code == 404


def test_sample_outcomes_shown_to_visitors_match_ground_truth() -> None:
    truth = {d["file"]: d["expected_outcome"] for d in GROUND_TRUTH["documents"]}
    for sample in SAMPLES:
        assert sample.expected_outcome == truth[sample.filename], sample.sample_id


def test_background_processing_reports_progress(client: TestClient) -> None:
    start(client)
    doc = load(client, "hidden-instructions")["document"]["document_id"]
    r = client.post(f"/documents/{doc}/process/background")
    assert r.status_code == 202
    assert r.json()["processing"] is True
    deadline = time.monotonic() + 30
    body: dict[str, Any] = {}
    while time.monotonic() < deadline:
        body = client.get(f"/documents/{doc}").json()
        if not body["processing"]:
            break
        time.sleep(0.05)
    assert body["processing"] is False
    assert body["status"] == "NEEDS_REVIEW"
    assert "prompt_injection_suspected" in body["security_flags"]
    events = [e["event_type"] for e in client.get(f"/documents/{doc}/audit").json()["events"]]
    assert "workflow.started" in events
    check = client.get(f"/documents/{doc}/audit/verify").json()
    assert check["valid"] is True and check["checked_events"] == len(events)


def test_regular_upload_lands_in_the_visitor_workspace(client: TestClient) -> None:
    start(client)
    r = client.post(
        "/documents/upload",
        files={"file": ("mine.pdf", sample_pdf("invoice_02_brightpath.pdf"), "application/pdf")},
    )
    assert r.status_code == 201
    assert [d["filename"] for d in client.get("/documents").json()] == ["mine.pdf"]


# --------------------------------------------------------------------------- limits


def test_per_visitor_document_and_question_limits(tmp_path: Path) -> None:
    settings = demo_settings(
        tmp_path, demo_docs_per_session_day=1, demo_questions_per_session_day=1
    )
    with TestClient(create_app(settings)) as client:
        start(client)
        doc = load(client)["document"]["document_id"]
        # re-loading the same sample is a duplicate and costs nothing
        assert client.post("/demo/samples/clean-invoice").json()["duplicate"] is True
        over = client.post("/demo/samples/european-invoice")
        assert over.status_code == 429
        assert int(over.headers["Retry-After"]) > 0
        assert over.json()["error"]["type"] == "rate_limited"

        process(client, doc)
        assert (
            client.post(f"/documents/{doc}/ask", json={"question": "Amount due?"}).status_code
            == 200
        )
        assert client.post(f"/documents/{doc}/ask", json={"question": "Vendor?"}).status_code == 429

        status = client.get("/demo/status").json()
        assert status["documents_remaining"] == 0
        assert status["questions_remaining"] == 0


def test_new_sessions_per_ip_are_limited(tmp_path: Path) -> None:
    with TestClient(create_app(demo_settings(tmp_path, demo_sessions_per_ip_hour=1))) as client:
        start(client)
        client.cookies.clear()
        assert client.post("/demo/session").status_code == 429


def test_requests_per_ip_are_limited(tmp_path: Path) -> None:
    with TestClient(create_app(demo_settings(tmp_path, demo_requests_per_ip_minute=10))) as client:
        start(client)
        codes = [client.get("/documents").status_code for _ in range(12)]
        assert codes.count(429) >= 1
        assert client.get("/health").status_code == 200  # probes are never limited


def test_demo_upload_caps(tmp_path: Path) -> None:
    with TestClient(create_app(demo_settings(tmp_path, demo_max_pages=1))) as client:
        start(client)
        name = "balance_sheet_04_litware_multipage.pdf"
        r = client.post(
            "/documents/upload", files={"file": (name, sample_pdf(name), "application/pdf")}
        )
        assert r.status_code == 422
        assert "pages" in r.json()["error"]["message"]
        status = client.get("/demo/status").json()
        assert status["limits"]["max_pages"] == 1
        assert status["limits"]["max_upload_mb"] == 5


def test_status_reports_offline_engine_in_mock_mode(client: TestClient) -> None:
    body = client.get("/demo/status").json()
    assert body["ai_mode"] == "offline"
    assert body["offline_reason"] == "configured_offline"
    assert body["session_active"] is False
    start(client)
    body = client.get("/demo/status").json()
    assert body["session_active"] is True
    assert body["documents_remaining"] == body["limits"]["documents_per_day"]


# --------------------------------------------------------------------------- document viewer


def test_page_images_are_scoped_cached_and_revalidated(client: TestClient) -> None:
    start(client)
    doc = load(client, "conflicting-figures")["document"]
    url = f"/documents/{doc['document_id']}/pages/2/image"

    r = client.get(url)
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG")
    assert r.headers["cache-control"] == "private, max-age=3600"
    etag = r.headers["etag"]

    again = client.get(url, headers={"If-None-Match": etag})
    assert again.status_code == 304 and again.content == b""
    assert client.get(url, headers={"If-None-Match": '"stale"'}).status_code == 200

    assert client.get(f"/documents/{doc['document_id']}/pages/3/image").status_code == 404
    assert client.get(f"/documents/{doc['document_id']}/pages/0/image").status_code == 422

    start(client)  # another visitor
    assert client.get(url).status_code == 404
    client.cookies.clear()
    assert client.get(url).status_code == 401


def test_locate_returns_boxes_for_both_conflicting_values(client: TestClient) -> None:
    start(client)
    doc_id = load(client, "conflicting-figures")["document"]["document_id"]
    r = client.post(
        f"/documents/{doc_id}/locate",
        json={
            "queries": [
                {"text": "9,750,000"},
                {"text": "9,570,000"},
                {"text": "total ASSETS:  9,570,000", "page": 2},
                {"text": "not in this document"},
            ]
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_text_layer"] is True
    assert body["positions"] == "text_layer"
    first, second, folded, absent = body["results"]
    assert [m["page_number"] for m in first["matches"]] == [1]
    assert [m["page_number"] for m in second["matches"]] == [2]
    assert folded["page"] == 2 and folded["matches"][0]["page_number"] == 2
    assert absent["matches"] == []
    rect = first["matches"][0]["rects"][0]
    assert set(rect) == {"x", "y", "width", "height"}
    assert 0 <= rect["x"] <= 1 and 0 <= rect["y"] <= 1


def test_locate_validates_input_and_workspace(client: TestClient) -> None:
    start(client)
    doc_id = load(client)["document"]["document_id"]
    url = f"/documents/{doc_id}/locate"
    too_many = {"queries": [{"text": "x"}] * 51}
    too_long = {"queries": [{"text": "x" * 501}]}
    for body in (too_many, too_long, {"queries": []}, {"queries": [{"text": ""}]}):
        assert client.post(url, json=body).status_code == 422
    assert client.post(url, json={"queries": [{"text": "x", "page": 0}]}).status_code == 422
    assert client.post(url, json={"queries": [{"text": "x"}], "extra": 1}).status_code == 422

    start(client)
    assert client.post(url, json={"queries": [{"text": "Amount"}]}).status_code == 404
