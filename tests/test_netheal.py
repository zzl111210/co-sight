from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.netheal.evaluation import evaluate
from app.netheal.network_toolkit import NetworkToolkit
from app.netheal.scenario_runner import run_scenario
from app.netheal.skills import netheal_skills


class NetworkToolkitTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name)
        self.toolkit = NetworkToolkit(workspace_path=self.workspace)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_upf_alarm_correlation_and_root_cause(self) -> None:
        alarms = json.loads(self.toolkit.read_alarm_events())
        diagnosis = json.loads(self.toolkit.diagnose_root_cause())
        self.assertEqual(alarms["raw_alarm_count"], 6)
        self.assertEqual(alarms["correlated_incident_count"], 1)
        self.assertEqual(diagnosis["primary_diagnosis"]["root_cause"], "UPF_OVERLOAD")
        self.assertEqual(diagnosis["primary_diagnosis"]["confidence"], 1.0)

    def test_all_scenarios_match_ground_truth_and_recover(self) -> None:
        scenarios = self.toolkit._read_json("scenarios.json")["scenarios"]
        for scenario in scenarios:
            with self.subTest(scenario=scenario["id"]):
                diagnosis = json.loads(
                    self.toolkit.diagnose_root_cause(scenario["site_id"], scenario["id"])
                )
                verification = json.loads(
                    self.toolkit.verify_recovery(scenario["site_id"], scenario["id"])
                )
                self.assertEqual(
                    diagnosis["primary_diagnosis"]["root_cause"],
                    scenario["ground_truth"],
                )
                self.assertEqual(
                    diagnosis["primary_diagnosis"]["root_resource"],
                    scenario["root_resource"],
                )
                self.assertTrue(verification["passed"])

    def test_report_and_work_order_are_written(self) -> None:
        report = json.loads(self.toolkit.generate_incident_report())
        work_order = json.loads(self.toolkit.generate_work_order())
        self.assertTrue(Path(report["markdown_path"]).is_file())
        self.assertTrue(Path(report["html_path"]).is_file())
        self.assertTrue(Path(work_order["output_path"]).is_file())

    def test_skill_registration_declares_ten_tools(self) -> None:
        skills = netheal_skills()
        self.assertEqual(len(skills), 10)
        self.assertEqual(len({skill["skill_name"] for skill in skills}), 10)

    def test_runner_and_evaluation(self) -> None:
        result = run_scenario(workspace_path=self.workspace)
        benchmark = evaluate(self.workspace)
        self.assertTrue(result["verification"]["passed"])
        self.assertEqual(benchmark["netheal_root_cause_accuracy_pct"], 100.0)
        self.assertGreater(
            benchmark["netheal_root_cause_accuracy_pct"],
            benchmark["single_alarm_baseline_accuracy_pct"],
        )


if __name__ == "__main__":
    unittest.main()
