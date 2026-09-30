"""FastAPI dependencies: container access, authentication and role-based authorization."""

from __future__ import annotations

import hmac
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, Request

from app.core.config import Role
from app.core.errors import AuthenticationError, AuthorizationError
from app.core.hashing import sha256_text
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

    @property
    def actor(self) -> str:
        return f"{'api_key' if self.authenticated else 'local'}:{self.principal_id}"


LOCAL_PRINCIPAL = Principal(principal_id="local-dev", role=Role.ADMIN, authenticated=False)


def get_principal(
    container: ContainerDep,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> Principal:
    settings = container.settings
    if not settings.auth_enabled:
        return LOCAL_PRINCIPAL
    if not x_api_key:
        raise AuthenticationError("missing X-API-Key header")
    for key, role in settings.api_key_roles().items():
        if hmac.compare_digest(key.encode(), x_api_key.encode()):
            # identity is a hash prefix of the key so raw keys never reach logs or audit records
            return Principal(
                principal_id=f"key-{sha256_text(key)[:10]}", role=role, authenticated=True
            )
    raise AuthenticationError("invalid API key")


PrincipalDep = Annotated[Principal, Depends(get_principal)]


def require_role(minimum: Role) -> Callable[[Principal], Principal]:
    def check(principal: PrincipalDep) -> Principal:
        if principal.role.rank < minimum.rank:
            raise AuthorizationError(f"requires role '{minimum.value}' or higher")
        return principal

    return check


Viewer = Annotated[Principal, Depends(require_role(Role.VIEWER))]
Analyst = Annotated[Principal, Depends(require_role(Role.ANALYST))]
Reviewer = Annotated[Principal, Depends(require_role(Role.REVIEWER))]
Admin = Annotated[Principal, Depends(require_role(Role.ADMIN))]
