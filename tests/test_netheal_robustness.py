from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.netheal.robustness_evaluation import evaluate_robustness


class NetHealRobustnessTests(unittest.TestCase):
    def test_noisy_and_missing_evidence_benchmark(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result = evaluate_robustness(temp_dir, seeds_per_profile=2)

            self.assertEqual(result["case_count"], 36)
            self.assertGreater(
                result["netheal_accuracy_pct"],
                result["single_alarm_baseline_accuracy_pct"],
            )
            self.assertGreaterEqual(
                result["auto_decision_accuracy_pct"],
                result["netheal_accuracy_pct"],
            )
            self.assertTrue(Path(result["json_path"]).is_file())
            self.assertTrue(Path(result["markdown_path"]).is_file())
            self.assertIn("severe_degradation", result["by_profile"])


if __name__ == "__main__":
    unittest.main()
