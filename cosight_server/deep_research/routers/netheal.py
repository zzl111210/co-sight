"""REST API for the NetHeal operations cockpit."""

from __future__ import annotations

from typing import Optional
from pathlib import Path
import uuid

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.netheal.insights import NetHealInsights
from app.netheal.reporting import ReportAccessManager
from app.netheal.service import NetHealService
from app.netheal.streaming import (
    StreamEventType,
    publish_agent_event,
    sse_event_stream,
)
from app.netheal.task_queue import TaskStatus, get_task_queue


_insights: NetHealInsights | None = None
nethealRouter = APIRouter(prefix="/api/netheal/v1", tags=["NetHeal-Agent"])
_service: NetHealService | None = None


def get_service() -> NetHealService:
    global _service
    if _service is None:
        _service = NetHealService(workspace_path="work_space")
    return _service


def get_insights() -> NetHealInsights:
    global _insights
    service = get_service()
    if _insights is None or _insights.service is not service:
        _insights = NetHealInsights(service)
    return _insights


class DiagnoseRequest(BaseModel):
    scenario_id: str = Field(default="upf-overload")
    incident_id: Optional[str] = None


class ApprovalRequest(BaseModel):
    comment: str = Field(default="", max_length=500)


class DemoRequest(BaseModel):
    scenario_id: str = Field(default="upf-overload")
    idempotency_key: Optional[str] = Field(default=None, max_length=100)


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
    async_mode: bool = Query(default=False),
):
    actor, role = _identity(x_netheal_actor, x_netheal_role)
    if async_mode:
        service = get_service()
        queue = get_task_queue()
        idempotency_key = request.idempotency_key or (
            f"demo-{request.scenario_id}-{actor}-{uuid.uuid4().hex}"
        )

        def run_task(task_id: str):
            def update_progress(
                stage: int,
                total_stages: int,
                label: str,
                message: str,
            ) -> None:
                queue.update_progress(
                    task_id,
                    stage,
                    total_stages,
                    label,
                    message,
                )
                publish_agent_event(
                    agent_name=label,
                    event_type=(
                        StreamEventType.AGENT_COMPLETED
                        if stage == total_stages - 1
                        else StreamEventType.AGENT_STARTED
                    ),
                    message=message,
                    detail={"task_id": task_id, "stage": stage},
                )

            return service.run_demo(
                request.scenario_id,
                actor,
                role,
                progress_callback=update_progress,
            )

        task_id = queue.submit(
            run_task,
            idempotency_key=idempotency_key,
            max_retries=0,
            inject_task_id=True,
        )
        return {"task_id": task_id, "status": "pending", "async_mode": True}
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
@nethealRouter.get("/incidents/{incident_id}/report")
def report_metadata(incident_id: str):
    detail = _handle(lambda: get_service().detail(incident_id))
    report = detail["incident"].get("repair", {}).get("report", {})
    return {
        "incident_id": incident_id,
        "available": {
            "markdown": bool(report.get("markdown_path")),
            "html": bool(report.get("html_path")),
        },
        "downloads": {
            "markdown": (
                f"/api/netheal/v1/incidents/{incident_id}/report/download/md"
            ),
            "html": (
                f"/api/netheal/v1/incidents/{incident_id}/report/download/html"
            ),
        },
    }


@nethealRouter.get("/incidents/{incident_id}/report/download/{file_type}")
def download_report(
    incident_id: str,
    file_type: str,
    x_netheal_actor: str | None = Header(default=None),
    x_netheal_role: str | None = Header(default=None),
):
    if file_type not in {"md", "html"}:
        raise HTTPException(status_code=400, detail="file_type must be md or html")
    actor, role = _identity(x_netheal_actor, x_netheal_role)
    if not ReportAccessManager.can_access(role, incident_id, get_service().store):
        raise HTTPException(status_code=403, detail="report access denied")

    detail = _handle(lambda: get_service().detail(incident_id))
    report = detail["incident"].get("repair", {}).get("report", {})
    key = "markdown_path" if file_type == "md" else "html_path"
    raw_path = report.get(key)
    if not raw_path:
        raise HTTPException(status_code=404, detail="report is not available")
    report_path = Path(raw_path).resolve()
    try:
        report_path.relative_to(get_service().workspace_path)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="invalid report path") from exc
    if not report_path.is_file():
        raise HTTPException(status_code=404, detail="report file does not exist")

    ReportAccessManager.log_access(
        incident_id,
        actor,
        role,
        file_type,
        get_service().store,
    )
    media_type = (
        "text/markdown; charset=utf-8"
        if file_type == "md"
        else "text/html; charset=utf-8"
    )
    return FileResponse(
        report_path,
        media_type=media_type,
        filename=f"NetHeal_{incident_id}.{file_type}",
    )


@nethealRouter.get("/tasks/{task_id}/progress")
def task_progress(task_id: str):
    queue = get_task_queue()
    progress = queue.get_progress(task_id)
    result = queue.get_result(task_id, wait=False)
    if progress is None or result is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    return {
        "task_id": task_id,
        "status": result.status.value,
        "progress": {
            "stage": progress.stage,
            "total_stages": progress.total_stages,
            "stage_label": progress.stage_label,
            "message": progress.message,
            "percent": round(progress.percent, 1),
        },
        "attempts": result.attempts,
        "error": result.error,
    }


@nethealRouter.get("/tasks/{task_id}/result")
def task_result(task_id: str):
    result = get_task_queue().get_result(task_id, wait=False)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    payload = {"task_id": task_id, "status": result.status.value}
    if result.status == TaskStatus.COMPLETED:
        payload["result"] = result.result
    elif result.status == TaskStatus.FAILED:
        payload["error"] = result.error
    return payload


@nethealRouter.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: str):
    if get_task_queue().cancel(task_id):
        return {"task_id": task_id, "status": "cancelled"}
    raise HTTPException(status_code=409, detail="task cannot be cancelled")


@nethealRouter.get("/tasks")
def list_tasks():
    return {"items": get_task_queue().list_tasks()}


@nethealRouter.get("/stream")
async def event_stream(incident_id: str | None = None):
    return StreamingResponse(
        sse_event_stream(incident_id=incident_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@nethealRouter.get("/reports/search")
def search_reports(
    q: str = Query(min_length=1),
    status: str | None = None,
    scenario_id: str | None = None,
    limit: int = Query(default=10, ge=1, le=50),
):
    return get_insights().search_reports(q, limit, status, scenario_id)


@nethealRouter.get("/reports/trends")
def report_trends(
    scenario_id: str | None = None,
    metric: str | None = None,
):
    return get_insights().trends(scenario_id, metric)


@nethealRouter.get("/diagnosis/vector-search")
def vector_search(
    q: str = Query(min_length=2),
    top_k: int = Query(default=5, ge=1, le=20),
):
    return get_insights().vector_search(q, top_k)


@nethealRouter.get("/diagnosis/graph-reasoning")
def graph_reasoning(scenario_id: str = "upf-overload"):
    return _handle(lambda: get_insights().graph_reasoning(scenario_id))


@nethealRouter.get("/diagnosis/fusion")
def fusion_diagnosis(scenario_id: str = "upf-overload"):
    return _handle(lambda: get_insights().fusion_diagnosis(scenario_id))


@nethealRouter.get("/diagnosis/explain/{incident_id}")
def explain_diagnosis(incident_id: str):
    return _handle(lambda: get_insights().explain(incident_id))


@nethealRouter.get("/evaluation/charts")
def evaluation_charts():
    return get_insights().evaluation_charts()
    return get_service().workflow()


@nethealRouter.get("/audit")
def audit(limit: int = Query(default=50, ge=1, le=200)):
    return {"items": get_service().audit(limit)}
