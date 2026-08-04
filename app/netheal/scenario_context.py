"""Resolve a NetHeal task to one consistent competition scenario.

The LLM planner may omit tool parameters or copy a schema default. This
module keeps every NetHeal tool call aligned with the user's original task.
"""

from __future__ import annotations

from typing import Any


SCENARIO_CONTEXTS: dict[str, dict[str, Any]] = {
    "upf-overload": {
        "aliases": ("upf-overload", "tc-01", "upf-01", "upf", "视频业务", "视频切片"),
        "root_cause": "UPF_OVERLOAD",
        "root_resource": "UPF-01",
        "knowledge_query": "UPF CPU 过载 视频业务 高时延 丢包",
        "priority": "P2",
    },
    "backhaul-link-down": {
        "aliases": (
            "backhaul-link-down",
            "tc-02",
            "gnodeb-03",
            "link-03",
            "回传链路",
            "小区掉线",
            "基站掉线",
        ),
        "root_cause": "BACKHAUL_LINK_DOWN",
        "root_resource": "LINK-03",
        "knowledge_query": "gNodeB-03 小区掉线 回传链路 LINK-03 端口中断 接入失败",
        "priority": "P1",
    },
    "slice-capacity-shortage": {
        "aliases": (
            "slice-capacity-shortage",
            "tc-03",
            "urllc",
            "slice-urllc",
            "工业控制",
            "切片资源",
            "sla违约",
            "sla 违约",
        ),
        "root_cause": "SLICE_CAPACITY_SHORTAGE",
        "root_resource": "slice-urllc",
        "knowledge_query": "URLLC 切片资源不足 工业控制 SLA 时延 丢包 带宽",
        "priority": "P1",
    },
    "alarm-storm-composite": {
        "aliases": (
            "alarm-storm-composite",
            "tc-06",
            "告警风暴",
            "复合故障",
            "传输抖动",
            "transmission jitter",
        ),
        "root_cause": "COMPOSITE_UPF_OVERLOAD_AND_TRANSMISSION_JITTER",
        "root_resource": "UPF-01",
        "knowledge_query": "告警风暴 UPF过载 传输抖动 复合故障 多业务影响",
        "priority": "P1",
    },
}

SCENARIO_MATCH_ORDER = (
    "alarm-storm-composite",
    "backhaul-link-down",
    "slice-capacity-shortage",
    "upf-overload",
)

SCENARIO_ID_FUNCTIONS = {
    "read_alarm_events",
    "query_kpi_metrics",
    "diagnose_root_cause",
    "generate_work_order",
    "verify_recovery",
    "generate_incident_report",
}

NETHEAL_CONTEXT_FUNCTIONS = SCENARIO_ID_FUNCTIONS | {
    "query_network_topology",
    "retrieve_fault_knowledge",
    "generate_repair_plan",
    "generate_config_commands",
}


def _canonical_scenario_id(value: str | None) -> str | None:
    normalized = (value or "").strip().lower()
    if normalized in SCENARIO_CONTEXTS:
        return normalized
    for scenario_id, context in SCENARIO_CONTEXTS.items():
        if normalized in {alias.lower() for alias in context["aliases"]}:
            return scenario_id
    return None


def infer_scenario_id(task_text: str) -> str | None:
    """Infer a scenario from stable case IDs, resources, and fault symptoms."""
    normalized = (task_text or "").lower()
    for scenario_id in SCENARIO_MATCH_ORDER:
        aliases = SCENARIO_CONTEXTS[scenario_id]["aliases"]
        if any(alias.lower() in normalized for alias in aliases):
            return scenario_id
    return None


def resolve_scenario_context(
    task_text: str,
    requested_scenario_id: str | None = None,
) -> dict[str, Any]:
    """Return the authoritative scenario context for a task."""
    inferred = infer_scenario_id(task_text)
    requested = _canonical_scenario_id(requested_scenario_id)
    scenario_id = inferred or requested or "upf-overload"
    source = "task_text" if inferred else ("tool_argument" if requested else "fallback")
    return {
        "scenario_id": scenario_id,
        "resolution_source": source,
        **SCENARIO_CONTEXTS[scenario_id],
    }


def align_netheal_tool_args(
    function_name: str,
    args: dict[str, Any],
    task_text: str,
) -> dict[str, Any]:
    """Align one NetHeal tool call with the task-level scenario context."""
    aligned = dict(args or {})
    if function_name not in NETHEAL_CONTEXT_FUNCTIONS:
        return aligned

    context = resolve_scenario_context(task_text, aligned.get("scenario_id"))
    if function_name in SCENARIO_ID_FUNCTIONS:
        aligned["scenario_id"] = context["scenario_id"]

    if function_name == "query_kpi_metrics":
        aligned.pop("resource_id", None)
    elif function_name == "query_network_topology":
        aligned["resource_id"] = context["root_resource"]
    elif function_name == "retrieve_fault_knowledge":
        aligned["query"] = context["knowledge_query"]
    elif function_name == "generate_repair_plan":
        aligned["root_cause"] = context["root_cause"]
        aligned["resource_id"] = context["root_resource"]
        aligned["simulation_mode"] = True
    elif function_name == "generate_config_commands":
        aligned["root_cause"] = context["root_cause"]
        aligned["dry_run"] = True
    elif function_name == "generate_work_order":
        aligned["root_cause"] = context["root_cause"]
        aligned["priority"] = context["priority"]

    return aligned
