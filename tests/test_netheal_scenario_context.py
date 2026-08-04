from __future__ import annotations

import json
import tempfile
import unittest

from app.netheal.network_toolkit import NetworkToolkit
from app.netheal.scenario_context import (
    align_netheal_tool_args,
    infer_scenario_id,
    resolve_scenario_context,
)


def test_infers_all_demo_scenarios_from_natural_language():
    cases = {
        "请诊断 UPF-01 视频业务高时延": "upf-overload",
        "请分析 gNodeB-03 小区掉线和回传链路": "backhaul-link-down",
        "URLLC 切片资源不足导致工业控制 SLA 违约": "slice-capacity-shortage",
        "告警风暴叠加 UPF 过载与传输抖动复合故障": "alarm-storm-composite",
    }
    for question, expected in cases.items():
        assert infer_scenario_id(question) == expected


def test_task_text_overrides_conflicting_upf_default():
    context = resolve_scenario_context(
        "gNodeB-03 小区掉线故障根因定位与仿真恢复方案",
        "upf-overload",
    )
    assert context["scenario_id"] == "backhaul-link-down"
    assert context["resolution_source"] == "task_text"


def test_aligns_complete_backhaul_tool_chain():
    question = "请分析 gNodeB-03 小区掉线，检查回传链路并验证恢复"

    alarms = align_netheal_tool_args(
        "read_alarm_events", {"scenario_id": "upf-overload"}, question
    )
    assert alarms["scenario_id"] == "backhaul-link-down"

    topology = align_netheal_tool_args(
        "query_network_topology", {"resource_id": "UPF-01"}, question
    )
    assert topology["resource_id"] == "LINK-03"

    repair = align_netheal_tool_args(
        "generate_repair_plan", {"root_cause": "UPF_OVERLOAD"}, question
    )
    assert repair["root_cause"] == "BACKHAUL_LINK_DOWN"
    assert repair["resource_id"] == "LINK-03"
    assert repair["simulation_mode"] is True

    report = align_netheal_tool_args(
        "generate_incident_report", {"scenario_id": "upf-overload"}, question
    )
    assert report["scenario_id"] == "backhaul-link-down"


def test_preserves_explicit_scenario_for_ambiguous_task():
    context = resolve_scenario_context(
        "请执行一次故障诊断",
        "slice-capacity-shortage",
    )
    assert context["scenario_id"] == "slice-capacity-shortage"
    assert context["resolution_source"] == "tool_argument"


def test_wrong_upf_argument_generates_backhaul_report():
    question = "请分析 gNodeB-03 小区掉线，检查回传链路并验证恢复"
    args = align_netheal_tool_args(
        "generate_incident_report",
        {"scenario_id": "upf-overload"},
        question,
    )
    with tempfile.TemporaryDirectory() as workspace:
        result = json.loads(
            NetworkToolkit(workspace_path=workspace).generate_incident_report(**args)
        )
        assert result["scenario_id"] == "backhaul-link-down"
        assert result["diagnosis"]["root_cause"] == "BACKHAUL_LINK_DOWN"
        assert result["diagnosis"]["root_resource"] == "LINK-03"
        assert result["html_path"].endswith("NetHeal_Report_backhaul-link-down.html")


class ScenarioContextTests(unittest.TestCase):
    def test_inference(self):
        test_infers_all_demo_scenarios_from_natural_language()

    def test_conflicting_default(self):
        test_task_text_overrides_conflicting_upf_default()

    def test_complete_tool_chain(self):
        test_aligns_complete_backhaul_tool_chain()

    def test_explicit_scenario(self):
        test_preserves_explicit_scenario_for_ambiguous_task()

    def test_report_matches_question(self):
        test_wrong_upf_argument_generates_backhaul_report()


if __name__ == "__main__":
    unittest.main()
