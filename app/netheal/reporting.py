"""Report management: authenticated download, full-text search, and historical comparison.

Builds on P0-1 (basic download) to add:
- Authenticated download with role-based access
- Full-text search across incident reports
- Historical KPI trend comparison across multiple closures

See: CODEX_HANDOFF.md §19.2 (P1-6)
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.common.logger_util import logger


# ---------------------------------------------------------------------------
# Report search engine
# ---------------------------------------------------------------------------


@dataclass
class ReportSearchResult:
    """A single match from a report search query."""

    incident_id: str
    scenario_id: str
    title: str
    root_cause: str
    status: str
    closed_at: str
    report_path: str
    snippet: str = ""
    score: float = 0.0
    kpi_summary: dict[str, Any] = field(default_factory=dict)


class ReportSearchEngine:
    """Simple in-memory full-text search over incident reports.

    In production, replace with Elasticsearch or PostgreSQL full-text search.
    """

    def __init__(self, workspace_path: str | Path = "work_space") -> None:
        self.workspace_path = Path(workspace_path)
        self._index: dict[str, ReportSearchResult] = {}

    def index_incident(self, incident: dict[str, Any]) -> None:
        """Index an incident for search."""
        report = incident.get("repair", {}).get("report", {})
        markdown_path = report.get("markdown_path", "")

        if not markdown_path or not Path(markdown_path).is_file():
            return

        try:
            content = Path(markdown_path).read_text(encoding="utf-8")
        except Exception:
            return

        self._index[incident["id"]] = ReportSearchResult(
            incident_id=incident["id"],
            scenario_id=incident.get("scenario_id", ""),
            title=incident.get("title", ""),
            root_cause=incident.get("root_cause", ""),
            status=incident.get("status", ""),
            closed_at=incident.get("updated_at", ""),
            report_path=markdown_path,
            kpi_summary=self._extract_kpi_summary(incident),
        )

    def search(
        self,
        query: str,
        max_results: int = 10,
        filter_status: str | None = None,
        filter_scenario: str | None = None,
    ) -> list[ReportSearchResult]:
        """Search indexed reports by keyword query."""
        query_terms = query.lower().split()
        if not query_terms:
            return []

        scored: list[tuple[float, ReportSearchResult]] = []
        for result in self._index.values():
            if filter_status and result.status != filter_status:
                continue
            if filter_scenario and result.scenario_id != filter_scenario:
                continue

            # Read content for scoring
            try:
                content = Path(result.report_path).read_text(encoding="utf-8").lower()
            except Exception:
                continue

            score = sum(
                content.count(term) * (2.0 if term in result.title.lower() else 1.0)
                for term in query_terms
            )
            if score > 0:
                # Extract snippet
                snippet = self._extract_snippet(content, query_terms)
                result.snippet = snippet
                result.score = score
                scored.append((score, result))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in scored[:max_results]]

    @staticmethod
    def _extract_snippet(content: str, terms: list[str], context_chars: int = 100) -> str:
        """Extract a relevant snippet around the first matching term."""
        for term in terms:
            idx = content.find(term)
            if idx >= 0:
                start = max(0, idx - context_chars)
                end = min(len(content), idx + len(term) + context_chars)
                snippet = content[start:end].strip()
                if start > 0:
                    snippet = "…" + snippet
                if end < len(content):
                    snippet = snippet + "…"
                return snippet
        return content[:context_chars * 2] + "…"

    @staticmethod
    def _extract_kpi_summary(incident: dict[str, Any]) -> dict[str, Any]:
        """Extract KPI before/after summary from an incident."""
        verification = incident.get("repair", {}).get("verification", {})
        checks = verification.get("checks", [])
        if not checks:
            return {}
        return {
            "checks_count": len(checks),
            "passed_count": sum(1 for c in checks if c.get("passed", False)),
            "metrics": [
                {"metric": c.get("metric", ""), "before": c.get("before", ""), "after": c.get("after", "")}
                for c in checks[:5]
            ],
        }


# ---------------------------------------------------------------------------
# Historical trend comparison
# ---------------------------------------------------------------------------


@dataclass
class TrendPoint:
    """A single data point in a historical trend series."""

    timestamp: str
    incident_id: str
    scenario_id: str
    metric: str
    value_before: float
    value_after: float
    recovery_passed: bool


class TrendAnalyzer:
    """Analyzes historical KPI trends across multiple incident closures.

    Useful for demonstrating that NetHeal-Agent not only diagnoses and repairs
    but also tracks long-term network health improvement.
    """

    def __init__(self, store=None) -> None:
        self._store = store

    def compute_trends(
        self,
        scenario_id: str | None = None,
        metric: str | None = None,
        limit: int = 20,
    ) -> list[TrendPoint]:
        """Compute historical KPI trends from closed incidents."""
        if self._store is None:
            return []

        incidents = self._store.list_incidents(limit * 3)
        closed = [inc for inc in incidents if inc.get("status") == "closed"]
        if scenario_id:
            closed = [inc for inc in closed if inc.get("scenario_id") == scenario_id]

        points: list[TrendPoint] = []
        for inc in closed[-limit:]:
            verification = inc.get("repair", {}).get("verification", {})
            checks = verification.get("checks", [])
            for check in checks:
                check_metric = check.get("metric", "")
                if metric and check_metric != metric:
                    continue
                try:
                    points.append(
                        TrendPoint(
                            timestamp=inc.get("updated_at", ""),
                            incident_id=inc.get("id", ""),
                            scenario_id=inc.get("scenario_id", ""),
                            metric=check_metric,
                            value_before=float(check.get("before", 0)),
                            value_after=float(check.get("after", 0)),
                            recovery_passed=verification.get("passed", False),
                        )
                    )
                except (ValueError, TypeError):
                    continue

        points.sort(key=lambda p: p.timestamp)
        return points

    def summary(self, scenario_id: str | None = None) -> dict[str, Any]:
        """Generate a trend summary with statistics."""
        points = self.compute_trends(scenario_id=scenario_id)

        if not points:
            return {"total_points": 0, "metrics": {}, "recovery_rate": 0.0}

        metrics: dict[str, list[TrendPoint]] = {}
        for p in points:
            metrics.setdefault(p.metric, []).append(p)

        recovery_rate = sum(1 for p in points if p.recovery_passed) / len(points) * 100

        metric_summaries = {}
        for metric_name, metric_points in metrics.items():
            improvements = [
                abs(p.value_after - p.value_before) for p in metric_points
                if p.recovery_passed
            ]
            metric_summaries[metric_name] = {
                "count": len(metric_points),
                "mean_improvement": sum(improvements) / len(improvements) if improvements else 0,
                "latest_before": metric_points[-1].value_before,
                "latest_after": metric_points[-1].value_after,
            }

        return {
            "total_points": len(points),
            "metrics": metric_summaries,
            "recovery_rate_pct": round(recovery_rate, 1),
            "scenario_filter": scenario_id or "all",
        }


# ---------------------------------------------------------------------------
# Authenticated report download (replaces direct FileResponse)
# ---------------------------------------------------------------------------


class ReportAccessManager:
    """Controls access to incident reports with role-based permissions.

    Reports may contain sensitive network topology and configuration data.
    Access should be restricted to authorized roles.
    """

    ALLOWED_ROLES = {"viewer", "operator", "approver", "admin"}

    @staticmethod
    def can_access(role: str, incident_id: str, store=None) -> bool:
        """Check if a role can access a specific incident report."""
        if role not in ReportAccessManager.ALLOWED_ROLES:
            return False
        # In production, also verify the user's tenant matches the incident's tenant
        return True

    @staticmethod
    def get_download_url(
        incident_id: str,
        base_url: str = "",
        format: str = "html",
        token: str = "",
    ) -> str:
        """Generate an authenticated download URL for a report."""
        url = f"{base_url}/api/netheal/v1/incidents/{incident_id}/report/download/{format}"
        if token:
            url += f"?token={token}"
        return url

    @staticmethod
    def log_access(
        incident_id: str,
        actor: str,
        role: str,
        format: str,
        store=None,
    ) -> None:
        """Log report access for audit trail."""
        logger.info(f"Report access: incident={incident_id}, actor={actor}, role={role}, format={format}")
        if store:
            try:
                store.add_audit(
                    incident_id,
                    actor,
                    role,
                    "report_download",
                    "success",
                    {"format": format},
                    datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                )
            except Exception:
                pass
