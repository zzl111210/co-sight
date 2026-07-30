"""Reproducible evaluation for the synthetic NetHeal-Agent benchmark."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path
from typing import Any

from app.netheal.network_toolkit import NetworkToolkit


SEVERITY_ORDER = {"critical": 0, "major": 1, "warning": 2, "minor": 3}
SYMPTOM_BASELINE = {
    "UPF_CPU_HIGH": "UPF_OVERLOAD",
    "CELL_UNAVAILABLE": "RADIO_CELL_FAULT",
    "SLICE_PACKET_LOSS_HIGH": "TRANSPORT_QUALITY_FAULT",
}


def _decode(payload: str) -> dict[str, Any]:
    return json.loads(payload)


def _baseline_prediction(alarms: list[dict[str, str]]) -> str:
    """Traditional baseline: classify only the first highest-severity alarm."""
    if not alarms:
        return "UNKNOWN"
    first = sorted(alarms, key=lambda item: SEVERITY_ORDER.get(item["severity"], 99))[0]
    return SYMPTOM_BASELINE.get(first["alarm_type"], "UNKNOWN")


def evaluate(workspace_path: str | Path | None = None) -> dict[str, Any]:
    toolkit = NetworkToolkit(workspace_path=workspace_path)
    scenarios = toolkit._read_json("scenarios.json")["scenarios"]
    results = []
    runtimes = []
    compression_rates = []
    for scenario in scenarios:
        started = time.perf_counter()
        alarm_result = _decode(
            toolkit.read_alarm_events(scenario["site_id"], scenario["id"])
        )
        diagnosis = _decode(
            toolkit.diagnose_root_cause(scenario["site_id"], scenario["id"])
        )
        verification = _decode(
            toolkit.verify_recovery(scenario["site_id"], scenario["id"])
        )
        duration_ms = round((time.perf_counter() - started) * 1000, 3)
        runtimes.append(duration_ms)
        compression_rates.append(alarm_result["alarm_compression_rate_pct"])
        predicted = diagnosis["primary_diagnosis"]["root_cause"]
        baseline = _baseline_prediction(alarm_result["alarms"])
        results.append(
            {
                "scenario_id": scenario["id"],
                "ground_truth": scenario["ground_truth"],
                "netheal_prediction": predicted,
                "netheal_correct": predicted == scenario["ground_truth"],
                "baseline_prediction": baseline,
                "baseline_correct": baseline == scenario["ground_truth"],
                "confidence": diagnosis["primary_diagnosis"]["confidence"],
                "verification_passed": verification["passed"],
                "runtime_ms": duration_ms,
            }
        )
    total = len(results)
    report = {
        "benchmark": "NetHeal synthetic campus-5g v1",
        "data_notice": "全部结果来自仓库内可复现的仿真告警、KPI、拓扑和专家规则，不代表真实运营商生产指标。",
        "case_count": total,
        "netheal_root_cause_accuracy_pct": round(
            sum(item["netheal_correct"] for item in results) / total * 100, 2
        ),
        "single_alarm_baseline_accuracy_pct": round(
            sum(item["baseline_correct"] for item in results) / total * 100, 2
        ),
        "recovery_verification_pass_rate_pct": round(
            sum(item["verification_passed"] for item in results) / total * 100, 2
        ),
        "mean_alarm_compression_rate_pct": round(statistics.mean(compression_rates), 2),
        "mean_local_pipeline_runtime_ms": round(statistics.mean(runtimes), 3),
        "cases": results,
    }
    output_dir = toolkit.workspace_path / "netheal_outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "evaluation_results.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["output_path"] = str(output_path)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the NetHeal synthetic benchmark")
    parser.add_argument("--workspace", default=None)
    args = parser.parse_args()
    print(json.dumps(evaluate(args.workspace), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
