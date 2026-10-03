"""FastAPI dependencies: container access, authentication and role-based authorization."""

from __future__ import annotations

import hmac
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Cookie, Depends, Header, Request

from app.core.config import Role, Settings
from app.core.errors import (
    AuthenticationError,
    AuthorizationError,
    DocumentNotFoundError,
    ReviewNotFoundError,
)
from app.core.hashing import sha256_text
from app.demo.limits import DAY_S, documents_key, questions_key, runs_key
from app.demo.sessions import COOKIE_NAME, verify_session
from app.domain.models import DEFAULT_WORKSPACE, Document, ReviewCase
from app.services.container import Container


def get_container(request: Request) -> Container:
    container: Container = request.app.state.container
    return container


ContainerDep = Annotated[Container, Depends(get_container)]


@dataclass(frozen=True)
class Principal:
    principal_id: str
    role: Role
    authenticated: bool
    # Set only for public-demo visitors: every read and write is confined to this workspace.
    # ``None`` means unscoped (local development or an API-key operator).
    workspace_id: str | None = None

    @property
    def actor(self) -> str:
        if self.workspace_id is not None:
            return f"visitor:{self.principal_id}"
        return f"{'api_key' if self.authenticated else 'local'}:{self.principal_id}"

    def can_access(self, workspace_id: str) -> bool:
        return self.workspace_id is None or self.workspace_id == workspace_id


LOCAL_PRINCIPAL = Principal(principal_id="local-dev", role=Role.ADMIN, authenticated=False)


def _api_key_principal(settings: Settings, x_api_key: str) -> Principal:
    for key, role in settings.api_key_roles().items():
        if hmac.compare_digest(key.encode(), x_api_key.encode()):
            # identity is a hash prefix of the key so raw keys never reach logs or audit records
            return Principal(
                principal_id=f"key-{sha256_text(key)[:10]}", role=role, authenticated=True
            )
    raise AuthenticationError("invalid API key")


def visitor_principal(workspace_id: str) -> Principal:
    # Visitors may upload, process, ask and resolve reviews -- but only inside their workspace.
    return Principal(
        principal_id=workspace_id.removeprefix("ws_")[:12],
        role=Role.REVIEWER,
        authenticated=True,
        workspace_id=workspace_id,
    )


def get_principal(
    container: ContainerDep,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
    demo_cookie: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
) -> Principal:
    settings = container.settings
    if settings.demo_mode:
        if x_api_key:
            return _api_key_principal(settings, x_api_key)
        assert settings.demo_secret is not None
        workspace_id = verify_session(
            settings.demo_secret.get_secret_value(),
            demo_cookie,
            settings.demo_session_ttl_hours * 3600,
        )
        if workspace_id is None:
            raise AuthenticationError("no valid demo session; start one at POST /demo/session")
        return visitor_principal(workspace_id)
    if not settings.auth_enabled:
        return LOCAL_PRINCIPAL
    if not x_api_key:
        raise AuthenticationError("missing X-API-Key header")
    return _api_key_principal(settings, x_api_key)


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def require_role(minimum: Role) -> Callable[[Principal], Principal]:
    def check(principal: PrincipalDep) -> Principal:
        if principal.role.rank < minimum.rank:
            raise AuthorizationError(f"requires role '{minimum.value}' or higher")
        return principal

    return check


def require_operator(
    principal: Annotated[Principal, Depends(require_role(Role.VIEWER))],
) -> Principal:
    """System-wide views (metrics, drift, evaluations) are never exposed to demo visitors."""
    if principal.workspace_id is not None:
        raise AuthorizationError("operator endpoint; not available to demo visitors")
    return principal


Viewer = Annotated[Principal, Depends(require_role(Role.VIEWER))]
Analyst = Annotated[Principal, Depends(require_role(Role.ANALYST))]
Reviewer = Annotated[Principal, Depends(require_role(Role.REVIEWER))]
Admin = Annotated[Principal, Depends(require_role(Role.ADMIN))]
Operator = Annotated[Principal, Depends(require_operator)]


# --------------------------------------------------------------------------- workspace scoping


def workspace_for(principal: Principal) -> str:
    """Workspace that new documents and answers belong to."""
    return principal.workspace_id or DEFAULT_WORKSPACE


def owned_document(container: Container, principal: Principal, document_id: str) -> Document:
    """Load a document the principal may see. Other workspaces' documents look nonexistent."""
    doc = container.documents.get(document_id)
    if not principal.can_access(doc.workspace_id):
        raise DocumentNotFoundError(f"document {document_id} not found")
    return doc


def owned_review(container: Container, principal: Principal, review_id: str) -> ReviewCase:
    case = container.reviews.get(review_id)
    if not principal.can_access(case.workspace_id):
        raise ReviewNotFoundError(f"review {review_id} not found")
    return case


AllowanceKind = Literal["documents", "runs", "questions"]


def _allowance(
    container: Container, workspace_id: str, kind: AllowanceKind
) -> tuple[str, int, str]:
    s = container.settings
    return {
        "documents": (
            documents_key(workspace_id),
            s.demo_docs_per_session_day,
            "documents per day",
        ),
        # reprocessing is allowed, within reason
        "runs": (
            runs_key(workspace_id),
            2 * s.demo_docs_per_session_day,
            "processing runs per day",
        ),
        "questions": (
            questions_key(workspace_id),
            s.demo_questions_per_session_day,
            "questions per day",
        ),
    }[kind]


def require_allowance(container: Container, principal: Principal, kind: AllowanceKind) -> None:
    """Fail fast if a demo visitor has no allowance left (no-op for everyone else)."""
    if principal.workspace_id is None:
        return
    key, limit, what = _allowance(container, principal.workspace_id, kind)
    if container.limiter.remaining(key, limit, DAY_S) <= 0:
        container.limiter.hit(key, limit, DAY_S, what)  # raises with a Retry-After


def charge_visitor(container: Container, principal: Principal, kind: AllowanceKind) -> None:
    """Count one unit of a demo visitor's daily allowance (no-op for everyone else)."""
    if principal.workspace_id is None:
        return
    key, limit, what = _allowance(container, principal.workspace_id, kind)
    container.limiter.hit(key, limit, DAY_S, what)
