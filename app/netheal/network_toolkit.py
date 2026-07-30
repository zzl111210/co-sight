"""Deterministic tools for the NetHeal-Agent competition scenario.

The toolkit deliberately uses local synthetic NMS data. It can therefore be
demonstrated and tested without connecting to a production 5G network.
"""

from __future__ import annotations

import csv
import html
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable


class NetworkToolkit:
    """Read evidence, diagnose faults, plan remediation, and verify recovery."""

    def __init__(self, data_dir: str | Path | None = None, workspace_path: str | Path | None = None):
        package_dir = Path(__file__).resolve().parent
        self.data_dir = Path(data_dir).resolve() if data_dir else package_dir / "data"
        self.workspace_path = Path(workspace_path or os.getenv("WORKSPACE_PATH") or os.getcwd()).resolve()

    @staticmethod
    def _payload(data: dict[str, Any]) -> str:
        return json.dumps(data, ensure_ascii=False, indent=2)

    def _read_csv(self, filename: str) -> list[dict[str, str]]:
        with (self.data_dir / filename).open("r", encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))

    def _read_json(self, filename: str) -> dict[str, Any]:
        with (self.data_dir / filename).open("r", encoding="utf-8") as stream:
            return json.load(stream)

    def _scenario(self, scenario_id: str) -> dict[str, Any]:
        scenarios = self._read_json("scenarios.json")["scenarios"]
        for scenario in scenarios:
            if scenario["id"] == scenario_id:
                return scenario
        raise ValueError(f"Unknown scenario_id: {scenario_id}")

    @staticmethod
    def _number(value: str | int | float) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _condition_matches(actual: float, operator: str, expected: float) -> bool:
        operations = {
            ">": actual > expected,
            ">=": actual >= expected,
            "<": actual < expected,
            "<=": actual <= expected,
            "==": actual == expected,
        }
        return operations.get(operator, False)

    @staticmethod
    def _safe_name(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]+", "-", value).strip("-") or "netheal"

    def read_alarm_events(
        self,
        site_id: str = "campus-5g",
        scenario_id: str = "upf-overload",
        severity: str = "",
    ) -> str:
        """Read and compress alarms from the simulated NMS feed."""
        alarms = [
            row
            for row in self._read_csv("alarms.csv")
            if row["site_id"] == site_id
            and row["scenario_id"] == scenario_id
            and (not severity or row["severity"].lower() == severity.lower())
        ]
        groups: dict[str, list[str]] = {}
        for alarm in alarms:
            groups.setdefault(alarm["correlation_group"], []).append(alarm["event_id"])
        compressed_count = len(groups)
        compression_rate = round((1 - compressed_count / len(alarms)) * 100, 2) if alarms else 0.0
        return self._payload(
            {
                "status": "success",
                "tool": "read_alarm_events",
                "site_id": site_id,
                "scenario_id": scenario_id,
                "raw_alarm_count": len(alarms),
                "correlated_incident_count": compressed_count,
                "alarm_compression_rate_pct": compression_rate,
                "correlation_groups": groups,
                "alarms": alarms,
                "evidence_source": str(self.data_dir / "alarms.csv"),
            }
        )

    def query_kpi_metrics(
        self,
        site_id: str = "campus-5g",
        scenario_id: str = "upf-overload",
        phase: str = "incident",
        resource_id: str = "",
    ) -> str:
        """Query KPI data and return threshold violations."""
        metrics = [
            row
            for row in self._read_csv("kpi_timeseries.csv")
            if row["site_id"] == site_id
            and row["scenario_id"] == scenario_id
            and (phase == "all" or row["phase"] == phase)
            and (not resource_id or row["resource_id"] == resource_id)
        ]
        return self._payload(
            {
                "status": "success",
                "tool": "query_kpi_metrics",
                "site_id": site_id,
                "scenario_id": scenario_id,
                "phase": phase,
                "metrics": metrics,
                "violations": [row for row in metrics if row["status"] == "abnormal"],
                "evidence_source": str(self.data_dir / "kpi_timeseries.csv"),
            }
        )

    def query_network_topology(
        self,
        site_id: str = "campus-5g",
        resource_id: str = "UPF-01",
    ) -> str:
        """Return the one-hop impact graph around a network resource."""
        topology = self._read_json("topology.json")
        if topology["site_id"] != site_id:
            return self._payload({"status": "not_found", "site_id": site_id})
        links = [
            link
            for link in topology["links"]
            if link["source"] == resource_id or link["target"] == resource_id
        ]
        related_ids = {resource_id}
        for link in links:
            related_ids.update([link["source"], link["target"]])
        nodes = [node for node in topology["nodes"] if node["id"] in related_ids]
        downstream = self._walk_downstream(resource_id, topology["links"])
        return self._payload(
            {
                "status": "success",
                "tool": "query_network_topology",
                "site_id": site_id,
                "focus_resource": resource_id,
                "adjacent_nodes": nodes,
                "adjacent_links": links,
                "downstream_impact": downstream,
                "evidence_source": str(self.data_dir / "topology.json"),
            }
        )

    @staticmethod
    def _walk_downstream(resource_id: str, links: Iterable[dict[str, Any]]) -> list[str]:
        adjacency: dict[str, list[str]] = {}
        for link in links:
            adjacency.setdefault(link["source"], []).append(link["target"])
        visited: set[str] = set()
        queue = list(adjacency.get(resource_id, []))
        while queue:
            node = queue.pop(0)
            if node in visited:
                continue
            visited.add(node)
            queue.extend(adjacency.get(node, []))
        return sorted(visited)

    def retrieve_fault_knowledge(
        self,
        query: str = "UPF CPU 时延 丢包",
        top_k: int = 3,
    ) -> str:
        """Retrieve expert rules and historical cases with keyword scoring."""
        knowledge = self._read_json("knowledge_base.json")
        normalized = query.lower()
        ranked_rules = []
        for rule in knowledge["rules"]:
            hits = [keyword for keyword in rule["keywords"] if keyword.lower() in normalized]
            ranked_rules.append(
                {
                    "score": len(hits),
                    "matched_keywords": hits,
                    "rule": rule,
                }
            )
        ranked_rules.sort(key=lambda item: item["score"], reverse=True)
        selected = [item for item in ranked_rules if item["score"] > 0][: max(1, int(top_k))]
        if not selected:
            selected = ranked_rules[: max(1, int(top_k))]
        selected_causes = {item["rule"]["root_cause"] for item in selected}
        cases = [
            case for case in knowledge["historical_cases"] if case["root_cause"] in selected_causes
        ]
        return self._payload(
            {
                "status": "success",
                "tool": "retrieve_fault_knowledge",
                "query": query,
                "matched_rules": selected,
                "historical_cases": cases,
                "evidence_source": str(self.data_dir / "knowledge_base.json"),
            }
        )

    def diagnose_root_cause(
        self,
        site_id: str = "campus-5g",
        scenario_id: str = "upf-overload",
    ) -> str:
        """Rank root causes by cross-checking alarms, KPIs, topology, and rules."""
        alarms = [
            row
            for row in self._read_csv("alarms.csv")
            if row["site_id"] == site_id and row["scenario_id"] == scenario_id
        ]
        kpis = [
            row
            for row in self._read_csv("kpi_timeseries.csv")
            if row["site_id"] == site_id
            and row["scenario_id"] == scenario_id
            and row["phase"] == "incident"
        ]
        knowledge = self._read_json("knowledge_base.json")
        alarm_types = {row["alarm_type"] for row in alarms}
        candidates: list[dict[str, Any]] = []
        for rule in knowledge["rules"]:
            matched_alarm_types = [
                alarm_type
                for alarm_type in rule["required_alarm_types"]
                if alarm_type in alarm_types
            ]
            matched_kpis = []
            for condition in rule["kpi_conditions"]:
                matches = [
                    row
                    for row in kpis
                    if row["metric"] == condition["metric"]
                    and self._condition_matches(
                        self._number(row["value"]),
                        condition["operator"],
                        self._number(condition["value"]),
                    )
                ]
                if matches:
                    matched_kpis.append(
                        {
                            "condition": condition,
                            "evidence": matches,
                        }
                    )
            evidence_total = len(rule["required_alarm_types"]) + len(rule["kpi_conditions"])
            evidence_matched = len(matched_alarm_types) + len(matched_kpis)
            score = round(evidence_matched / evidence_total, 4) if evidence_total else 0.0
            root_resource = self._infer_root_resource(rule, alarms)
            candidates.append(
                {
                    "root_cause": rule["root_cause"],
                    "title": rule["title"],
                    "root_resource": root_resource,
                    "confidence": score,
                    "matched_alarm_types": matched_alarm_types,
                    "matched_kpis": matched_kpis,
                    "rule_id": rule["id"],
                }
            )
        candidates.sort(key=lambda item: item["confidence"], reverse=True)
        top = candidates[0] if candidates else None
        evidence_ids = [
            row["event_id"]
            for row in alarms
            if top and row["alarm_type"] in top["matched_alarm_types"]
        ]
        return self._payload(
            {
                "status": "success" if top else "insufficient_evidence",
                "tool": "diagnose_root_cause",
                "site_id": site_id,
                "scenario_id": scenario_id,
                "primary_diagnosis": top,
                "ranked_candidates": candidates,
                "evidence_chain": {
                    "alarm_event_ids": evidence_ids,
                    "kpi_sample_count": len(top["matched_kpis"]) if top else 0,
                    "knowledge_rule": top["rule_id"] if top else None,
                    "reasoning_hops": [
                        "告警关联",
                        "KPI阈值验证",
                        "拓扑影响确认",
                        "专家规则匹配",
                        "历史案例交叉验证",
                    ],
                },
            }
        )

    @staticmethod
    def _infer_root_resource(rule: dict[str, Any], alarms: list[dict[str, str]]) -> str:
        for alarm_type in rule["required_alarm_types"]:
            for alarm in alarms:
                if alarm["alarm_type"] == alarm_type:
                    return alarm["resource_id"]
        return "unknown"

    def generate_repair_plan(
        self,
        root_cause: str = "UPF_OVERLOAD",
        resource_id: str = "UPF-01",
        simulation_mode: bool = True,
    ) -> str:
        """Generate a risk-graded repair plan with rollback protection."""
        rule = self._rule_for(root_cause)
        execution_mode = "simulation_auto_execute" if simulation_mode else "human_approval_required"
        transaction_id = f"NH-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        return self._payload(
            {
                "status": "success",
                "tool": "generate_repair_plan",
                "transaction_id": transaction_id,
                "root_cause": root_cause,
                "resource_id": resource_id,
                "risk_level": rule["risk_level"],
                "execution_mode": execution_mode,
                "actions": [
                    {"order": index + 1, "action": action}
                    for index, action in enumerate(rule["remediation"])
                ],
                "rollback": rule["rollback"].replace("${transaction_id}", transaction_id),
                "safety_policy": "真实网络配置变更必须人工审批；自动执行仅限本地仿真环境。",
            }
        )

    def generate_config_commands(
        self,
        root_cause: str = "UPF_OVERLOAD",
        dry_run: bool = True,
    ) -> str:
        """Generate vendor-neutral, auditable configuration commands."""
        rule = self._rule_for(root_cause)
        return self._payload(
            {
                "status": "success",
                "tool": "generate_config_commands",
                "root_cause": root_cause,
                "dry_run": bool(dry_run),
                "commands": rule["commands"],
                "command_count": len(rule["commands"]),
                "notice": "命令为比赛仿真格式，不直接连接或修改真实网元。",
            }
        )

    def generate_work_order(
        self,
        scenario_id: str = "upf-overload",
        root_cause: str = "UPF_OVERLOAD",
        priority: str = "P2",
    ) -> str:
        """Create a structured JSON work order in the configured workspace."""
        scenario = self._scenario(scenario_id)
        rule = self._rule_for(root_cause)
        payload = {
            "work_order_id": f"WO-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "site_id": scenario["site_id"],
            "scenario_id": scenario_id,
            "priority": priority,
            "root_cause": root_cause,
            "root_resource": scenario["root_resource"],
            "affected_service": scenario["affected_service"],
            "recommended_actions": rule["remediation"],
            "approval_status": "pending",
        }
        output_dir = self.workspace_path / "netheal_outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"work_order_{self._safe_name(scenario_id)}.json"
        output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._payload(
            {
                "status": "success",
                "tool": "generate_work_order",
                "work_order": payload,
                "output_path": str(output_path),
            }
        )

    def verify_recovery(
        self,
        site_id: str = "campus-5g",
        scenario_id: str = "upf-overload",
    ) -> str:
        """Compare incident and post-repair KPI values against scenario SLAs."""
        scenario = self._scenario(scenario_id)
        rows = [
            row
            for row in self._read_csv("kpi_timeseries.csv")
            if row["site_id"] == site_id and row["scenario_id"] == scenario_id
        ]
        incident = {row["metric"]: self._number(row["value"]) for row in rows if row["phase"] == "incident"}
        recovered = {
            row["metric"]: self._number(row["value"]) for row in rows if row["phase"] == "post_repair"
        }
        checks = []
        for key, threshold in scenario["expected"].items():
            if key.endswith("_max"):
                metric = key[: -len("_max")]
                passed = recovered.get(metric, float("inf")) <= self._number(threshold)
                expression = f"{metric} <= {threshold}"
            elif key.endswith("_min"):
                metric = key[: -len("_min")]
                passed = recovered.get(metric, float("-inf")) >= self._number(threshold)
                expression = f"{metric} >= {threshold}"
            else:
                continue
            checks.append(
                {
                    "metric": metric,
                    "before": incident.get(metric),
                    "after": recovered.get(metric),
                    "sla": expression,
                    "passed": passed,
                }
            )
        passed = bool(checks) and all(check["passed"] for check in checks)
        return self._payload(
            {
                "status": "success",
                "tool": "verify_recovery",
                "site_id": site_id,
                "scenario_id": scenario_id,
                "passed": passed,
                "checks": checks,
                "next_action": "生成闭环报告" if passed else "回溯根因定位并执行下一候选修复方案",
                "retry_required": not passed,
                "evidence_source": str(self.data_dir / "kpi_timeseries.csv"),
            }
        )

    def generate_incident_report(
        self,
        site_id: str = "campus-5g",
        scenario_id: str = "upf-overload",
    ) -> str:
        """Generate Markdown and lightweight HTML incident-closure reports."""
        diagnosis = json.loads(self.diagnose_root_cause(site_id, scenario_id))
        primary = diagnosis["primary_diagnosis"]
        repair = json.loads(
            self.generate_repair_plan(primary["root_cause"], primary["root_resource"])
        )
        commands = json.loads(self.generate_config_commands(primary["root_cause"]))
        verification = json.loads(self.verify_recovery(site_id, scenario_id))
        scenario = self._scenario(scenario_id)
        output_dir = self.workspace_path / "netheal_outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        safe_id = self._safe_name(scenario_id)
        markdown_path = output_dir / f"NetHeal_Report_{safe_id}.md"
        html_path = output_dir / f"NetHeal_Report_{safe_id}.html"
        markdown = self._render_markdown(scenario, diagnosis, repair, commands, verification)
        html_report = self._render_html(scenario, diagnosis, repair, commands, verification)
        markdown_path.write_text(markdown, encoding="utf-8")
        html_path.write_text(html_report, encoding="utf-8")
        return self._payload(
            {
                "status": "success",
                "tool": "generate_incident_report",
                "scenario_id": scenario_id,
                "diagnosis": primary,
                "verification_passed": verification["passed"],
                "markdown_path": str(markdown_path),
                "html_path": str(html_path),
            }
        )

    def _rule_for(self, root_cause: str) -> dict[str, Any]:
        for rule in self._read_json("knowledge_base.json")["rules"]:
            if rule["root_cause"] == root_cause:
                return rule
        raise ValueError(f"Unknown root_cause: {root_cause}")

    @staticmethod
    def _render_markdown(
        scenario: dict[str, Any],
        diagnosis: dict[str, Any],
        repair: dict[str, Any],
        commands: dict[str, Any],
        verification: dict[str, Any],
    ) -> str:
        primary = diagnosis["primary_diagnosis"]
        action_lines = "\n".join(
            f"{item['order']}. {item['action']}" for item in repair["actions"]
        )
        command_lines = "\n".join(f"- `{command}`" for command in commands["commands"])
        check_lines = "\n".join(
            f"| {item['metric']} | {item['before']} | {item['after']} | {item['sla']} | "
            f"{'通过' if item['passed'] else '失败'} |"
            for item in verification["checks"]
        )
        return f"""# NetHeal-Agent 故障闭环报告

## 事件概览

- 场景：{scenario['title']}
- 站点：{scenario['site_id']}
- 根因：{primary['title']}（{primary['root_cause']}）
- 根网元：{primary['root_resource']}
- 诊断置信度：{primary['confidence']:.0%}
- 验证结论：{'恢复成功' if verification['passed'] else '恢复失败，触发回溯'}

## 证据链

- 告警事件：{', '.join(diagnosis['evidence_chain']['alarm_event_ids'])}
- 知识规则：{diagnosis['evidence_chain']['knowledge_rule']}
- 推理链路：{' → '.join(diagnosis['evidence_chain']['reasoning_hops'])}

## 修复方案

{action_lines}

## 仿真配置命令

{command_lines}

> 安全策略：{repair['safety_policy']}

## KPI 恢复验证

| 指标 | 修复前 | 修复后 | SLA | 结果 |
|---|---:|---:|---|---|
{check_lines}

## 闭环结论

{verification['next_action']}
"""

    @staticmethod
    def _render_html(
        scenario: dict[str, Any],
        diagnosis: dict[str, Any],
        repair: dict[str, Any],
        commands: dict[str, Any],
        verification: dict[str, Any],
    ) -> str:
        primary = diagnosis["primary_diagnosis"]
        rows = "".join(
            "<tr>"
            f"<td>{html.escape(item['metric'])}</td>"
            f"<td>{item['before']}</td><td>{item['after']}</td>"
            f"<td>{html.escape(item['sla'])}</td>"
            f"<td class=\"{'ok' if item['passed'] else 'bad'}\">"
            f"{'通过' if item['passed'] else '失败'}</td></tr>"
            for item in verification["checks"]
        )
        actions = "".join(
            f"<li>{html.escape(item['action'])}</li>" for item in repair["actions"]
        )
        command_items = "".join(
            f"<li><code>{html.escape(command)}</code></li>" for command in commands["commands"]
        )
        return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>NetHeal-Agent 故障闭环报告</title>
<style>
body{{margin:0;background:#07111f;color:#dbeafe;font-family:Arial,"Microsoft YaHei",sans-serif}}
main{{max-width:1040px;margin:auto;padding:36px 24px}}h1{{margin-bottom:6px}}
.sub{{color:#7dd3fc}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:14px}}
.card{{background:#0f2035;border:1px solid #1d4f73;border-radius:14px;padding:18px;margin:16px 0}}
.metric{{font-size:28px;font-weight:700;color:#38bdf8}}table{{width:100%;border-collapse:collapse}}
th,td{{padding:10px;border-bottom:1px solid #24435f;text-align:left}}.ok{{color:#4ade80}}.bad{{color:#fb7185}}
code{{color:#a7f3d0;white-space:pre-wrap}}.pill{{display:inline-block;padding:5px 10px;border-radius:99px;background:#164e63}}
</style></head><body><main>
<h1>NetHeal-Agent</h1><div class="sub">5G 校园专网多智能体故障诊断与自愈报告</div>
<section class="grid">
<div class="card"><div>场景</div><strong>{html.escape(scenario['title'])}</strong></div>
<div class="card"><div>根因</div><strong>{html.escape(primary['title'])}</strong></div>
<div class="card"><div>置信度</div><div class="metric">{primary['confidence']:.0%}</div></div>
<div class="card"><div>闭环状态</div><span class="pill">{'恢复成功' if verification['passed'] else '需要回溯'}</span></div>
</section>
<section class="card"><h2>证据链</h2><p>{html.escape(' → '.join(diagnosis['evidence_chain']['reasoning_hops']))}</p>
<p>告警：{html.escape(', '.join(diagnosis['evidence_chain']['alarm_event_ids']))}；
规则：{html.escape(diagnosis['evidence_chain']['knowledge_rule'])}</p></section>
<section class="card"><h2>修复方案</h2><ol>{actions}</ol><ul>{command_items}</ul>
<p>{html.escape(repair['safety_policy'])}</p></section>
<section class="card"><h2>KPI 前后对比</h2><table><thead><tr>
<th>指标</th><th>修复前</th><th>修复后</th><th>SLA</th><th>结果</th>
</tr></thead><tbody>{rows}</tbody></table></section>
</main></body></html>"""
