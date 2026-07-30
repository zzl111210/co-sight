"""One-command deterministic demonstration of the NetHeal-Agent workflow."""

from __future__ import annotations

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

from app.netheal.network_toolkit import NetworkToolkit


def _decode(payload: str) -> dict[str, Any]:
    return json.loads(payload)


def run_scenario(
    scenario_id: str = "upf-overload",
    site_id: str = "campus-5g",
    workspace_path: str | Path | None = None,
    max_retries: int = 2,
) -> dict[str, Any]:
    """Run the evidence, diagnosis, repair, verification, and report DAG."""
    toolkit = NetworkToolkit(workspace_path=workspace_path)
    started = time.perf_counter()
    parallel_calls: dict[str, Callable[[], str]] = {
        "alarm_agent": lambda: toolkit.read_alarm_events(site_id, scenario_id),
        "kpi_probe": lambda: toolkit.query_kpi_metrics(site_id, scenario_id, "incident"),
        "topology_agent": lambda: toolkit.query_network_topology(
            site_id, toolkit._scenario(scenario_id)["root_resource"]
        ),
        "knowledge_probe": lambda: toolkit.retrieve_fault_knowledge(
            toolkit._scenario(scenario_id)["title"]
        ),
    }
    evidence: dict[str, Any] = {}
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {name: executor.submit(call) for name, call in parallel_calls.items()}
        for name, future in futures.items():
            evidence[name] = _decode(future.result())

    diagnosis = _decode(toolkit.diagnose_root_cause(site_id, scenario_id))
    primary = diagnosis["primary_diagnosis"]
    repair = _decode(
        toolkit.generate_repair_plan(
            primary["root_cause"],
            primary["root_resource"],
            simulation_mode=True,
        )
    )
    commands = _decode(toolkit.generate_config_commands(primary["root_cause"], dry_run=True))
    work_order = _decode(
        toolkit.generate_work_order(scenario_id, primary["root_cause"], priority="P2")
    )

    retry_count = 0
    verification = _decode(toolkit.verify_recovery(site_id, scenario_id))
    while not verification["passed"] and retry_count < max_retries:
        retry_count += 1
        diagnosis = _decode(toolkit.diagnose_root_cause(site_id, scenario_id))
        verification = _decode(toolkit.verify_recovery(site_id, scenario_id))

    report = _decode(toolkit.generate_incident_report(site_id, scenario_id))
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    return {
        "project": "NetHeal-Agent",
        "workflow": "parallel evidence -> diagnosis -> risk branch -> verification -> report",
        "site_id": site_id,
        "scenario_id": scenario_id,
        "duration_ms": duration_ms,
        "parallel_agents": list(parallel_calls),
        "evidence": evidence,
        "diagnosis": diagnosis,
        "repair": repair,
        "commands": commands,
        "work_order": work_order,
        "verification": verification,
        "retry_count": retry_count,
        "report": report,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a NetHeal-Agent 5G fault scenario")
    parser.add_argument("--scenario", default="upf-overload")
    parser.add_argument("--site", default="campus-5g")
    parser.add_argument("--workspace", default=None)
    args = parser.parse_args()
    result = run_scenario(args.scenario, args.site, args.workspace)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
