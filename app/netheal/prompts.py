"""Scenario-specific prompt guidance without replacing Co-Sight prompts."""

from __future__ import annotations

from app.netheal.scenario_context import resolve_scenario_context


NETHEAL_KEYWORDS = (
    "netheal",
    "campus-5g",
    "5g校园",
    "5g 校园",
    "5g专网",
    "5g 专网",
    "upf",
    "gnodeb",
    "小区掉线",
    "基站掉线",
    "回传链路",
    "网络切片",
    "urllc",
    "告警风暴",
)


def is_netheal_request(question: str) -> bool:
    normalized = (question or "").lower()
    return any(keyword in normalized for keyword in NETHEAL_KEYWORDS)


def build_netheal_planning_guidance(question: str) -> str:
    if not is_netheal_request(question):
        return ""
    context = resolve_scenario_context(question)
    return f"""

# NetHeal-Agent 场景规划约束
本次任务唯一场景ID：{context['scenario_id']}；预期根因编码：{context['root_cause']}；根网元：{context['root_resource']}。
所有 NetHeal 工具调用必须携带或遵循该场景上下文，禁止在同一任务中切换到其他测试场景。
这是5G专网智能运维任务。使用 create_plan 创建以下8个步骤，并保留方括号中的专业智能体角色：
1. [告警解析智能体] 读取并关联压缩告警
2. [根因定位智能体] 查询故障期KPI与阈值违例
3. [拓扑关联智能体] 查询根网元邻接与下游影响
4. [根因定位智能体] 检索专家规则与历史案例
5. [根因定位智能体] 融合四路证据并排序根因
6. [修复决策智能体] 生成风险分级修复方案、仿真命令和工单
7. [验证评估智能体] 比较修复前后KPI；未通过则回溯根因定位，最多2次
8. [验证评估智能体] 生成Markdown与HTML故障闭环报告

依赖关系必须体现DAG并发：步骤0、1、2、3无依赖；步骤4依赖[0,1,2,3]；
步骤5依赖[4]；步骤6依赖[5]；步骤7依赖[6]。
不要把四路取证合并成一个步骤。生产配置变更必须保留人工审批分支，自动执行仅限仿真。
"""


def build_netheal_actor_guidance(question: str, current_step: str) -> str:
    if not is_netheal_request(question):
        return ""
    context = resolve_scenario_context(question)
    return f"""

# NetHeal-Agent 当前专业角色约束
当前步骤：{current_step}
- 场景锁定：scenario_id={context['scenario_id']}，root_cause={context['root_cause']}，root_resource={context['root_resource']}。
- 每个工具的参数和输出都必须与上述场景一致；发现历史默认值或其他场景时，以当前任务场景为准。
- 只使用 NetHeal 专用工具返回的结构化证据，不使用互联网搜索，不编造网管数据。
- 告警步骤调用 read_alarm_events；KPI步骤调用 query_kpi_metrics；拓扑步骤调用 query_network_topology；
  知识步骤调用 retrieve_fault_knowledge；根因步骤调用 diagnose_root_cause。
- 修复步骤至少调用 generate_repair_plan，并调用 generate_config_commands 与 generate_work_order 展示安全分支。
- 验证步骤调用 verify_recovery；若 passed=false，备注中明确要求回溯根因定位。
- 最终报告步骤调用 generate_incident_report。
- 中间步骤无需 file_saver；工具结果已包含来源和证据ID。完成后用 mark_step 保存结构化结论。
- 真实网元配置不得自动执行；所有配置命令必须保持 dry_run 或 simulation_mode。
"""
