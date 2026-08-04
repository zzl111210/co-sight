"""Signed bearer tokens with a development header compatibility mode."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer


class AuthRole(str, Enum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    APPROVER = "approver"
    ADMIN = "admin"


@dataclass(frozen=True)
class AuthContext:
    actor: str
    role: AuthRole
    tenant_id: str = "default"
    token_id: str = ""


def auth_mode() -> str:
    return os.getenv("NETHEAL_AUTH_MODE", "development").strip().lower()


class TokenService:
    """Issue and verify time-limited signed tokens.

    Production deployments should replace the development issuer with the
    organisation's OIDC provider. The local login endpoint is intentionally
    disabled when NETHEAL_AUTH_MODE=production.
    """

    def __init__(
        self,
        secret_key: str | None = None,
        max_age_seconds: int = 3600,
    ) -> None:
        configured_secret = secret_key or os.getenv("NETHEAL_TOKEN_SECRET", "")
        if not configured_secret:
            if auth_mode() == "production":
                raise RuntimeError(
                    "NETHEAL_TOKEN_SECRET is required in production mode"
                )
            configured_secret = "netheal-development-secret-change-me"
        self.max_age_seconds = max_age_seconds
        self._serializer = URLSafeTimedSerializer(
            configured_secret,
            salt="netheal-bearer-v1",
        )

    def issue(
        self,
        actor: str,
        role: AuthRole,
        tenant_id: str = "default",
    ) -> str:
        if not actor.strip():
            raise ValueError("actor must not be empty")
        return self._serializer.dumps(
            {
                "sub": actor.strip(),
                "role": role.value,
                "tenant_id": tenant_id.strip() or "default",
            }
        )

    def verify(self, token: str) -> AuthContext:
        try:
            payload: dict[str, Any] = self._serializer.loads(
                token,
                max_age=self.max_age_seconds,
            )
        except SignatureExpired as exc:
            raise PermissionError("authentication token has expired") from exc
        except BadSignature as exc:
            raise PermissionError("authentication token is invalid") from exc

        actor = str(payload.get("sub", "")).strip()
        try:
            role = AuthRole(str(payload.get("role", "")))
        except ValueError as exc:
            raise PermissionError("authentication token has an invalid role") from exc
        if not actor:
            raise PermissionError("authentication token has no actor")
        return AuthContext(
            actor=actor,
            role=role,
            tenant_id=str(payload.get("tenant_id", "default")),
        )

    def refresh(self, token: str) -> str:
        context = self.verify(token)
        return self.issue(context.actor, context.role, context.tenant_id)


def bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, separator, value = authorization.partition(" ")
    if separator and scheme.lower() == "bearer" and value.strip():
        return value.strip()
    raise PermissionError("Authorization must use the Bearer scheme")


def resolve_auth_context(
    token_service: TokenService,
    authorization: str | None = None,
    actor_header: str | None = None,
    role_header: str | None = None,
    tenant_header: str | None = None,
) -> AuthContext:
    token = bearer_token(authorization)
    if token:
        return token_service.verify(token)
    if auth_mode() == "production":
        raise PermissionError("Bearer authentication is required")
    try:
        role = AuthRole(role_header or "viewer")
    except ValueError as exc:
        raise PermissionError(f"invalid NetHeal role: {role_header}") from exc
    return AuthContext(
        actor=actor_header or "cockpit-user",
        role=role,
        tenant_id=tenant_header or "default",
    )
