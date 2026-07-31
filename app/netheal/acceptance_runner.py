"""Executable acceptance suite for the NetHeal-Agent demonstration system."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from app.netheal.service import NetHealService


def _check(name: str, actual: Any, expected: Any) -> dict[str, Any]:
    return {
        "name": name,
        "passed": actual == expected,
        "actual": actual,
        "expected": expected,
    }


def _predicate_check(
    name: str,
    actual: Any,
    predicate: Callable[[Any], bool],
    expected: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "passed": bool(predicate(actual)),
        "actual": actual,
        "expected": expected,
    }


def _run_closed_loop_case(
    service: NetHealService,
    scenario: dict[str, Any],
) -> dict[str, Any]:
    started = time.perf_counter()
    checks: list[dict[str, Any]] = []
    error: str | None = None
    incident_id: str | None = None

    try:
        result = service.run_demo(
            scenario["id"],
            actor="acceptance-runner",
            role="approver",
        )
        incident = result["incident"]
        incident_id = incident["id"]
        repair = incident.get("repair", {})
        commands = repair.get("commands", {})
        work_order = repair.get("work_order", {})
        report = repair.get("report", {})
        event_types = {event.get("event_type") for event in result.get("events", [])}

        checks.extend(
            [
                _check("闭环状态", incident.get("status"), "closed"),
                _check(
                    "根因编码",
                    incident.get("root_cause"),
                    scenario["ground_truth"],
                ),
                _check(
                    "根网元",
                    incident.get("root_resource"),
                    scenario["root_resource"],
                ),
                _check(
                    "恢复验证",
                    incident.get("verification_passed"),
                    True,
                ),
                _predicate_check(
                    "诊断置信度",
                    incident.get("confidence"),
                    lambda value: value is not None and float(value) >= 0.8,
                    ">= 0.8",
                ),
                _predicate_check(
                    "仿真配置命令",
                    commands.get("command_count", 0),
                    lambda value: int(value) >= 1 and commands.get("dry_run") is True,
                    "至少 1 条且 dry_run=true",
                ),
                _predicate_check(
                    "工单文件",
                    work_order.get("output_path"),
                    lambda value: bool(value) and Path(value).is_file(),
                    "文件存在",
                ),
                _predicate_check(
                    "Markdown闭环报告",
                    report.get("markdown_path"),
                    lambda value: bool(value) and Path(value).is_file(),
                    "文件存在",
                ),
                _predicate_check(
                    "HTML闭环报告",
                    report.get("html_path"),
                    lambda value: bool(value) and Path(value).is_file(),
                    "文件存在",
                ),
                _predicate_check(
                    "关键生命周期事件",
                    sorted(event_types),
                    lambda value: {
                        "diagnosis_completed",
                        "repair_executed",
                        "status_changed",
                    }
                    <= set(value),
                    "包含诊断、修复和状态迁移事件",
                ),
            ]
        )
    except Exception as exc:  # pragma: no cover - surfaced in the report
        error = f"{type(exc).__name__}: {exc}"

    return {
        "test_case_id": scenario["test_case_id"],
        "scenario_id": scenario["id"],
        "title": scenario["title"],
        "category": "端到端故障闭环",
        "passed": error is None and all(item["passed"] for item in checks),
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "incident_id": incident_id,
        "checks": checks,
        "error": error,
    }


def _run_permission_case(service: NetHealService) -> dict[str, Any]:
    started = time.perf_counter()
    denied = False
    error: str | None = None
    try:
        service.reset_demo("acceptance-viewer", "viewer")
    except PermissionError:
        denied = True
    except Exception as exc:  # pragma: no cover - surfaced in the report
        error = f"{type(exc).__name__}: {exc}"

    checks = [_check("只读角色禁止重置系统", denied, True)]
    return {
        "test_case_id": "TC-04",
        "scenario_id": "rbac-viewer-denied",
        "title": "RBAC越权操作拦截",
        "category": "安全控制",
        "passed": error is None and all(item["passed"] for item in checks),
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "incident_id": None,
        "checks": checks,
        "error": error,
    }


def _run_state_guard_case(
    service: NetHealService,
    closed_incident_id: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    rejected = False
    error: str | None = None
    try:
        service.verify(
            closed_incident_id,
            actor="acceptance-operator",
            role="operator",
        )
    except ValueError:
        rejected = True
    except Exception as exc:  # pragma: no cover - surfaced in the report
        error = f"{type(exc).__name__}: {exc}"

    checks = [_check("已闭环事件禁止重复验证", rejected, True)]
    return {
        "test_case_id": "TC-05",
        "scenario_id": "lifecycle-transition-guard",
        "title": "事件状态机非法跳转拦截",
        "category": "可靠性控制",
        "passed": error is None and all(item["passed"] for item in checks),
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        "incident_id": closed_incident_id,
        "checks": checks,
        "error": error,
    }


def _render_markdown(report: dict[str, Any]) -> str:
    rows = "\n".join(
        "| {case} | {title} | {category} | {status} | {duration:.2f} ms |".format(
            case=item["test_case_id"],
            title=item["title"],
            category=item["category"],
            status="通过" if item["passed"] else "失败",
            duration=item["duration_ms"],
        )
        for item in report["results"]
    )
    failure_details = []
    for item in report["results"]:
        failed_checks = [check for check in item["checks"] if not check["passed"]]
        if not failed_checks and not item["error"]:
            continue
        failure_details.append(f"### {item['test_case_id']} {item['title']}")
        if item["error"]:
            failure_details.append(f"- 异常：`{item['error']}`")
        for check in failed_checks:
            failure_details.append(
                f"- {check['name']}：实际 `{check['actual']}`，预期 `{check['expected']}`"
            )

    details = "\n".join(failure_details) or "无失败项。"
    summary = report["summary"]
    return f"""# NetHeal-Agent 可执行性验收报告

- 执行时间：{report['generated_at']}
- 总用例：{summary['total']}
- 通过：{summary['passed']}
- 失败：{summary['failed']}
- 总体结论：{'通过' if summary['all_passed'] else '不通过'}
- 运行模式：仿真闭环，不写入真实网络

| 编号 | 测试用例 | 类别 | 结果 | 耗时 |
|---|---|---|---|---:|
{rows}

## 失败详情

{details}
"""


def run_acceptance(
    output_dir: str | Path = "work_space/netheal_acceptance",
    scenario_ids: list[str] | None = None,
    include_safety_cases: bool = True,
) -> dict[str, Any]:
    output_path = Path(output_dir).resolve()
    output_path.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="netheal-acceptance-") as temp_dir:
        service = NetHealService(
            workspace_path=output_path / "runtime",
            database_path=Path(temp_dir) / "netheal.db",
        )
        scenarios = service.scenarios()
        selected_ids = set(scenario_ids or [item["id"] for item in scenarios])
        selected = [item for item in scenarios if item["id"] in selected_ids]
        unknown = selected_ids - {item["id"] for item in selected}
        if unknown:
            raise ValueError(f"Unknown scenario id(s): {', '.join(sorted(unknown))}")

        results = [_run_closed_loop_case(service, scenario) for scenario in selected]
        if include_safety_cases:
            results.append(_run_permission_case(service))
            closed_ids = [
                item["incident_id"]
                for item in results
                if item["category"] == "端到端故障闭环"
                and item["passed"]
                and item["incident_id"]
            ]
            if closed_ids:
                results.append(_run_state_guard_case(service, closed_ids[0]))

    passed = sum(item["passed"] for item in results)
    report = {
        "project": "NetHeal-Agent",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(
            timespec="seconds"
        ),
        "simulation_mode": True,
        "real_network_write_enabled": False,
        "summary": {
            "total": len(results),
            "passed": passed,
            "failed": len(results) - passed,
            "all_passed": passed == len(results),
        },
        "results": results,
    }
    json_path = output_path / "acceptance_report.json"
    markdown_path = output_path / "acceptance_report.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(_render_markdown(report), encoding="utf-8")
    report["artifacts"] = {
        "json": str(json_path),
        "markdown": str(markdown_path),
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run repeatable NetHeal-Agent executable acceptance cases"
    )
    parser.add_argument(
        "--scenario",
        action="append",
        dest="scenarios",
        help="Run one scenario id; repeat the option to select multiple scenarios",
    )
    parser.add_argument(
        "--output-dir",
        default="work_space/netheal_acceptance",
        help="Directory for JSON, Markdown, work orders, and closure reports",
    )
    parser.add_argument(
        "--skip-safety-cases",
        action="store_true",
        help="Only run the selected end-to-end fault scenarios",
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON result")
    args = parser.parse_args()

    report = run_acceptance(
        output_dir=args.output_dir,
        scenario_ids=args.scenarios,
        include_safety_cases=not args.skip_safety_cases,
    )
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("NetHeal-Agent 可执行性验收")
        for item in report["results"]:
            status = "PASS" if item["passed"] else "FAIL"
            print(
                f"[{status}] {item['test_case_id']} {item['title']} "
                f"({item['duration_ms']:.2f} ms)"
            )
        summary = report["summary"]
        print(
            f"结果：{summary['passed']}/{summary['total']} 通过；"
            f"报告：{report['artifacts']['markdown']}"
        )
    sys.exit(0 if report["summary"]["all_passed"] else 1)


if __name__ == "__main__":
    main()
