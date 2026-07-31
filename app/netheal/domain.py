"""Domain types and lifecycle rules for production-style NetHeal incidents."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class IncidentStatus(str, Enum):
    DETECTED = "detected"
    DIAGNOSING = "diagnosing"
    APPROVAL_PENDING = "approval_pending"
    APPROVED = "approved"
    EXECUTING = "executing"
    VERIFYING = "verifying"
    CLOSED = "closed"
    NEEDS_REVIEW = "needs_review"


class UserRole(str, Enum):
    VIEWER = "viewer"
    OPERATOR = "operator"
    APPROVER = "approver"
    ADMIN = "admin"


ALLOWED_TRANSITIONS: dict[IncidentStatus, set[IncidentStatus]] = {
    IncidentStatus.DETECTED: {IncidentStatus.DIAGNOSING},
    IncidentStatus.DIAGNOSING: {
        IncidentStatus.APPROVAL_PENDING,
        IncidentStatus.NEEDS_REVIEW,
    },
    IncidentStatus.APPROVAL_PENDING: {
        IncidentStatus.APPROVED,
        IncidentStatus.NEEDS_REVIEW,
    },
    IncidentStatus.APPROVED: {IncidentStatus.EXECUTING},
    IncidentStatus.EXECUTING: {
        IncidentStatus.VERIFYING,
        IncidentStatus.NEEDS_REVIEW,
    },
    IncidentStatus.VERIFYING: {
        IncidentStatus.CLOSED,
        IncidentStatus.NEEDS_REVIEW,
    },
    IncidentStatus.NEEDS_REVIEW: {
        IncidentStatus.DIAGNOSING,
        IncidentStatus.APPROVAL_PENDING,
    },
    IncidentStatus.CLOSED: set(),
}


ROLE_PERMISSIONS: dict[UserRole, set[str]] = {
    UserRole.VIEWER: {"read"},
    UserRole.OPERATOR: {"read", "diagnose", "execute", "verify"},
    UserRole.APPROVER: {"read", "diagnose", "approve", "execute", "verify"},
    UserRole.ADMIN: {"read", "diagnose", "approve", "execute", "verify", "reset"},
}


def ensure_transition(current: str, target: str) -> None:
    current_status = IncidentStatus(current)
    target_status = IncidentStatus(target)
    if target_status not in ALLOWED_TRANSITIONS[current_status]:
        raise ValueError(f"Invalid incident transition: {current_status.value} -> {target_status.value}")


def ensure_permission(role: str, action: str) -> None:
    try:
        user_role = UserRole(role)
    except ValueError as exc:
        raise PermissionError(f"Unknown role: {role}") from exc
    if action not in ROLE_PERMISSIONS[user_role]:
        raise PermissionError(f"Role '{role}' cannot perform '{action}'")


@dataclass
class Incident:
    id: str
    site_id: str
    scenario_id: str
    title: str
    severity: str
    status: str = IncidentStatus.DETECTED.value
    root_cause: str | None = None
    root_resource: str | None = None
    confidence: float | None = None
    affected_service: str | None = None
    risk_level: str | None = None
    verification_passed: bool | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    repair: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
