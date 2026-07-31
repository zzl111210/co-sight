"""Deterministic evidence-fusion engine used by NetHeal tools and benchmarks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class EvidenceWeights:
    alarm: float = 0.55
    kpi: float = 0.45
    cross_source_bonus: float = 0.05


class EvidenceFusionEngine:
    """Rank fault rules while preserving an explainable evidence breakdown."""

    def __init__(self, weights: EvidenceWeights | None = None):
        self.weights = weights or EvidenceWeights()

    @staticmethod
    def _number(value: Any) -> float:
        return float(value)

    @staticmethod
    def _matches(actual: float, operator: str, expected: float) -> bool:
        operations = {
            ">": actual > expected,
            ">=": actual >= expected,
            "<": actual < expected,
            "<=": actual <= expected,
            "==": actual == expected,
        }
        if operator not in operations:
            raise ValueError(f"Unsupported KPI operator: {operator}")
        return operations[operator]

    @staticmethod
    def _root_resource(
        rule: dict[str, Any],
        alarms: list[dict[str, Any]],
        matched_kpis: list[dict[str, Any]],
    ) -> str:
        root_alarm_type = rule.get("root_alarm_type")
        if root_alarm_type:
            for alarm in alarms:
                if alarm.get("alarm_type") == root_alarm_type:
                    return str(alarm.get("resource_id", "unknown"))

        for alarm_type in rule.get("required_alarm_types", []):
            for alarm in alarms:
                if alarm.get("alarm_type") == alarm_type:
                    return str(alarm.get("resource_id", "unknown"))
        for item in matched_kpis:
            evidence = item.get("evidence", [])
            if evidence:
                return str(evidence[0].get("resource_id", "unknown"))
        return "unknown"

    def rank(
        self,
        alarms: Iterable[dict[str, Any]],
        kpis: Iterable[dict[str, Any]],
        rules: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        alarm_rows = list(alarms)
        kpi_rows = list(kpis)
        alarm_types = {row.get("alarm_type") for row in alarm_rows}
        candidates: list[dict[str, Any]] = []

        for rule in rules:
            required_alarms = list(rule.get("required_alarm_types", []))
            conditions = list(rule.get("kpi_conditions", []))
            matched_alarm_types = [
                alarm_type
                for alarm_type in required_alarms
                if alarm_type in alarm_types
            ]
            matched_kpis: list[dict[str, Any]] = []
            for condition in conditions:
                matches = [
                    row
                    for row in kpi_rows
                    if row.get("metric") == condition["metric"]
                    and self._matches(
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

            alarm_coverage = (
                len(matched_alarm_types) / len(required_alarms)
                if required_alarms
                else 0.0
            )
            kpi_coverage = (
                len(matched_kpis) / len(conditions)
                if conditions
                else 0.0
            )
            available_alarm = bool(alarm_rows and required_alarms)
            available_kpi = bool(kpi_rows and conditions)
            active_weight = (
                (self.weights.alarm if available_alarm else 0.0)
                + (self.weights.kpi if available_kpi else 0.0)
            )
            weighted_score = (
                (
                    alarm_coverage
                    * (self.weights.alarm if available_alarm else 0.0)
                    + kpi_coverage
                    * (self.weights.kpi if available_kpi else 0.0)
                )
                / active_weight
                if active_weight
                else 0.0
            )
            if alarm_coverage > 0 and kpi_coverage > 0:
                weighted_score += self.weights.cross_source_bonus

            evidence_expected = len(required_alarms) + len(conditions)
            evidence_matched = len(matched_alarm_types) + len(matched_kpis)
            candidates.append(
                {
                    "root_cause": rule["root_cause"],
                    "title": rule["title"],
                    "root_resource": self._root_resource(
                        rule,
                        alarm_rows,
                        matched_kpis,
                    ),
                    "confidence": round(min(weighted_score, 1.0), 4),
                    "evidence_coverage": round(
                        evidence_matched / evidence_expected
                        if evidence_expected
                        else 0.0,
                        4,
                    ),
                    "alarm_coverage": round(alarm_coverage, 4),
                    "kpi_coverage": round(kpi_coverage, 4),
                    "matched_alarm_types": matched_alarm_types,
                    "matched_kpis": matched_kpis,
                    "rule_id": rule["id"],
                }
            )

        candidates.sort(
            key=lambda item: (
                item["confidence"],
                item["evidence_coverage"],
                len(item["matched_alarm_types"]),
                len(item["matched_kpis"]),
            ),
            reverse=True,
        )
        return candidates
