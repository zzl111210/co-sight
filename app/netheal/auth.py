"""JWT-based authentication and role-based access control for NetHeal-Agent.

Supports two modes:
- Production: JWT tokens issued by an OAuth2/OIDC provider.
- Development: Header-based actor/role passthrough (backward-compatible).

See: CODEX_HANDOFF.md §19.2 (P1-2)
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

import jwt
from app.common.logger_util import logger


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------


class AuthRole(str, Enum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    APPROVER = "approver"
    ADMIN = "admin"


ROLE_HIERARCHY: dict[AuthRole, int] = {
    AuthRole.VIEWER: 0,
    AuthRole.OPERATOR: 10,
    AuthRole.APPROVER: 20,
    AuthRole.ADMIN: 30,
}


@dataclass
class AuthContext:
    """Authenticated user context extracted from a validated token or header."""

    actor: str
    role: AuthRole
    tenant_id: str = "default"
    token_id: str = ""
    issued_at: float = field(default_factory=time.time)
    expires_at: float = 0.0

    def has_role(self, minimum: AuthRole) -> bool:
        return ROLE_HIERARCHY.get(self.role, 0) >= ROLE_HIERARCHY.get(minimum, 0)

    def is_expired(self) -> bool:
        if self.expires_at <= 0:
            return False
        return time.time() > self.expires_at


# ---------------------------------------------------------------------------
# Token service
# ---------------------------------------------------------------------------


class TokenService:
    """Issues and validates JWT tokens.

    In development mode, tokens are self-signed with a local secret.
    In production, configure the OIDC discovery URL and expected audience.
    """

    def __init__(
        self,
        secret_key: str | None = None,
        algorithm: str = "HS256",
        issuer: str = "netheal-agent",
        default_ttl_seconds: int = 3600,
        oidc_discovery_url: str | None = None,
        oidc_audience: str | None = None,
    ) -> None:
        self.secret_key = secret_key or os.environ.get("NETHEAL_JWT_SECRET", "netheal-dev-secret-change-in-production")
        self.algorithm = algorithm
        self.issuer = issuer
        self.default_ttl_seconds = default_ttl_seconds
        self.oidc_discovery_url = oidc_discovery_url
        self.oidc_audience = oidc_audience
        self._dev_mode = os.environ.get("NETHEAL_AUTH_MODE", "dev").lower() != "production"

    def issue_token(
        self,
        actor: str,
        role: AuthRole,
        tenant_id: str = "default",
        ttl_seconds: int | None = None,
    ) -> str:
        """Issue a new JWT token for the given actor and role."""
        now = time.time()
        payload = {
            "sub": actor,
            "role": role.value,
            "tenant_id": tenant_id,
            "iss": self.issuer,
            "iat": now,
            "exp": now + (ttl_seconds or self.default_ttl_seconds),
            "jti": f"netheal-{int(now * 1000)}-{os.urandom(4).hex()}",
        }
        token = jwt.encode(payload, self.secret_key, algorithm=self.algorithm)
        logger.debug(f"Issued JWT for actor={actor}, role={role.value}, tenant={tenant_id}")
        return token

    def validate_token(self, token: str) -> AuthContext | None:
        """Validate a JWT token and return the corresponding AuthContext.

        Returns None if the token is invalid, expired, or malformed.
        """
        try:
            payload = jwt.decode(
                token,
                self.secret_key,
                algorithms=[self.algorithm],
                issuer=self.issuer,
                options={"verify_exp": True},
            )
            role_str = payload.get("role", "viewer")
            try:
                role = AuthRole(role_str)
            except ValueError:
                logger.warning(f"Unknown role in token: {role_str}, defaulting to viewer")
                role = AuthRole.VIEWER

            return AuthContext(
                actor=payload.get("sub", "unknown"),
                role=role,
                tenant_id=payload.get("tenant_id", "default"),
                token_id=payload.get("jti", ""),
                issued_at=payload.get("iat", time.time()),
                expires_at=payload.get("exp", 0),
            )
        except jwt.ExpiredSignatureError:
            logger.warning("JWT token has expired")
            return None
        except jwt.InvalidTokenError as exc:
            logger.warning(f"Invalid JWT token: {exc}")
            return None

    def refresh_token(self, token: str) -> str | None:
        """Refresh a token if it's still valid but close to expiry."""
        ctx = self.validate_token(token)
        if ctx is None:
            return None
        remaining = ctx.expires_at - time.time()
        if remaining > 300:  # more than 5 minutes remaining
            return token
        return self.issue_token(ctx.actor, ctx.role, ctx.tenant_id)


# ---------------------------------------------------------------------------
# Development-mode passthrough (backward-compatible)
# ---------------------------------------------------------------------------


def dev_auth_context(
    actor: str | None = None,
    role: str | None = None,
    tenant_id: str = "default",
) -> AuthContext:
    """Create an AuthContext from request headers in development mode.

    This is the backward-compatible path that preserves the existing
    X-NetHeal-Actor / X-NetHeal-Role header mechanism.
    """
    actor = actor or "cockpit-user"
    try:
        role_enum = AuthRole(role or "viewer")
    except ValueError:
        role_enum = AuthRole.VIEWER

    return AuthContext(
        actor=actor,
        role=role_enum,
        tenant_id=tenant_id,
        token_id=f"dev-{int(time.time())}",
    )


# ---------------------------------------------------------------------------
# Authentication middleware factory
# ---------------------------------------------------------------------------


def create_auth_dependency(
    token_service: TokenService | None = None,
    dev_mode: bool | None = None,
):
    """Create a FastAPI dependency for authentication.

    In dev mode, falls back to X-NetHeal-Actor / X-NetHeal-Role headers.
    In production mode, requires a valid Bearer token.

    Usage:
        from fastapi import Depends

        require_auth = create_auth_dependency()
        router.include_router(..., dependencies=[Depends(require_auth)])
    """
    if dev_mode is None:
        dev_mode = os.environ.get("NETHEAL_AUTH_MODE", "dev").lower() != "production"

    async def _dependency(
        authorization: str | None = None,
        x_netheal_actor: str | None = None,
        x_netheal_role: str | None = None,
        x_netheal_tenant: str | None = None,
    ) -> AuthContext:
        from fastapi import HTTPException

        # Production: validate Bearer token
        if not dev_mode and authorization and authorization.startswith("Bearer "):
            if token_service is None:
                raise HTTPException(status_code=500, detail="Token service not configured")
            token = authorization.removeprefix("Bearer ").strip()
            ctx = token_service.validate_token(token)
            if ctx is None:
                raise HTTPException(status_code=401, detail="Invalid or expired token")
            return ctx

        # Development: header passthrough
        if dev_mode:
            return dev_auth_context(
                actor=x_netheal_actor,
                role=x_netheal_role,
                tenant_id=x_netheal_tenant or "default",
            )

        raise HTTPException(status_code=401, detail="Authentication required")

    return _dependency


# ---------------------------------------------------------------------------
# Approval workflow service
# ---------------------------------------------------------------------------


@dataclass
class ApprovalRequest:
    """A pending approval for a network change."""

    id: str
    incident_id: str
    requester: str
    risk_level: str
    change_summary: str
    commands: list[str]
    rollback_plan: str
    status: str = "pending"  # pending | approved | rejected
    approved_by: str = ""
    approved_at: str = ""
    comment: str = ""


class ApprovalService:
    """Manages the change approval workflow.

    In development, approvals are automatically granted for medium-risk
    changes when the actor has approver role. In production, this would
    integrate with an external workflow system (Jira, ServiceNow, etc.).
    """

    def __init__(self, store=None) -> None:
        self._pending: dict[str, ApprovalRequest] = {}
        self._store = store

    def create_approval(
        self,
        incident_id: str,
        requester: str,
        risk_level: str,
        change_summary: str,
        commands: list[str],
        rollback_plan: str,
    ) -> ApprovalRequest:
        import uuid

        req = ApprovalRequest(
            id=f"APR-{uuid.uuid4().hex[:8].upper()}",
            incident_id=incident_id,
            requester=requester,
            risk_level=risk_level,
            change_summary=change_summary,
            commands=commands,
            rollback_plan=rollback_plan,
        )
        self._pending[req.id] = req
        logger.info(f"Approval request created: {req.id} for incident {incident_id}, risk={risk_level}")
        return req

    def approve(self, approval_id: str, approved_by: str, comment: str = "") -> ApprovalRequest:
        from datetime import datetime, timezone

        if approval_id not in self._pending:
            raise KeyError(f"Approval not found: {approval_id}")

        req = self._pending[approval_id]
        if req.status != "pending":
            raise ValueError(f"Approval {approval_id} is already {req.status}")

        req.status = "approved"
        req.approved_by = approved_by
        req.approved_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        req.comment = comment
        logger.info(f"Approval {approval_id} approved by {approved_by}")
        return req

    def reject(self, approval_id: str, rejected_by: str, reason: str = "") -> ApprovalRequest:
        if approval_id not in self._pending:
            raise KeyError(f"Approval not found: {approval_id}")

        req = self._pending[approval_id]
        req.status = "rejected"
        req.approved_by = rejected_by
        req.comment = reason
        logger.info(f"Approval {approval_id} rejected by {rejected_by}: {reason}")
        return req

    def get_approval(self, approval_id: str) -> ApprovalRequest | None:
        return self._pending.get(approval_id)

    def list_pending(self) -> list[ApprovalRequest]:
        return [r for r in self._pending.values() if r.status == "pending"]

    def is_approved(self, approval_id: str) -> bool:
        req = self._pending.get(approval_id)
        return req is not None and req.status == "approved"
