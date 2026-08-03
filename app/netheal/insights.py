"""Read-only advanced diagnosis and historical insight orchestration."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from app.netheal.advanced_diagnosis import (
    EvaluationChartGenerator,
    FusionDiagnosisEngine,
    GraphReasoner,
    VectorCaseRetriever,
)
from app.netheal.reporting import ReportSearchEngine, TrendAnalyzer
from app.netheal.service import NetHealService


class NetHealInsights:
    """Compose advanced diagnosis helpers without bloating the API router."""

    def __init__(self, service: NetHealService) -> None:
        self.service = service
        data_dir = service.toolkit.data_dir
        topology = service.toolkit._read_json("topology.json")
        self.vector_retriever = VectorCaseRetriever(
            data_dir / "knowledge_base.json"
        )
        self.graph_reasoner = GraphReasoner(topology)
        self.fusion_engine = FusionDiagnosisEngine(self.graph_reasoner)
        self.report_search = ReportSearchEngine(service.workspace_path)
        self.trend_analyzer = TrendAnalyzer(store=service.store)
        self.chart_generator = EvaluationChartGenerator(service.workspace_path)

    def _alarm_resources(self, scenario_id: str) -> list[str]:
        """Keep duplicate alarm resources as useful propagation evidence."""
        return [
            row.get("resource_id", "")
            for row in self.service.toolkit._read_csv("alarms.csv")
            if row.get("scenario_id") == scenario_id and row.get("resource_id")
        ]

    def vector_search(self, query: str, top_k: int = 5) -> dict[str, Any]:
        results = self.vector_retriever.search(query, top_k=top_k)
        return {
            "query": query,
            "total": len(results),
            "items": [asdict(item) for item in results],
            "engine": "local_tfidf",
            "dataset": "synthetic_historical_cases",
        }

    def graph_reasoning(self, scenario_id: str) -> dict[str, Any]:
        scenario = self.service._scenario(scenario_id)
        resources = self._alarm_resources(scenario_id)
        candidates = self.graph_reasoner.identify_root_candidates(resources)
        return {
            "scenario_id": scenario_id,
            "site_id": scenario["site_id"],
            "alarm_resources": resources,
            "root_candidates": candidates,
            "propagation_scores": self.graph_reasoner.propagation_score(resources),
            "expected_root_resource": scenario["root_resource"],
            "dataset": "synthetic_topology",
        }

    def fusion_diagnosis(self, scenario_id: str) -> dict[str, Any]:
        scenario = self.service._scenario(scenario_id)
        rule_diagnosis = self.service._decode(
            self.service.toolkit.diagnose_root_cause(
                scenario["site_id"],
                scenario_id,
            )
        )
        result = self.fusion_engine.fuse(
            rule_diagnosis,
            self._alarm_resources(scenario_id),
            scenario_title=scenario["title"],
        )
        payload = asdict(result)
        payload.update(
            {
                "scenario_id": scenario_id,
                "site_id": scenario["site_id"],
                "dataset": "synthetic_evidence",
            }
        )
        return payload

    def explain(self, incident_id: str) -> dict[str, Any]:
        detail = self.service.detail(incident_id)
        incident = detail["incident"]
        evidence = incident.get("evidence", {})
        hops: list[dict[str, Any]] = []

        alarm_summary = evidence.get("alarm_summary", {})
        if alarm_summary:
            hops.append(
                {
                    "stage": "alarm_correlation",
                    "title": "告警关联压缩",
                    "summary": (
                        f"{alarm_summary.get('raw', 0)} 条原始告警压缩为 "
                        f"{alarm_summary.get('correlated', 0)} 个关联事件"
                    ),
                    "evidence": alarm_summary,
                }
            )
        kpi_violations = evidence.get("kpi_violations", [])
        if kpi_violations:
            hops.append(
                {
                    "stage": "kpi_validation",
                    "title": "KPI异常验证",
                    "summary": f"发现 {len(kpi_violations)} 项异常指标",
                    "evidence": kpi_violations,
                }
            )
        knowledge_matches = evidence.get("knowledge_matches", [])
        if knowledge_matches:
            hops.append(
                {
                    "stage": "knowledge_retrieval",
                    "title": "知识与案例匹配",
                    "summary": f"命中 {len(knowledge_matches)} 条专家规则",
                    "evidence": knowledge_matches,
                }
            )
        if incident.get("root_cause"):
            hops.append(
                {
                    "stage": "root_cause_fusion",
                    "title": "融合根因定位",
                    "summary": (
                        f"{incident['root_cause']} / {incident.get('root_resource', '')} / "
                        f"{float(incident.get('confidence') or 0):.0%}"
                    ),
                    "evidence": {
                        "ranked_candidates": evidence.get("ranked_candidates", []),
                    },
                }
            )

        graph = self.graph_reasoning(incident["scenario_id"])
        return {
            "incident_id": incident_id,
            "title": incident.get("title", ""),
            "root_cause": incident.get("root_cause", ""),
            "root_resource": incident.get("root_resource", ""),
            "confidence": incident.get("confidence", 0),
            "reasoning_hops": hops,
            "graph_candidates": graph["root_candidates"],
            "lifecycle": detail.get("events", []),
        }

    def search_reports(
        self,
        query: str,
        max_results: int = 10,
        status: str | None = None,
        scenario_id: str | None = None,
    ) -> dict[str, Any]:
        # Incrementally refresh so reports created after service startup appear.
        for incident in self.service.incidents(limit=500):
            self.report_search.index_incident(incident)
        results = self.report_search.search(
            query,
            max_results=max_results,
            filter_status=status,
            filter_scenario=scenario_id,
        )
        return {
            "query": query,
            "total": len(results),
            "items": [asdict(item) for item in results],
        }

    def trends(
        self,
        scenario_id: str | None = None,
        metric: str | None = None,
    ) -> dict[str, Any]:
        points = self.trend_analyzer.compute_trends(
            scenario_id=scenario_id,
            metric=metric,
        )
        return {
            "summary": self.trend_analyzer.summary(scenario_id=scenario_id),
            "points": [asdict(point) for point in points],
        }

    def evaluation_charts(self) -> dict[str, Any]:
        report_path = (
            self.service.workspace_path
            / "netheal_acceptance"
            / "acceptance_report.json"
        )
        if report_path.is_file():
            report = json.loads(report_path.read_text(encoding="utf-8"))
        else:
            report = {"results": [], "summary": {"total": 0, "passed": 0}}
        charts = self.chart_generator.generate(report)
        charts["dataset_notice"] = (
            "图表仅基于仓库内合成场景验收结果，不代表真实运营商生产指标。"
        )
        return charts
