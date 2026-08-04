"""Co-Sight skill declarations for NetHeal-Agent tools."""

from __future__ import annotations

from app.agent_dispatcher.infrastructure.entity.SkillFunction import SkillFunction


def _property(en: str, zh: str, value_type: str = "string", default=None) -> dict:
    result = {"type": value_type, "en": en, "zh": zh}
    if default is not None:
        result["default"] = default
    return result


def _skill(
    name: str,
    display_zh: str,
    display_en: str,
    description_zh: str,
    description_en: str,
    parameters: dict,
) -> dict:
    return {
        "skill_name": name,
        "skill_type": "function",
        "display_name_zh": display_zh,
        "display_name_en": display_en,
        "description_zh": description_zh,
        "description_en": description_en,
        "semantic_apis": ["api_5g_network_operations"],
        "function": SkillFunction(
            id=f"netheal-{name}",
            name=f"app.netheal.network_toolkit.NetworkToolkit.{name}",
            description_zh=description_zh,
            description_en=description_en,
            parameters=parameters,
        ),
    }


def netheal_skills() -> list[dict]:
    site_and_scenario = {
        "type": "object",
        "properties": {
            "site_id": _property("5G private-network site ID", "5G专网站点ID", default="campus-5g"),
            "scenario_id": _property("Required fault scenario ID: upf-overload, backhaul-link-down, slice-capacity-shortage, or alarm-storm-composite", "必填故障场景ID：upf-overload、backhaul-link-down、slice-capacity-shortage 或 alarm-storm-composite"),
        },
        "required": ["scenario_id"],
    }
    return [
        _skill(
            "read_alarm_events",
            "读取并关联告警",
            "Read and Correlate Alarms",
            "读取网管告警，去重并按根事件进行关联压缩。",
            "Read NMS alarms, deduplicate them, and correlate derived alarms.",
            {
                "type": "object",
                "properties": {
                    **site_and_scenario["properties"],
                    "severity": _property("Optional severity filter", "可选告警级别过滤"),
                },
                "required": ["scenario_id"],
            },
        ),
        _skill(
            "query_kpi_metrics",
            "查询网络KPI",
            "Query Network KPIs",
            "查询时延、丢包率、CPU、吞吐量等KPI及阈值违例。",
            "Query latency, packet loss, CPU, throughput, and threshold violations.",
            {
                "type": "object",
                "properties": {
                    **site_and_scenario["properties"],
                    "phase": _property("baseline, incident, post_repair, or all", "基线、故障、修复后或全部阶段", default="incident"),
                    "resource_id": _property("Optional resource filter", "可选网元过滤"),
                },
                "required": ["scenario_id"],
            },
        ),
        _skill(
            "query_network_topology",
            "查询网络拓扑",
            "Query Network Topology",
            "查询网元邻接关系、承载关系及下游业务影响范围。",
            "Query adjacency, bearer relationships, and downstream service impact.",
            {
                "type": "object",
                "properties": {
                    "site_id": site_and_scenario["properties"]["site_id"],
                    "resource_id": _property("Focus network resource", "关注网元"),
                },
                "required": ["resource_id"],
            },
        ),
        _skill(
            "retrieve_fault_knowledge",
            "检索故障知识",
            "Retrieve Fault Knowledge",
            "从专家规则与历史工单中检索相似故障和处置经验。",
            "Retrieve similar faults and remediation experience from expert rules and cases.",
            {
                "type": "object",
                "properties": {
                    "query": _property("Fault symptoms and resources", "故障现象与网元关键词"),
                    "top_k": _property("Maximum returned rules", "最多返回规则数", "integer", 3),
                },
                "required": ["query"],
            },
        ),
        _skill(
            "diagnose_root_cause",
            "定位故障根因",
            "Diagnose Root Cause",
            "融合告警、KPI、拓扑和知识规则，对候选根因进行排序并输出证据链。",
            "Fuse alarms, KPIs, topology, and rules to rank root causes with evidence.",
            site_and_scenario,
        ),
        _skill(
            "generate_repair_plan",
            "生成修复方案",
            "Generate Repair Plan",
            "根据根因生成带风险分级、审批策略和回滚动作的修复方案。",
            "Generate a risk-graded repair plan with approval and rollback controls.",
            {
                "type": "object",
                "properties": {
                    "root_cause": _property("Root-cause code", "根因编码"),
                    "resource_id": _property("Root resource ID", "根网元ID"),
                    "simulation_mode": _property("Whether execution is simulated", "是否为仿真执行", "boolean", True),
                },
                "required": ["root_cause", "resource_id"],
            },
        ),
        _skill(
            "generate_config_commands",
            "生成配置命令",
            "Generate Configuration Commands",
            "生成厂商中立、可审计且默认不执行的仿真配置命令。",
            "Generate vendor-neutral, auditable, dry-run configuration commands.",
            {
                "type": "object",
                "properties": {
                    "root_cause": _property("Root-cause code", "根因编码"),
                    "dry_run": _property("Keep commands in dry-run mode", "保持命令仅仿真", "boolean", True),
                },
                "required": ["root_cause"],
            },
        ),
        _skill(
            "generate_work_order",
            "生成运维工单",
            "Generate Work Order",
            "生成包含根因、影响范围、修复动作和审批状态的结构化工单。",
            "Generate a structured work order with cause, impact, actions, and approval state.",
            {
                "type": "object",
                "properties": {
                    "scenario_id": site_and_scenario["properties"]["scenario_id"],
                    "root_cause": _property("Root-cause code", "根因编码"),
                    "priority": _property("Work-order priority", "工单优先级", default="P2"),
                },
                "required": ["scenario_id", "root_cause"],
            },
        ),
        _skill(
            "verify_recovery",
            "验证恢复效果",
            "Verify Recovery",
            "比较修复前后KPI与SLA，判断是否恢复并决定闭环或回溯。",
            "Compare pre/post KPIs with SLAs and decide closure or diagnosis retry.",
            site_and_scenario,
        ),
        _skill(
            "generate_incident_report",
            "生成故障闭环报告",
            "Generate Incident Report",
            "生成包含证据链、根因、修复命令和KPI对比的Markdown与HTML报告。",
            "Generate Markdown and HTML reports with evidence, cause, commands, and KPI comparison.",
            site_and_scenario,
        ),
    ]
