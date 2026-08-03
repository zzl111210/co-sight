"""REST API for the NetHeal operations cockpit.

Supports two auth modes:
- dev (default): X-NetHeal-Actor / X-NetHeal-Role headers (backward-compatible)
- production: Bearer JWT tokens validated by TokenService
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.netheal.auth import (
    AuthContext,
    AuthRole,
    ApprovalService,
    TokenService,
    create_auth_dependency,
    dev_auth_context,
)
from app.netheal.advanced_diagnosis import (
    EvaluationChartGenerator,
    FusionDiagnosisEngine,
    GraphReasoner,
    VectorCaseRetriever,
)
from app.netheal.database import list_sites
from app.netheal.reporting import ReportSearchEngine, TrendAnalyzer
from app.netheal.streaming import sse_event_stream
from app.netheal.task_queue import get_task_queue, TaskStatus
from app.netheal.service import NetHealService


nethealRouter = APIRouter(prefix="/api/netheal/v1", tags=["NetHeal-Agent"])
_service: NetHealService | None = None
_token_service: TokenService | None = None
_approval_service: ApprovalService | None = None
_auth_dependency = create_auth_dependency()


def get_service() -> NetHealService:
    global _service
    if _service is None:
        _service = NetHealService(workspace_path="work_space")
    return _service


def get_token_service() -> TokenService:
    global _token_service
    if _token_service is None:
        _token_service = TokenService()
    return _token_service


def get_approval_service() -> ApprovalService:
    global _approval_service
    if _approval_service is None:
        _approval_service = ApprovalService()
    return _approval_service


class DiagnoseRequest(BaseModel):
    scenario_id: str = Field(default="upf-overload")
    incident_id: Optional[str] = None


class ApprovalRequest(BaseModel):
    comment: str = Field(default="", max_length=500)


class DemoRequest(BaseModel):
    scenario_id: str = Field(default="upf-overload")


class LoginRequest(BaseModel):
    actor: str = Field(min_length=1, max_length=100)
    role: str = Field(default="viewer")
    tenant_id: str = Field(default="default")


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    actor: str
    role: str


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
    """Run a full closed-loop demo for the given scenario.

    Set async_mode=true to submit as a background task and return a task_id
    for polling via /tasks/{task_id}/progress.
    """
    actor, role = _identity(x_netheal_actor, x_netheal_role)

    if async_mode:
        queue = get_task_queue()
        idempotency_key = f"demo-run-{request.scenario_id}-{actor}"

        def _run():
            svc = get_service()
            return svc.run_demo(request.scenario_id, actor, role)

        task_id = queue.submit(
            fn=_run,
            idempotency_key=idempotency_key,
            max_retries=2,
        )
        return {
            "task_id": task_id,
            "status": "pending",
            "message": "Demo submitted as background task. Poll /tasks/{task_id}/progress for updates.",
        }

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


@nethealRouter.get("/incidents/{incident_id}/report")
def download_report(
    incident_id: str,
    format: str = Query(default="html", pattern="^(html|md|both)$"),
):
    """Download the incident closure report as HTML, Markdown, or a ZIP of both."""
    return _handle(lambda: _serve_report(incident_id, format))


def _serve_report(incident_id: str, format: str):
    incident = get_service().detail(incident_id)
    report = incident.get("incident", {}).get("repair", {}).get("report")
    if not report:
        raise HTTPException(status_code=404, detail="该事件尚未生成闭环报告，请先完成诊断→审批→执行→验证全流程。")

    markdown_path = report.get("markdown_path")
    html_path = report.get("html_path")

    if format == "md":
        if not markdown_path or not Path(markdown_path).is_file():
            raise HTTPException(status_code=404, detail="Markdown 报告文件不存在")
        return FileResponse(
            markdown_path,
            media_type="text/markdown; charset=utf-8",
            filename=os.path.basename(markdown_path),
        )

    if format == "html":
        if not html_path or not Path(html_path).is_file():
            raise HTTPException(status_code=404, detail="HTML 报告文件不存在")
        return FileResponse(
            html_path,
            media_type="text/html; charset=utf-8",
            filename=os.path.basename(html_path),
        )

    # format == "both": return JSON with both paths for frontend to handle
    return {
        "markdown_path": markdown_path,
        "html_path": html_path,
        "markdown_exists": bool(markdown_path and Path(markdown_path).is_file()),
        "html_exists": bool(html_path and Path(html_path).is_file()),
    }


@nethealRouter.get("/incidents/{incident_id}/report/download/{file_type}")
def download_report_file(
    incident_id: str,
    file_type: str,
):
    """Direct file download: /report/download/html or /report/download/md"""
    if file_type not in ("html", "md"):
        raise HTTPException(status_code=400, detail="file_type must be 'html' or 'md'")
    return _handle(lambda: _serve_report(incident_id, file_type))


# ---------------------------------------------------------------------------
# Auth endpoints (P1-2: JWT authentication)
# ---------------------------------------------------------------------------


@nethealRouter.post("/auth/login", response_model=LoginResponse)
def login(request: LoginRequest):
    """Issue a JWT token for the given actor and role.

    In dev mode, this endpoint issues a self-signed token.
    In production, redirect to your OIDC provider.
    """
    tsvc = get_token_service()
    try:
        role = AuthRole(request.role)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid role: {request.role}")

    token = tsvc.issue_token(request.actor, role, request.tenant_id)
    return LoginResponse(
        access_token=token,
        token_type="bearer",
        expires_in=tsvc.default_ttl_seconds,
        actor=request.actor,
        role=role.value,
    )


@nethealRouter.post("/auth/refresh")
def refresh_token(
    authorization: str | None = Header(default=None),
):
    """Refresh an existing JWT token."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Bearer token required")
    token = authorization.removeprefix("Bearer ").strip()
    tsvc = get_token_service()
    new_token = tsvc.refresh_token(token)
    if new_token is None:
        raise HTTPException(status_code=401, detail="Invalid or expired token, please re-login")
    return {"access_token": new_token, "token_type": "bearer"}


@nethealRouter.get("/auth/me")
def whoami(
    ctx: AuthContext = Depends(_auth_dependency),
):
    """Return the current authenticated user context."""
    return {
        "actor": ctx.actor,
        "role": ctx.role.value,
        "tenant_id": ctx.tenant_id,
        "expired": ctx.is_expired(),
    }


# ---------------------------------------------------------------------------
# Approval workflow endpoints (P1-2: structured approval)
# ---------------------------------------------------------------------------


@nethealRouter.post("/approvals")
def create_approval(
    incident_id: str = Query(...),
    risk_level: str = Query(default="medium"),
    change_summary: str = Query(default=""),
    x_netheal_actor: str | None = Header(default=None),
    x_netheal_role: str | None = Header(default=None),
):
    """Create a formal approval request for a change."""
    actor, _role = _identity(x_netheal_actor, x_netheal_role)
    svc = get_approval_service()
    incident = get_service().detail(incident_id)
    repair = incident.get("incident", {}).get("repair", {})
    commands = repair.get("commands", {}).get("commands", [])
    rollback = repair.get("plan", {}).get("rollback", "manual rollback")

    req = svc.create_approval(
        incident_id=incident_id,
        requester=actor,
        risk_level=risk_level,
        change_summary=change_summary or f"NetHeal-Agent recommended repair for {incident_id}",
        commands=commands if isinstance(commands, list) else [str(commands)],
        rollback_plan=str(rollback),
    )
    return {
        "approval_id": req.id,
        "incident_id": req.incident_id,
        "status": req.status,
        "risk_level": req.risk_level,
    }


@nethealRouter.post("/approvals/{approval_id}/approve")
def approve_change(
    approval_id: str,
    comment: str = Query(default=""),
    x_netheal_actor: str | None = Header(default=None),
    x_netheal_role: str | None = Header(default=None),
):
    """Approve a pending change approval."""
    actor, _role = _identity(x_netheal_actor, x_netheal_role)
    svc = get_approval_service()
    try:
        req = svc.approve(approval_id, actor, comment)
        return {"approval_id": req.id, "status": req.status, "approved_by": req.approved_by}
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@nethealRouter.post("/approvals/{approval_id}/reject")
def reject_change(
    approval_id: str,
    reason: str = Query(default=""),
    x_netheal_actor: str | None = Header(default=None),
    x_netheal_role: str | None = Header(default=None),
):
    """Reject a pending change approval."""
    actor, _role = _identity(x_netheal_actor, x_netheal_role)
    svc = get_approval_service()
    try:
        req = svc.reject(approval_id, actor, reason)
        return {"approval_id": req.id, "status": req.status, "rejected_by": req.approved_by}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@nethealRouter.get("/approvals")
def list_approvals():
    """List all pending approvals."""
    svc = get_approval_service()
    return {"items": [{"id": r.id, "incident_id": r.incident_id, "risk_level": r.risk_level, "status": r.status} for r in svc.list_pending()]}


# ---------------------------------------------------------------------------
# Task queue endpoints (P1-3: background tasks)
# ---------------------------------------------------------------------------


@nethealRouter.get("/tasks/{task_id}/progress")
def task_progress(task_id: str):
    """Get the current progress of a background task."""
    queue = get_task_queue()
    progress = queue.get_progress(task_id)
    result = queue.get_result(task_id)
    if progress is None and result is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    return {
        "task_id": task_id,
        "status": result.status.value if result else "unknown",
        "progress": {
            "stage": progress.stage if progress else 0,
            "total_stages": progress.total_stages if progress else 6,
            "stage_label": progress.stage_label if progress else "",
            "message": progress.message if progress else "",
            "percent": progress.percent if progress else 0.0,
        },
        "error": result.error if result and result.error else "",
        "attempts": result.attempts if result else 0,
    }


@nethealRouter.get("/tasks/{task_id}/result")
def task_result(task_id: str):
    """Get the final result of a background task (blocks until complete)."""
    queue = get_task_queue()
    result = queue.get_result(task_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    if result.status == TaskStatus.PENDING:
        return {"task_id": task_id, "status": "pending", "message": "Task has not started yet"}
    if result.status == TaskStatus.RUNNING:
        return {"task_id": task_id, "status": "running", "message": "Task is still running"}
    if result.status == TaskStatus.CANCELLED:
        return {"task_id": task_id, "status": "cancelled"}
    if result.status == TaskStatus.FAILED:
        return {"task_id": task_id, "status": "failed", "error": result.error}
    return {"task_id": task_id, "status": "completed", "result": result.result}


@nethealRouter.post("/tasks/{task_id}/cancel")
def cancel_task(task_id: str):
    """Cancel a running background task."""
    queue = get_task_queue()
    if queue.cancel(task_id):
        return {"task_id": task_id, "status": "cancelled"}
    raise HTTPException(status_code=409, detail=f"Task cannot be cancelled: {task_id}")


@nethealRouter.get("/tasks")
def list_tasks():
    """List all background tasks."""
    queue = get_task_queue()
    return {"items": queue.list_tasks()}


# ---------------------------------------------------------------------------
# Multi-tenant site management (P1-4)
# ---------------------------------------------------------------------------


@nethealRouter.get("/sites")
def sites_list():
    """List all configured network sites (multi-tenant)."""
    return {"items": list_sites()}


@nethealRouter.get("/db/health")
def database_health():
    """Check database connectivity and migration status."""
    svc = get_service()
    store_health = svc.store.health()
    return {
        "ok": store_health["ok"],
        "engine": "sqlite",
        "journal_mode": "WAL",
        "migration_version": store_health.get("version", 1),
    }


# ---------------------------------------------------------------------------
# SSE streaming endpoint (P1-5: real-time push)
# ---------------------------------------------------------------------------


@nethealRouter.get("/stream")
async def event_stream(incident_id: str | None = None):
    """Server-Sent Events endpoint for real-time agent/tool streaming.

    Client usage:
        const source = new EventSource('/api/netheal/v1/stream?incident_id=NH-xxx');
        source.addEventListener('agent_started', (e) => console.log(JSON.parse(e.data)));
        source.addEventListener('status_changed', (e) => updateUI(JSON.parse(e.data)));
    """
    from fastapi.responses import StreamingResponse

    return StreamingResponse(
        sse_event_stream(incident_id=incident_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


# ---------------------------------------------------------------------------
# Report search & trends endpoints (P1-6)
# ---------------------------------------------------------------------------

_search_engine: ReportSearchEngine | None = None
_trend_analyzer: TrendAnalyzer | None = None


def get_search_engine() -> ReportSearchEngine:
    global _search_engine
    if _search_engine is None:
        _search_engine = ReportSearchEngine()
        # Index existing incidents
        svc = get_service()
        for inc in svc.incidents():
            _search_engine.index_incident(inc)
    return _search_engine


def get_trend_analyzer() -> TrendAnalyzer:
    global _trend_analyzer
    if _trend_analyzer is None:
        _trend_analyzer = TrendAnalyzer(store=get_service().store)
    return _trend_analyzer


@nethealRouter.get("/reports/search")
def search_reports(
    q: str = Query(min_length=1),
    status: str | None = None,
    scenario_id: str | None = None,
    limit: int = Query(default=10, ge=1, le=50),
):
    """Full-text search across closed incident reports."""
    engine = get_search_engine()
    results = engine.search(q, max_results=limit, filter_status=status, filter_scenario=scenario_id)
    return {
        "query": q,
        "total": len(results),
        "items": [
            {
                "incident_id": r.incident_id,
                "scenario_id": r.scenario_id,
                "title": r.title,
                "root_cause": r.root_cause,
                "status": r.status,
                "closed_at": r.closed_at,
                "snippet": r.snippet,
                "score": r.score,
                "kpi_summary": r.kpi_summary,
            }
            for r in results
        ],
    }


@nethealRouter.get("/reports/trends")
def report_trends(
    scenario_id: str | None = None,
    metric: str | None = None,
):
    """Get historical KPI trend data across closed incidents."""
    analyzer = get_trend_analyzer()
    points = analyzer.compute_trends(scenario_id=scenario_id, metric=metric)
    summary = analyzer.summary(scenario_id=scenario_id)
    return {
        "summary": summary,
        "points": [
            {
                "timestamp": p.timestamp,
                "incident_id": p.incident_id,
                "scenario_id": p.scenario_id,
                "metric": p.metric,
                "value_before": p.value_before,
                "value_after": p.value_after,
                "recovery_passed": p.recovery_passed,
            }
            for p in points
        ],
    }


# ---------------------------------------------------------------------------
# P2: Advanced diagnosis endpoints
# ---------------------------------------------------------------------------

_vector_retriever: VectorCaseRetriever | None = None
_graph_reasoner: GraphReasoner | None = None
_fusion_engine: FusionDiagnosisEngine | None = None
_chart_generator: EvaluationChartGenerator | None = None


def get_vector_retriever() -> VectorCaseRetriever:
    global _vector_retriever
    if _vector_retriever is None:
        from pathlib import Path
        kb_path = Path(__file__).resolve().parents[3] / "app" / "netheal" / "data" / "knowledge_base.json"
        _vector_retriever = VectorCaseRetriever(kb_path)
    return _vector_retriever


def get_graph_reasoner() -> GraphReasoner:
    global _graph_reasoner
    if _graph_reasoner is None:
        topo = get_service().topology()
        _graph_reasoner = GraphReasoner(topo)
    return _graph_reasoner


def get_fusion_engine() -> FusionDiagnosisEngine:
    global _fusion_engine
    if _fusion_engine is None:
        _fusion_engine = FusionDiagnosisEngine(graph_reasoner=get_graph_reasoner())
    return _fusion_engine


def get_chart_generator() -> EvaluationChartGenerator:
    global _chart_generator
    if _chart_generator is None:
        _chart_generator = EvaluationChartGenerator()
    return _chart_generator


@nethealRouter.get("/diagnosis/vector-search")
def vector_search_cases(
    q: str = Query(min_length=2, description="Search query for historical cases"),
    top_k: int = Query(default=5, ge=1, le=20),
):
    """P2-3: Vector-based historical case retrieval."""
    retriever = get_vector_retriever()
    results = retriever.search(q, top_k=top_k)
    return {
        "query": q,
        "total": len(results),
        "items": [
            {
                "case_id": r.case_id,
                "summary": r.summary,
                "root_cause": r.root_cause,
                "resolution": r.resolution,
                "recovery_minutes": r.recovery_minutes,
                "score": r.score,
                "matched_terms": r.matched_terms,
            }
            for r in results
        ],
    }


@nethealRouter.get("/diagnosis/graph-reasoning")
def graph_reasoning(
    scenario_id: str = "upf-overload",
):
    """P2-4: Graph-based propagation analysis for root cause identification."""
    reasoner = get_graph_reasoner()
    svc = get_service()
    scenario = svc._scenario(scenario_id)
    alarms = svc._decode(svc.toolkit.read_alarm_events(scenario["site_id"], scenario_id))
    alarm_resources = list({e.get("resource_id", "") for e in alarms.get("correlated_events", []) if e.get("resource_id")})
    if not alarm_resources:
        alarm_resources = [scenario.get("root_resource", "UPF-01")]

    candidates = reasoner.identify_root_candidates(alarm_resources)
    scores = reasoner.propagation_score(alarm_resources)
    return {
        "scenario_id": scenario_id,
        "alarm_resources": alarm_resources,
        "root_candidates": candidates,
        "propagation_scores": scores,
    }


@nethealRouter.get("/diagnosis/fusion")
def fusion_diagnosis(
    scenario_id: str = "upf-overload",
    site_id: str = "campus-5g",
):
    """P2-4: Rule + graph + LLM fusion diagnosis."""
    svc = get_service()
    engine = get_fusion_engine()
    diagnosis = svc._decode(svc.toolkit.diagnose_root_cause(site_id, scenario_id))
    alarms = svc._decode(svc.toolkit.read_alarm_events(site_id, scenario_id))
    alarm_resources = list({e.get("resource_id", "") for e in alarms.get("correlated_events", []) if e.get("resource_id")})

    result = engine.fuse(diagnosis, alarm_resources)
    return {
        "scenario_id": scenario_id,
        "primary_root_cause": result.primary_root_cause,
        "primary_title": result.primary_title,
        "primary_resource": result.primary_resource,
        "confidence": result.confidence,
        "rule_confidence": result.rule_confidence,
        "graph_confidence": result.graph_confidence,
        "llm_confidence": result.llm_confidence,
        "fusion_method": result.fusion_method,
        "review_required": result.review_required,
        "review_reason": result.review_reason,
        "candidates": [
            {
                "root_cause": c.get("root_cause", ""),
                "title": c.get("title", ""),
                "confidence": c.get("confidence", 0),
                "evidence_coverage": c.get("evidence_coverage", 0),
            }
            for c in result.candidates[:3]
        ],
    }


@nethealRouter.get("/evaluation/charts")
def evaluation_charts():
    """P2-5: Generate evaluation chart data for competition presentations."""
    import json
    from pathlib import Path

    gen = get_chart_generator()
    report_path = Path("work_space/netheal_acceptance/acceptance_report.json")
    if report_path.is_file():
        report = json.loads(report_path.read_text(encoding="utf-8"))
    else:
        report = {"results": [], "summary": {"total": 0, "passed": 0}}

    charts = gen.generate(report)
    return charts


@nethealRouter.get("/diagnosis/explain/{incident_id}")
def explain_diagnosis(incident_id: str):
    """P2-4: Get human-readable explanation of the diagnosis reasoning chain."""
    svc = get_service()
    detail = svc.detail(incident_id)
    incident = detail.get("incident", {})
    evidence = incident.get("evidence", {})

    reasoning_hops = []
    if evidence.get("alarm_summary"):
        a = evidence["alarm_summary"]
        reasoning_hops.append(f"告警解析：收到 {a.get('raw', 0)} 条原始告警，关联压缩后 {a.get('correlated', 0)} 条，压缩率 {a.get('compression_rate_pct', 0):.1f}%")
    if evidence.get("kpi_violations"):
        reasoning_hops.append(f"KPI 检测：发现 {len(evidence['kpi_violations'])} 项指标异常")
    if evidence.get("knowledge_matches"):
        reasoning_hops.append(f"知识匹配：命中 {len(evidence['knowledge_matches'])} 条专家规则")
    if incident.get("root_cause"):
        reasoning_hops.append(f"根因定位：{incident['root_cause']}（置信度 {float(incident.get('confidence', 0)) * 100:.0f}%）")

    return {
        "incident_id": incident_id,
        "title": incident.get("title", ""),
        "root_cause": incident.get("root_cause", ""),
        "confidence": incident.get("confidence", 0),
        "reasoning_hops": reasoning_hops,
        "graph_analysis": get_graph_reasoner().identify_root_candidates(
            list(evidence.get("downstream_impact", [incident.get("root_resource", "")]))
        ),
    }


# ---------------------------------------------------------------------------
# API Key configuration endpoints
# ---------------------------------------------------------------------------

import re as _re
from pathlib import Path as _Path
from dotenv import load_dotenv as _load_dotenv, set_key as _set_key


def _get_env_path() -> _Path:
    """Find the .env file in the repository root."""
    # Try current working directory first, then walk up
    candidates = [
        _Path.cwd() / ".env",
        _Path(__file__).resolve().parents[3] / ".env",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return _Path.cwd() / ".env"


def _reload_env() -> None:
    """Reload .env into os.environ."""
    env_path = _get_env_path()
    if env_path.is_file():
        _load_dotenv(env_path, override=True)
        logger.info(f"已重新加载环境变量: {env_path}")


@nethealRouter.get("/config/api")
def get_api_config():
    """Get current API configuration (masked)."""
    env_path = _get_env_path()
    return {
        "env_path": str(env_path),
        "config": {
            "API_KEY": _mask(os.environ.get("API_KEY", "")),
            "API_BASE_URL": os.environ.get("API_BASE_URL", ""),
            "MODEL_NAME": os.environ.get("MODEL_NAME", ""),
            "MAX_TOKENS": os.environ.get("MAX_TOKENS", "4096"),
            "TEMPERATURE": os.environ.get("TEMPERATURE", "0.0"),
            "PROXY": os.environ.get("PROXY", ""),
            "TAVILY_API_KEY": _mask(os.environ.get("TAVILY_API_KEY", "")),
            "GOOGLE_API_KEY": _mask(os.environ.get("GOOGLE_API_KEY", "")),
            "SEARCH_ENGINE_ID": os.environ.get("SEARCH_ENGINE_ID", ""),
            "LLM_TIMEOUT": os.environ.get("LLM_TIMEOUT", "60"),
            "TURBO_MODE": os.environ.get("TURBO_MODE", "False"),
        },
        "is_placeholder": "如：" in (os.environ.get("API_KEY", "") or ""),
    }


@nethealRouter.post("/config/api")
def save_api_config(data: dict):
    """Save API configuration to .env file and reload."""
    env_path = _get_env_path()
    if not env_path.is_file():
        raise HTTPException(status_code=500, detail=".env 文件未找到")

    # Whitelist allowed keys
    allowed = {
        "API_KEY", "API_BASE_URL", "MODEL_NAME", "MAX_TOKENS", "TEMPERATURE",
        "PROXY", "TAVILY_API_KEY", "GOOGLE_API_KEY", "SEARCH_ENGINE_ID",
        "LLM_TIMEOUT", "TURBO_MODE",
    }
    updated = []
    for key, value in data.items():
        if key not in allowed:
            continue
        # Don't overwrite with masked value
        if "****" in str(value) and os.environ.get(key, ""):
            continue
        os.environ[key] = str(value)
        _set_key(env_path, key, str(value))
        updated.append(key)

    _reload_env()
    logger.info(f"API 配置已更新: {', '.join(updated)}")
    return {"ok": True, "updated": updated, "message": f"已更新 {len(updated)} 项配置，重启服务后生效。"}


def _mask(value: str) -> str:
    if not value or len(value) < 8:
        return value or ""
    return value[:4] + "****" + value[-4:]
