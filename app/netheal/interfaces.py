"""Abstract repository and executor interfaces for production-grade deployment.

These interfaces decouple the NetHeal-Agent toolkit from its data sources and
execution targets. The default implementations read from local synthetic files
and simulate changes in dry-run mode. Production adapters must implement
authentication, idempotency, timeouts, rollbacks, and audit trails.

See: CODEX_HANDOFF.md §17.6, §19.2
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


# ---------------------------------------------------------------------------
# Shared value objects
# ---------------------------------------------------------------------------


@dataclass
class AlarmRecord:
    """Normalised alarm event from any upstream source."""

    event_id: str
    timestamp: str
    site_id: str
    scenario_id: str
    severity: str
    source: str
    resource_id: str
    alarm_type: str
    metric: str
    value: float
    threshold: float
    description: str
    correlation_group: str


@dataclass
class KpiRecord:
    """Normalised KPI measurement from any upstream source."""

    timestamp: str
    site_id: str
    scenario_id: str
    phase: str  # baseline | incident | post_repair
    resource_id: str
    metric: str
    value: float
    unit: str
    threshold: float
    status: str  # normal | abnormal


@dataclass
class TopologyNode:
    """A network element in the topology graph."""

    id: str
    type: str
    name: str = ""
    health: str = "normal"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TopologyLink:
    """A connection between two network elements."""

    source: str
    target: str
    status: str = "healthy"
    relation: str = "connected_to"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TopologyGraph:
    """Full topology snapshot."""

    nodes: list[TopologyNode] = field(default_factory=list)
    links: list[TopologyLink] = field(default_factory=list)
    site_id: str = ""


@dataclass
class KnowledgeRule:
    """Expert rule for fault diagnosis."""

    id: str
    root_cause: str
    title: str
    keywords: list[str] = field(default_factory=list)
    root_alarm_type: str = ""
    required_alarm_types: list[str] = field(default_factory=list)
    kpi_conditions: list[dict[str, Any]] = field(default_factory=list)
    affected_resource_type: str = ""
    risk_level: str = "medium"
    remediation: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    rollback: str = ""


@dataclass
class ChangeCommand:
    """A single configuration change command."""

    command: str
    target: str = ""
    dry_run: bool = True
    transaction_id: str = ""


@dataclass
class ChangeResult:
    """Result of executing one or more configuration commands."""

    success: bool
    transaction_id: str
    commands: list[ChangeCommand] = field(default_factory=list)
    output: str = ""
    error: str = ""
    executed_at: str = ""


# ---------------------------------------------------------------------------
# Repository interfaces (data sources)
# ---------------------------------------------------------------------------


class AlarmRepository(ABC):
    """Source of network alarm events."""

    @abstractmethod
    def fetch_alarms(
        self,
        site_id: str,
        scenario_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[AlarmRecord]:
        """Retrieve alarm records for the given site and optional filters."""
        ...

    @abstractmethod
    def health(self) -> dict[str, Any]:
        """Check connectivity and data freshness."""
        ...


class KpiRepository(ABC):
    """Source of network KPI measurements."""

    @abstractmethod
    def fetch_kpis(
        self,
        site_id: str,
        scenario_id: str,
        phase: str | None = None,
        resource_id: str | None = None,
    ) -> list[KpiRecord]:
        """Retrieve KPI records filtered by site, scenario, phase and resource."""
        ...

    @abstractmethod
    def health(self) -> dict[str, Any]:
        """Check connectivity and data freshness."""
        ...


class TopologyRepository(ABC):
    """Source of network topology data."""

    @abstractmethod
    def fetch_topology(self, site_id: str) -> TopologyGraph:
        """Retrieve the complete topology graph for a site."""
        ...

    @abstractmethod
    def health(self) -> dict[str, Any]:
        """Check connectivity and data freshness."""
        ...


class KnowledgeRepository(ABC):
    """Source of fault knowledge rules and historical cases."""

    @abstractmethod
    def fetch_rules(self, keywords: list[str] | None = None) -> list[KnowledgeRule]:
        """Retrieve diagnostic rules, optionally filtered by keywords."""
        ...

    @abstractmethod
    def fetch_historical_cases(self, root_cause: str | None = None) -> list[dict[str, Any]]:
        """Retrieve historical incident cases for reference."""
        ...

    @abstractmethod
    def health(self) -> dict[str, Any]:
        """Check connectivity and data freshness."""
        ...


# ---------------------------------------------------------------------------
# Executor interfaces (change targets)
# ---------------------------------------------------------------------------


class ChangeExecutor(ABC):
    """Executes network configuration changes."""

    @abstractmethod
    def execute(
        self,
        commands: list[ChangeCommand],
        transaction_id: str | None = None,
        dry_run: bool = True,
        idempotency_key: str | None = None,
        timeout_seconds: int = 300,
    ) -> ChangeResult:
        """Execute a batch of commands within a single transaction.

        Args:
            commands: Ordered list of configuration commands.
            transaction_id: Unique identifier; auto-generated if not provided.
            dry_run: When True, validate without applying changes.
            idempotency_key: Optional client-supplied key to prevent duplicate
                execution. Implementations should persist this key and reject
                duplicates within a configurable window.
            timeout_seconds: Maximum execution time before rollback.

        Returns:
            Structured result with success status and output.
        """
        ...

    @abstractmethod
    def rollback(self, transaction_id: str) -> ChangeResult:
        """Roll back a previously executed transaction."""
        ...

    @abstractmethod
    def health(self) -> dict[str, Any]:
        """Check executor connectivity and readiness."""
        ...


# ---------------------------------------------------------------------------
# Default implementations (synthetic data for development / testing)
# ---------------------------------------------------------------------------

import csv
import json
from pathlib import Path


class SyntheticAlarmRepository(AlarmRepository):
    """Reads alarms from the local alarms.csv file."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)

    def fetch_alarms(
        self,
        site_id: str,
        scenario_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[AlarmRecord]:
        path = self.data_dir / "alarms.csv"
        if not path.is_file():
            return []
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        records = []
        for row in rows:
            if row.get("site_id") != site_id:
                continue
            if scenario_id and row.get("scenario_id") != scenario_id:
                continue
            records.append(
                AlarmRecord(
                    event_id=row.get("event_id", ""),
                    timestamp=row.get("timestamp", ""),
                    site_id=row.get("site_id", ""),
                    scenario_id=row.get("scenario_id", ""),
                    severity=row.get("severity", "info"),
                    source=row.get("source", ""),
                    resource_id=row.get("resource_id", ""),
                    alarm_type=row.get("alarm_type", ""),
                    metric=row.get("metric", ""),
                    value=float(row.get("value", 0)),
                    threshold=float(row.get("threshold", 0)),
                    description=row.get("description", ""),
                    correlation_group=row.get("correlation_group", ""),
                )
            )
        return records

    def health(self) -> dict[str, Any]:
        path = self.data_dir / "alarms.csv"
        return {"ok": path.is_file(), "source": str(path)}


class SyntheticKpiRepository(KpiRepository):
    """Reads KPIs from the local kpi_timeseries.csv file."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)

    def fetch_kpis(
        self,
        site_id: str,
        scenario_id: str,
        phase: str | None = None,
        resource_id: str | None = None,
    ) -> list[KpiRecord]:
        path = self.data_dir / "kpi_timeseries.csv"
        if not path.is_file():
            return []
        with path.open("r", encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        records = []
        for row in rows:
            if row.get("site_id") != site_id:
                continue
            if row.get("scenario_id") != scenario_id:
                continue
            if phase and row.get("phase") != phase:
                continue
            if resource_id and row.get("resource_id") != resource_id:
                continue
            records.append(
                KpiRecord(
                    timestamp=row.get("timestamp", ""),
                    site_id=row.get("site_id", ""),
                    scenario_id=row.get("scenario_id", ""),
                    phase=row.get("phase", ""),
                    resource_id=row.get("resource_id", ""),
                    metric=row.get("metric", ""),
                    value=float(row.get("value", 0)),
                    unit=row.get("unit", ""),
                    threshold=float(row.get("threshold", 0)),
                    status=row.get("status", "normal"),
                )
            )
        return records

    def health(self) -> dict[str, Any]:
        path = self.data_dir / "kpi_timeseries.csv"
        return {"ok": path.is_file(), "source": str(path)}


class SyntheticTopologyRepository(TopologyRepository):
    """Reads topology from the local topology.json file."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)

    def fetch_topology(self, site_id: str) -> TopologyGraph:
        path = self.data_dir / "topology.json"
        if not path.is_file():
            return TopologyGraph(site_id=site_id)
        with path.open("r", encoding="utf-8") as stream:
            data = json.load(stream)

        nodes = []
        for item in data.get("nodes", []):
            metadata = {
                key: value
                for key, value in item.items()
                if key not in {"id", "name", "type", "health", "status"}
            }
            nodes.append(
                TopologyNode(
                    id=str(item.get("id", "")),
                    name=str(item.get("name") or item.get("id", "")),
                    type=str(item.get("type", "unknown")),
                    health=str(item.get("health") or item.get("status", "normal")),
                    metadata=metadata,
                )
            )

        links = []
        for item in data.get("links", []):
            metadata = {
                key: value
                for key, value in item.items()
                if key not in {"source", "target", "status", "relation"}
            }
            links.append(
                TopologyLink(
                    source=str(item.get("source", "")),
                    target=str(item.get("target", "")),
                    status=str(item.get("status", "healthy")),
                    relation=str(item.get("relation", "connected_to")),
                    metadata=metadata,
                )
            )
        return TopologyGraph(nodes=nodes, links=links, site_id=site_id)

    def health(self) -> dict[str, Any]:
        path = self.data_dir / "topology.json"
        return {"ok": path.is_file(), "source": str(path)}


class SyntheticKnowledgeRepository(KnowledgeRepository):
    """Reads rules and cases from the local knowledge_base.json file."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)

    def _load(self) -> dict[str, Any]:
        path = self.data_dir / "knowledge_base.json"
        if not path.is_file():
            return {"rules": [], "historical_cases": []}
        with path.open("r", encoding="utf-8") as stream:
            return json.load(stream)

    def fetch_rules(self, keywords: list[str] | None = None) -> list[KnowledgeRule]:
        data = self._load()
        rules = []
        for item in data.get("rules", []):
            rule = KnowledgeRule(
                id=item.get("id", ""),
                root_cause=item.get("root_cause", ""),
                title=item.get("title", ""),
                keywords=item.get("keywords", []),
                root_alarm_type=item.get("root_alarm_type", ""),
                required_alarm_types=item.get("required_alarm_types", []),
                kpi_conditions=item.get("kpi_conditions", []),
                affected_resource_type=item.get("affected_resource_type", ""),
                risk_level=item.get("risk_level", "medium"),
                remediation=item.get("remediation", []),
                commands=item.get("commands", []),
                rollback=item.get("rollback", ""),
            )
            if keywords:
                text = " ".join(rule.keywords + [rule.title, rule.root_cause]).lower()
                if not any(kw.lower() in text for kw in keywords):
                    continue
            rules.append(rule)
        return rules

    def fetch_historical_cases(self, root_cause: str | None = None) -> list[dict[str, Any]]:
        data = self._load()
        cases = data.get("historical_cases", [])
        if root_cause:
            cases = [c for c in cases if c.get("root_cause") == root_cause]
        return cases

    def health(self) -> dict[str, Any]:
        path = self.data_dir / "knowledge_base.json"
        return {"ok": path.is_file(), "source": str(path)}


class SimulationChangeExecutor(ChangeExecutor):
    """Logs commands without applying them to real network equipment.

    This is the default executor for all development and testing environments.
    Production deployments must replace this with a real executor that includes
    authentication, idempotency keys, timeouts, rollbacks, and audit trails.
    """

    def __init__(self, workspace_path: str | Path | None = None) -> None:
        self.workspace_path = Path(workspace_path or "work_space").resolve()
        self.workspace_path.mkdir(parents=True, exist_ok=True)
        self._executed: dict[str, ChangeResult] = {}

    def execute(
        self,
        commands: list[ChangeCommand],
        transaction_id: str | None = None,
        dry_run: bool = True,
        idempotency_key: str | None = None,
        timeout_seconds: int = 300,
    ) -> ChangeResult:
        import uuid
        from datetime import datetime, timezone

        tid = transaction_id or f"TXN-{uuid.uuid4().hex[:8].upper()}"

        # Idempotency check
        if idempotency_key and idempotency_key in self._executed:
            return self._executed[idempotency_key]

        now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        output_lines = [
            f"=== Simulation Transaction {tid} ===",
            f"Dry Run: {dry_run}",
            f"Timestamp: {now}",
            "--- Commands ---",
        ]
        for cmd in commands:
            output_lines.append(f"  [{cmd.target or 'global'}] {cmd.command}")
        output_lines.append("--- End ---")

        # Persist simulation log
        log_path = self.workspace_path / "netheal_outputs" / f"simulation_{tid}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("\n".join(output_lines), encoding="utf-8")

        result = ChangeResult(
            success=True,
            transaction_id=tid,
            commands=commands,
            output="\n".join(output_lines),
            executed_at=now,
        )

        if idempotency_key:
            self._executed[idempotency_key] = result

        return result

    def rollback(self, transaction_id: str) -> ChangeResult:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        return ChangeResult(
            success=True,
            transaction_id=transaction_id,
            output=f"Simulation rollback for {transaction_id} at {now}",
            executed_at=now,
        )

    def health(self) -> dict[str, Any]:
        return {
            "ok": True,
            "type": "simulation",
            "real_network_write_enabled": False,
            "executed_transactions": len(self._executed),
        }
