"""REST API for the NetHeal operations cockpit."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.netheal.service import NetHealService


nethealRouter = APIRouter(prefix="/api/netheal/v1", tags=["NetHeal-Agent"])
_service: NetHealService | None = None


def get_service() -> NetHealService:
    global _service
    if _service is None:
        _service = NetHealService(workspace_path="work_space")
    return _service


class DiagnoseRequest(BaseModel):
    scenario_id: str = Field(default="upf-overload")
    incident_id: Optional[str] = None


class ApprovalRequest(BaseModel):
    comment: str = Field(default="", max_length=500)


class DemoRequest(BaseModel):
    scenario_id: str = Field(default="upf-overload")


def _identity(
    actor: str | None,
    role: str | None,
) -> tuple[str, str]:
    return actor or "cockpit-user", role or "viewer"


def _handle(operation):
    try:
        return operation()
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@nethealRouter.get("/health")
def health():
    return get_service().health()


@nethealRouter.get("/scenarios")
def scenarios():
    return {"items": get_service().scenarios()}


@nethealRouter.get("/overview")
def overview():
    return get_service().overview()


@nethealRouter.get("/incidents")
def incidents(limit: int = Query(default=50, ge=1, le=200)):
    return {"items": get_service().incidents(limit)}


@nethealRouter.get("/incidents/{incident_id}")
def incident_detail(incident_id: str):
    return _handle(lambda: get_service().detail(incident_id))


@nethealRouter.post("/incidents/diagnose")
def diagnose(
    request: DiagnoseRequest,
    x_netheal_actor: str | None = Header(default=None),
    x_netheal_role: str | None = Header(default=None),
):
    actor, role = _identity(x_netheal_actor, x_netheal_role)
    return _handle(
        lambda: get_service().diagnose(
            request.scenario_id,
            request.incident_id,
            actor,
            role,
        )
    )


@nethealRouter.post("/incidents/{incident_id}/approve")
def approve(
    incident_id: str,
    request: ApprovalRequest,
    x_netheal_actor: str | None = Header(default=None),
    x_netheal_role: str | None = Header(default=None),
):
    actor, role = _identity(x_netheal_actor, x_netheal_role)
    return _handle(
        lambda: get_service().approve(
            incident_id,
            actor,
            role,
            request.comment,
        )
    )


@nethealRouter.post("/incidents/{incident_id}/execute")
def execute(
    incident_id: str,
    x_netheal_actor: str | None = Header(default=None),
    x_netheal_role: str | None = Header(default=None),
):
    actor, role = _identity(x_netheal_actor, x_netheal_role)
    return _handle(lambda: get_service().execute(incident_id, actor, role))


@nethealRouter.post("/incidents/{incident_id}/verify")
def verify(
    incident_id: str,
    x_netheal_actor: str | None = Header(default=None),
    x_netheal_role: str | None = Header(default=None),
):
    actor, role = _identity(x_netheal_actor, x_netheal_role)
    return _handle(lambda: get_service().verify(incident_id, actor, role))


@nethealRouter.post("/demo/run")
def run_demo(
    request: DemoRequest,
    x_netheal_actor: str | None = Header(default=None),
    x_netheal_role: str | None = Header(default=None),
):
    actor, role = _identity(x_netheal_actor, x_netheal_role)
    return _handle(lambda: get_service().run_demo(request.scenario_id, actor, role))


@nethealRouter.post("/demo/reset")
def reset_demo(
    x_netheal_actor: str | None = Header(default=None),
    x_netheal_role: str | None = Header(default=None),
):
    actor, role = _identity(x_netheal_actor, x_netheal_role)
    return _handle(lambda: get_service().reset_demo(actor, role))


@nethealRouter.get("/topology")
def topology(incident_id: str | None = None):
    return get_service().topology(incident_id)


@nethealRouter.get("/metrics")
def metrics(scenario_id: str = "upf-overload"):
    return get_service().metrics(scenario_id)


@nethealRouter.get("/workflow")
def workflow():
    return get_service().workflow()


@nethealRouter.get("/audit")
def audit(limit: int = Query(default=50, ge=1, le=200)):
    return {"items": get_service().audit(limit)}
