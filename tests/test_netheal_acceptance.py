from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.netheal.acceptance_runner import run_acceptance


class NetHealAcceptanceTests(unittest.TestCase):
    def test_all_acceptance_cases_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            report = run_acceptance(Path(temp_dir))

            self.assertTrue(report["summary"]["all_passed"])
            self.assertEqual(report["summary"]["total"], 5)
            self.assertEqual(
                {item["test_case_id"] for item in report["results"]},
                {"TC-01", "TC-02", "TC-03", "TC-04", "TC-05"},
            )
            self.assertTrue(Path(report["artifacts"]["json"]).is_file())
            self.assertTrue(Path(report["artifacts"]["markdown"]).is_file())


if __name__ == "__main__":
    unittest.main()
