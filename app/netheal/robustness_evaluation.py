"""Reproducible robustness benchmark for noisy and incomplete NMS evidence."""

from __future__ import annotations

import json
import random
from collections import defaultdict
from pathlib import Path
from typing import Any

from app.netheal.diagnosis_engine import EvidenceFusionEngine
from app.netheal.network_toolkit import NetworkToolkit


PROFILES: dict[str, dict[str, int]] = {
    "clean": {"drop_alarms": 0, "drop_kpis": 0, "noise_alarms": 0},
    "alarm_noise_25pct": {"drop_alarms": 0, "drop_kpis": 0, "noise_alarms": 2},
    "missing_alarm": {"drop_alarms": 1, "drop_kpis": 0, "noise_alarms": 0},
    "missing_kpi": {"drop_alarms": 0, "drop_kpis": 1, "noise_alarms": 0},
    "mixed_degradation": {"drop_alarms": 1, "drop_kpis": 1, "noise_alarms": 2},
    "severe_degradation": {"drop_alarms": 2, "drop_kpis": 2, "noise_alarms": 3},
}


def _unique(rows: list[dict[str, str]], field: str) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        value = row[field]
        if value not in seen:
            result.append(dict(row))
            seen.add(value)
    return result


def _perturb(
    signal_alarms: list[dict[str, str]],
    signal_kpis: list[dict[str, str]],
    noise_pool: list[dict[str, str]],
    profile: dict[str, int],
    rng: random.Random,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    alarms = [dict(row) for row in signal_alarms]
    kpis = [dict(row) for row in signal_kpis]
    rng.shuffle(alarms)
    rng.shuffle(kpis)

    alarm_keep = max(1, len(alarms) - profile["drop_alarms"])
    kpi_keep = max(1, len(kpis) - profile["drop_kpis"])
    alarms = alarms[:alarm_keep]
    kpis = kpis[:kpi_keep]

    if profile["noise_alarms"]:
        noise = rng.sample(
            noise_pool,
            min(profile["noise_alarms"], len(noise_pool)),
        )
        alarms.extend(dict(row) for row in noise)
        rng.shuffle(alarms)
    return alarms, kpis


def _single_alarm_baseline(
    alarms: list[dict[str, str]],
    rules: list[dict[str, Any]],
) -> str:
    if not alarms:
        return "UNKNOWN"
    alarm_type = alarms[0]["alarm_type"]
    for rule in rules:
        if alarm_type in rule["required_alarm_types"]:
            return str(rule["root_cause"])
    return "UNKNOWN"


def _round_pct(numerator: int, denominator: int) -> float:
    return round(numerator / denominator * 100, 2) if denominator else 0.0


def evaluate_robustness(
    output_dir: str | Path = "work_space/netheal_evaluation",
    seeds_per_profile: int = 20,
) -> dict[str, Any]:
    """Run deterministic evidence perturbations and write JSON/Markdown evidence."""
    toolkit = NetworkToolkit()
    engine = EvidenceFusionEngine()
    scenarios = toolkit._read_json("scenarios.json")["scenarios"]
    rules = toolkit._read_json("knowledge_base.json")["rules"]
    all_alarms = toolkit._read_csv("alarms.csv")
    all_kpis = toolkit._read_csv("kpi_timeseries.csv")
    results: list[dict[str, Any]] = []

    for profile_name, profile in PROFILES.items():
        for scenario in scenarios:
            scenario_id = scenario["id"]
            signal_alarms = _unique(
                [
                    row
                    for row in all_alarms
                    if row["scenario_id"] == scenario_id
                ],
                "alarm_type",
            )
            signal_kpis = _unique(
                [
                    row
                    for row in all_kpis
                    if row["scenario_id"] == scenario_id
                    and row["phase"] == "incident"
                ],
                "metric",
            )
            noise_pool = _unique(
                [
                    row
                    for row in all_alarms
                    if row["scenario_id"] != scenario_id
                ],
                "alarm_type",
            )

            for seed in range(seeds_per_profile):
                rng = random.Random(f"netheal:{profile_name}:{scenario_id}:{seed}")
                alarms, kpis = _perturb(
                    signal_alarms,
                    signal_kpis,
                    noise_pool,
                    profile,
                    rng,
                )
                ranked = engine.rank(alarms, kpis, rules)
                top = ranked[0]
                runner_up = ranked[1] if len(ranked) > 1 else {"confidence": 0.0}
                margin = round(top["confidence"] - runner_up["confidence"], 4)
                review_required = top["confidence"] < 0.6 or margin < 0.1
                expected = scenario["ground_truth"]
                results.append(
                    {
                        "profile": profile_name,
                        "scenario_id": scenario_id,
                        "seed": seed,
                        "expected": expected,
                        "predicted": top["root_cause"],
                        "correct": top["root_cause"] == expected,
                        "confidence": top["confidence"],
                        "evidence_coverage": top["evidence_coverage"],
                        "margin": margin,
                        "review_required": review_required,
                        "baseline_predicted": _single_alarm_baseline(alarms, rules),
                        "baseline_correct": (
                            _single_alarm_baseline(alarms, rules) == expected
                        ),
                        "alarm_count": len(alarms),
                        "kpi_count": len(kpis),
                    }
                )

    by_profile: dict[str, Any] = {}
    for profile_name in PROFILES:
        rows = [row for row in results if row["profile"] == profile_name]
        auto_rows = [row for row in rows if not row["review_required"]]
        by_profile[profile_name] = {
            "case_count": len(rows),
            "netheal_accuracy_pct": _round_pct(
                sum(row["correct"] for row in rows),
                len(rows),
            ),
            "single_alarm_baseline_accuracy_pct": _round_pct(
                sum(row["baseline_correct"] for row in rows),
                len(rows),
            ),
            "human_review_rate_pct": _round_pct(
                sum(row["review_required"] for row in rows),
                len(rows),
            ),
            "auto_decision_accuracy_pct": _round_pct(
                sum(row["correct"] for row in auto_rows),
                len(auto_rows),
            ),
            "mean_confidence_pct": round(
                sum(row["confidence"] for row in rows) / len(rows) * 100,
                2,
            ),
        }

    auto_results = [row for row in results if not row["review_required"]]
    summary = {
        "benchmark_type": "synthetic_evidence_robustness",
        "dataset_notice": (
            "指标来自本仓库模拟网管数据的可复现实验，不代表真实运营商生产网络。"
        ),
        "profiles": list(PROFILES),
        "scenario_count": len(scenarios),
        "seeds_per_profile": seeds_per_profile,
        "case_count": len(results),
        "netheal_accuracy_pct": _round_pct(
            sum(row["correct"] for row in results),
            len(results),
        ),
        "single_alarm_baseline_accuracy_pct": _round_pct(
            sum(row["baseline_correct"] for row in results),
            len(results),
        ),
        "human_review_rate_pct": _round_pct(
            sum(row["review_required"] for row in results),
            len(results),
        ),
        "auto_decision_accuracy_pct": _round_pct(
            sum(row["correct"] for row in auto_results),
            len(auto_results),
        ),
        "by_profile": by_profile,
    }

    target = Path(output_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    json_path = target / "robustness_evaluation.json"
    markdown_path = target / "robustness_evaluation.md"
    json_path.write_text(
        json.dumps({"summary": summary, "cases": results}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(summary), encoding="utf-8")
    return {
        **summary,
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }


def _render_markdown(summary: dict[str, Any]) -> str:
    rows = []
    for profile, values in summary["by_profile"].items():
        rows.append(
            "| {profile} | {case_count} | {netheal_accuracy_pct:.2f}% | "
            "{single_alarm_baseline_accuracy_pct:.2f}% | "
            "{human_review_rate_pct:.2f}% | {auto_decision_accuracy_pct:.2f}% |".format(
                profile=profile,
                **values,
            )
        )
    return "\n".join(
        [
            "# NetHeal-Agent 鲁棒性评测",
            "",
            f"> {summary['dataset_notice']}",
            "",
            "| 扰动配置 | 样本数 | NetHeal 准确率 | 单告警基线 | 人工复核率 | 自动决策准确率 |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
            *rows,
            "",
            "## 总体结果",
            "",
            f"- 样本数：{summary['case_count']}",
            f"- NetHeal 根因定位准确率：{summary['netheal_accuracy_pct']:.2f}%",
            f"- 单告警基线准确率：{summary['single_alarm_baseline_accuracy_pct']:.2f}%",
            f"- 低置信度人工复核率：{summary['human_review_rate_pct']:.2f}%",
            f"- 自动决策子集准确率：{summary['auto_decision_accuracy_pct']:.2f}%",
            "",
            "人工复核率表示系统主动识别证据不足的比例，不等同于诊断失败。",
        ]
    )


if __name__ == "__main__":
    print(json.dumps(evaluate_robustness(), ensure_ascii=False, indent=2))
