"""API-key authentication and role-based authorization."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import create_app
from tests.support import make_settings, sample_pdf

KEYS = {
    "viewer-key": "viewer",
    "analyst-key": "analyst",
    "reviewer-key": "reviewer",
    "admin-key": "admin",
}


def h(key: str) -> dict[str, str]:
    return {"X-API-Key": key}


@pytest.fixture
def client(tmp_path: Path) -> Iterator[TestClient]:
    settings = make_settings(tmp_path, auth_enabled=True, api_keys_json=json.dumps(KEYS))
    with TestClient(create_app(settings)) as c:
        yield c


def upload(client: TestClient, key: str, name: str = "income_statement_03_aurora.pdf") -> object:
    return client.post(
        "/documents/upload",
        headers=h(key),
        files={"file": (name, sample_pdf(name), "application/pdf")},
    )


def test_health_is_public(client: TestClient) -> None:
    assert client.get("/health").status_code == 200


def test_missing_and_invalid_keys(client: TestClient) -> None:
    r = client.get("/reviews")
    assert r.status_code == 401
    assert r.json()["error"]["type"] == "unauthenticated"
    assert client.get("/reviews", headers=h("wrong")).status_code == 401


def test_role_hierarchy(client: TestClient) -> None:
    assert client.get("/reviews", headers=h("viewer-key")).status_code == 200
    assert upload(client, "viewer-key").status_code == 403  # type: ignore[attr-defined]

    up = upload(client, "analyst-key")
    assert up.status_code == 201  # type: ignore[attr-defined]
    doc_id = up.json()["document"]["document_id"]  # type: ignore[attr-defined]
    processed = client.post(f"/documents/{doc_id}/process", headers=h("analyst-key")).json()
    review_id = processed["review_id"]

    assert (
        client.post(f"/reviews/{review_id}/approve", json={}, headers=h("analyst-key")).status_code
        == 403
    )
    assert client.post("/evaluations/run", headers=h("reviewer-key")).status_code == 403
    assert client.get("/audit/verify", headers=h("reviewer-key")).status_code == 403

    approved = client.post(
        f"/reviews/{review_id}/approve",
        json={"reviewer_id": "spoofed-name"},
        headers=h("reviewer-key"),
    )
    assert approved.status_code == 200
    # authenticated identity wins over the client-supplied reviewer_id
    assert approved.json()["reviewer_id"].startswith("key-")
    assert approved.json()["reviewer_id"] != "spoofed-name"

    assert client.get("/audit/verify", headers=h("admin-key")).status_code == 200


def test_raw_keys_never_reach_audit_trail(client: TestClient) -> None:
    up = upload(client, "analyst-key")
    doc_id = up.json()["document"]["document_id"]  # type: ignore[attr-defined]
    audit = client.get(f"/documents/{doc_id}/audit", headers=h("viewer-key")).text
    assert "analyst-key" not in audit
    assert "api_key:key-" in audit
