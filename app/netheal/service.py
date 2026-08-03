"""Application service orchestrating NetHeal tools and incident lifecycle."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.netheal.domain import (
    Incident,
    IncidentStatus,
    ensure_permission,
    ensure_transition,
)
from app.netheal.network_toolkit import NetworkToolkit
from app.netheal.store import NetHealStore


class NetHealService:
    def __init__(
        self,
        workspace_path: str | Path = "work_space",
        database_path: str | Path | None = None,
        toolkit: NetworkToolkit | None = None,
    ):
        self.workspace_path = Path(workspace_path).resolve()
        self.workspace_path.mkdir(parents=True, exist_ok=True)
        self.toolkit = toolkit or NetworkToolkit(workspace_path=self.workspace_path)
        db_path = database_path or self.workspace_path / "netheal" / "netheal.db"
        self.store = NetHealStore(db_path)
        self._lock = threading.RLock()
        self.bootstrap()

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    @staticmethod
    def _decode(payload: str) -> dict[str, Any]:
        return json.loads(payload)

    def _scenario(self, scenario_id: str) -> dict[str, Any]:
        return self.toolkit._scenario(scenario_id)

    def _incident_id(self) -> str:
        return f"NH-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

    def bootstrap(self) -> None:
        if self.store.list_incidents(limit=1):
            return
        now = self._now()
        seed_specs = [
            ("NH-DEMO-001", "upf-overload", "critical", IncidentStatus.DETECTED.value),
            ("NH-DEMO-002", "backhaul-link-down", "critical", IncidentStatus.CLOSED.value),
            (
                "NH-DEMO-003",
                "slice-capacity-shortage",
                "major",
                IncidentStatus.APPROVAL_PENDING.value,
            ),
        ]
        for incident_id, scenario_id, severity, status in seed_specs:
            scenario = self._scenario(scenario_id)
            incident = Incident(
                id=incident_id,
                site_id=scenario["site_id"],
                scenario_id=scenario_id,
                title=scenario["title"],
                severity=severity,
                status=status,
                affected_service=scenario["affected_service"],
                created_at=now,
                updated_at=now,
            ).to_dict()
            if status in {IncidentStatus.CLOSED.value, IncidentStatus.APPROVAL_PENDING.value}:
                diagnosis = self._decode(
                    self.toolkit.diagnose_root_cause(scenario["site_id"], scenario_id)
                )
                primary = diagnosis["primary_diagnosis"]
                repair_plan = self._decode(
                    self.toolkit.generate_repair_plan(
                        primary["root_cause"],
                        primary["root_resource"],
                        simulation_mode=True,
                    )
                )
                incident.update(
                    {
                        "root_cause": primary["root_cause"],
                        "root_resource": primary["root_resource"],
                        "confidence": primary["confidence"],
                        "risk_level": repair_plan["risk_level"],
                        "evidence": diagnosis["evidence_chain"],
                        "repair": {"plan": repair_plan},
                    }
                )
            if status == IncidentStatus.CLOSED.value:
                verification = self._decode(
                    self.toolkit.verify_recovery(scenario["site_id"], scenario_id)
                )
                incident["verification_passed"] = bool(verification["passed"])
                incident["repair"]["verification"] = verification
            self.store.upsert_incident(incident)
            self.store.add_event(
                incident_id,
                "incident_seeded",
                "system",
                f"载入演示事件：{scenario['title']}",
                {"status": status},
                now,
            )

    def reset_demo(self, actor: str, role: str) -> dict[str, Any]:
        self._authorize(None, actor, role, "reset")
        with self._lock:
            self.store.clear()
            self.bootstrap()
            self._audit(None, actor, role, "reset_demo", "success", {})
        return self.overview()

    def _audit(
        self,
        incident_id: str | None,
        actor: str,
        role: str,
        action: str,
        result: str,
        detail: dict[str, Any],
    ) -> None:
        self.store.add_audit(
            incident_id,
            actor,
            role,
            action,
            result,
            detail,
            self._now(),
        )

    def _authorize(
        self,
        incident_id: str | None,
        actor: str,
        role: str,
        action: str,
    ) -> None:
        try:
            ensure_permission(role, action)
        except PermissionError:
            self._audit(
                incident_id,
                actor,
                role,
                "authorization_denied",
                "denied",
                {"requested_action": action},
            )
            raise

    def _event(
        self,
        incident_id: str,
        event_type: str,
        actor: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        self.store.add_event(
            incident_id,
            event_type,
            actor,
            message,
            payload or {},
            self._now(),
        )

    def _transition(
        self,
        incident: dict[str, Any],
        target: IncidentStatus,
        actor: str,
        message: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ensure_transition(incident["status"], target.value)
        incident["status"] = target.value
        incident["updated_at"] = self._now()
        incident["version"] = int(incident.get("version", 1)) + 1
        self.store.upsert_incident(incident)
        self._event(incident["id"], "status_changed", actor, message, {
            "status": target.value,
            **(payload or {}),
        })
        return incident

    def create_incident(
        self,
        scenario_id: str,
        actor: str = "operator",
        role: str = "operator",
    ) -> dict[str, Any]:
        self._authorize(None, actor, role, "diagnose")
        scenario = self._scenario(scenario_id)
        now = self._now()
        severity = {
            "upf-overload": "critical",
            "backhaul-link-down": "critical",
            "slice-capacity-shortage": "major",
            "alarm-storm-composite": "critical",
        }.get(scenario_id, "major")
        incident = Incident(
            id=self._incident_id(),
            site_id=scenario["site_id"],
            scenario_id=scenario_id,
            title=scenario["title"],
            severity=severity,
            affected_service=scenario["affected_service"],
            created_at=now,
            updated_at=now,
        ).to_dict()
        self.store.upsert_incident(incident)
        self._event(
            incident["id"],
            "incident_detected",
            actor,
            "网管告警触发新事件",
            {"scenario_id": scenario_id},
        )
        self._audit(incident["id"], actor, role, "create_incident", "success", {})
        return incident

    def diagnose(
        self,
        scenario_id: str = "upf-overload",
        incident_id: str | None = None,
        actor: str = "operator",
        role: str = "operator",
    ) -> dict[str, Any]:
        self._authorize(incident_id, actor, role, "diagnose")
        with self._lock:
            incident = (
                self.store.get_incident(incident_id)
                if incident_id
                else self.create_incident(scenario_id, actor, role)
            )
            if incident is None:
                raise KeyError(f"Incident not found: {incident_id}")
            if incident["status"] == IncidentStatus.NEEDS_REVIEW.value:
                self._transition(
                    incident,
                    IncidentStatus.DIAGNOSING,
                    actor,
                    "验证失败后重新进入根因分析",
                )
            elif incident["status"] == IncidentStatus.DETECTED.value:
                self._transition(
                    incident,
                    IncidentStatus.DIAGNOSING,
                    actor,
                    "多智能体开始并行取证",
                )
            else:
                raise ValueError(f"Incident cannot be diagnosed from {incident['status']}")

            alarms = self._decode(
                self.toolkit.read_alarm_events(incident["site_id"], incident["scenario_id"])
            )
            kpis = self._decode(
                self.toolkit.query_kpi_metrics(
                    incident["site_id"], incident["scenario_id"], "incident"
                )
            )
            scenario = self._scenario(incident["scenario_id"])
            topology = self._decode(
                self.toolkit.query_network_topology(
                    incident["site_id"], scenario["root_resource"]
                )
            )
            knowledge = self._decode(
                self.toolkit.retrieve_fault_knowledge(scenario["title"])
            )
            diagnosis = self._decode(
                self.toolkit.diagnose_root_cause(
                    incident["site_id"], incident["scenario_id"]
                )
            )
            primary = diagnosis["primary_diagnosis"]
            repair_plan = self._decode(
                self.toolkit.generate_repair_plan(
                    primary["root_cause"],
                    primary["root_resource"],
                    simulation_mode=True,
                )
            )
            incident.update(
                {
                    "root_cause": primary["root_cause"],
                    "root_resource": primary["root_resource"],
                    "confidence": primary["confidence"],
                    "risk_level": repair_plan["risk_level"],
                    "repair": {"plan": repair_plan},
                    "evidence": {
                        **diagnosis["evidence_chain"],
                        "alarm_summary": {
                            "raw": alarms["raw_alarm_count"],
                            "correlated": alarms["correlated_incident_count"],
                            "compression_rate_pct": alarms["alarm_compression_rate_pct"],
                        },
                        "kpi_violations": kpis["violations"],
                        "downstream_impact": topology["downstream_impact"],
                        "knowledge_matches": [
                            item["rule"]["id"] for item in knowledge["matched_rules"]
                        ],
                        "ranked_candidates": diagnosis["ranked_candidates"],
                    },
                }
            )
            self.store.upsert_incident(incident)
            self._event(
                incident["id"],
                "diagnosis_completed",
                actor,
                f"根因定位：{primary['title']}，置信度 {primary['confidence']:.0%}",
                {"root_cause": primary["root_cause"], "confidence": primary["confidence"]},
            )
            self._transition(
                incident,
                IncidentStatus.APPROVAL_PENDING,
                actor,
                "中风险修复方案进入人工审批",
            )
            self._audit(
                incident["id"],
                actor,
                role,
                "diagnose",
                "success",
                {"root_cause": incident["root_cause"]},
            )
            return self.detail(incident["id"])

    def approve(
        self,
        incident_id: str,
        actor: str,
        role: str,
        comment: str = "",
    ) -> dict[str, Any]:
        self._authorize(incident_id, actor, role, "approve")
        with self._lock:
            incident = self._require_incident(incident_id)
            self._transition(
                incident,
                IncidentStatus.APPROVED,
                actor,
                "审批人批准仿真修复",
                {"comment": comment},
            )
            self._audit(
                incident_id,
                actor,
                role,
                "approve",
                "success",
                {"comment": comment},
            )
            return self.detail(incident_id)

    def execute(
        self,
        incident_id: str,
        actor: str,
        role: str,
    ) -> dict[str, Any]:
        self._authorize(incident_id, actor, role, "execute")
        with self._lock:
            incident = self._require_incident(incident_id)
            self._transition(
                incident,
                IncidentStatus.EXECUTING,
                actor,
                "开始执行仿真修复事务",
            )
            repair = incident.get("repair", {}).get("plan")
            if not repair:
                repair = self._decode(
                    self.toolkit.generate_repair_plan(
                        incident["root_cause"],
                        incident["root_resource"],
                        simulation_mode=True,
                    )
                )
            commands = self._decode(
                self.toolkit.generate_config_commands(
                    incident["root_cause"], dry_run=True
                )
            )
            work_order = self._decode(
                self.toolkit.generate_work_order(
                    incident["scenario_id"], incident["root_cause"]
                )
            )
            incident["repair"] = {
                "plan": repair,
                "commands": commands,
                "work_order": work_order,
            }
            self.store.upsert_incident(incident)
            self._event(
                incident_id,
                "repair_executed",
                actor,
                f"仿真事务 {repair['transaction_id']} 执行完成",
                {
                    "transaction_id": repair["transaction_id"],
                    "dry_run": commands["dry_run"],
                    "command_count": commands["command_count"],
                },
            )
            self._transition(
                incident,
                IncidentStatus.VERIFYING,
                actor,
                "进入5分钟KPI恢复观察窗",
            )
            self._audit(
                incident_id,
                actor,
                role,
                "execute_simulation",
                "success",
                {"transaction_id": repair["transaction_id"]},
            )
            return self.detail(incident_id)

    def verify(
        self,
        incident_id: str,
        actor: str,
        role: str,
    ) -> dict[str, Any]:
        self._authorize(incident_id, actor, role, "verify")
        with self._lock:
            incident = self._require_incident(incident_id)
            if incident["status"] != IncidentStatus.VERIFYING.value:
                raise ValueError(f"Incident cannot be verified from {incident['status']}")
            verification = self._decode(
                self.toolkit.verify_recovery(
                    incident["site_id"], incident["scenario_id"]
                )
            )
            report = self._decode(
                self.toolkit.generate_incident_report(
                    incident["site_id"], incident["scenario_id"]
                )
            )
            incident["verification_passed"] = bool(verification["passed"])
            incident.setdefault("repair", {})["verification"] = verification
            incident["repair"]["report"] = report
            self.store.upsert_incident(incident)
            target = (
                IncidentStatus.CLOSED
                if verification["passed"]
                else IncidentStatus.NEEDS_REVIEW
            )
            self._transition(
                incident,
                target,
                actor,
                (
                    "SLA恢复，事件自动闭环"
                    if verification["passed"]
                    else "SLA未恢复，触发重新诊断"
                ),
                {"checks": verification["checks"]},
            )
            self._audit(
                incident_id,
                actor,
                role,
                "verify_recovery",
                "success" if verification["passed"] else "needs_review",
                {"passed": verification["passed"]},
            )
            return self.detail(incident_id)

    def run_demo(
        self,
        scenario_id: str = "upf-overload",
        actor: str = "demo-director",
        role: str = "approver",
    ) -> dict[str, Any]:
        self._authorize(None, actor, role, "approve")
        incident = self.diagnose(scenario_id, actor=actor, role=role)["incident"]
        self.approve(incident["id"], actor, role, "比赛演示：批准仿真修复")
        self.execute(incident["id"], actor, role)
        return self.verify(incident["id"], actor, role)

    def _require_incident(self, incident_id: str) -> dict[str, Any]:
        incident = self.store.get_incident(incident_id)
        if incident is None:
            raise KeyError(f"Incident not found: {incident_id}")
        return incident

    def detail(self, incident_id: str) -> dict[str, Any]:
        incident = self._require_incident(incident_id)
        return {
            "incident": incident,
            "events": self.store.list_events(incident_id),
        }

    def incidents(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.store.list_incidents(limit)

    def scenarios(self) -> list[dict[str, Any]]:
        rows = self.toolkit._read_json("scenarios.json")["scenarios"]
        return [
            {
                **scenario,
                "acceptance_criteria": [
                    f"根因编码为 {scenario['ground_truth']}",
                    f"根网元定位为 {scenario['root_resource']}",
                    "事件状态最终为 closed",
                    "恢复验证 verification_passed 为 true",
                    "生成仿真命令、工单及闭环报告",
                ],
                "execution_mode": "simulation",
                "real_network_write_enabled": False,
            }
            for scenario in rows
        ]

    def overview(self) -> dict[str, Any]:
        incidents = self.store.list_incidents()
        active = [
            incident
            for incident in incidents
            if incident["status"] != IncidentStatus.CLOSED.value
        ]
        diagnosed = [
            incident for incident in incidents if incident.get("confidence") is not None
        ]
        return {
            "site_id": "campus-5g",
            "site_name": "5G校园专网",
            "network_health_score": 92 if active else 99,
            "active_incidents": len(active),
            "critical_incidents": sum(
                incident["severity"] == "critical" for incident in active
            ),
            "closed_incidents": sum(
                incident["status"] == IncidentStatus.CLOSED.value
                for incident in incidents
            ),
            "mean_confidence_pct": round(
                (
                    sum(float(incident["confidence"]) for incident in diagnosed)
                    / len(diagnosed)
                    * 100
                )
                if diagnosed
                else 0,
                1,
            ),
            "auto_closure_rate_pct": round(
                (
                    sum(
                        incident["status"] == IncidentStatus.CLOSED.value
                        for incident in incidents
                    )
                    / len(incidents)
                    * 100
                )
                if incidents
                else 0,
                1,
            ),
            "last_updated": self._now(),
        }

    def topology(self, incident_id: str | None = None) -> dict[str, Any]:
        topology = self.toolkit._read_json("topology.json")
        incident = self.store.get_incident(incident_id) if incident_id else None
        nodes = []
        for node in topology["nodes"]:
            item = dict(node)
            item["health"] = "normal"
            if incident and node["id"] == incident.get("root_resource"):
                item["health"] = (
                    "normal"
                    if incident["status"] == IncidentStatus.CLOSED.value
                    else "critical"
                )
            elif incident and node["id"] in incident.get("evidence", {}).get(
                "downstream_impact", []
            ):
                item["health"] = "affected"
            nodes.append(item)
        return {**topology, "nodes": nodes}

    def metrics(
        self,
        scenario_id: str = "upf-overload",
    ) -> dict[str, Any]:
        rows = [
            row
            for row in self.toolkit._read_csv("kpi_timeseries.csv")
            if row["scenario_id"] == scenario_id
        ]
        for row in rows:
            row["value"] = float(row["value"])
            row["threshold"] = float(row["threshold"])
        return {"scenario_id": scenario_id, "series": rows}

    def workflow(self) -> dict[str, Any]:
        workflow_path = (
            Path(__file__).resolve().parent / "workflows" / "netheal_dag.json"
        )
        return json.loads(workflow_path.read_text(encoding="utf-8"))

    def audit(self, limit: int = 50) -> list[dict[str, Any]]:
        return self.store.list_audit(limit)

    def health(self) -> dict[str, Any]:
        data_files = [
            "alarms.csv",
            "kpi_timeseries.csv",
            "topology.json",
            "knowledge_base.json",
            "scenarios.json",
        ]
        files = {
            name: (self.toolkit.data_dir / name).is_file() for name in data_files
        }
        store_health = self.store.health()
        return {
            "status": "healthy" if all(files.values()) and store_health["ok"] else "degraded",
            "database": {
                "ok": store_health["ok"],
                "engine": "sqlite",
                "journal_mode": "WAL",
            },
            "data_files": files,
            "simulation_mode": True,
            "real_network_write_enabled": False,
            "timestamp": self._now(),
        }
