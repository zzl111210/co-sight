"""SQLite persistence for incidents, lifecycle events, and audit records."""

from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class NetHealStore:
    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path).resolve()
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA journal_mode = WAL")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS incidents (
                    id TEXT PRIMARY KEY,
                    site_id TEXT NOT NULL,
                    scenario_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    status TEXT NOT NULL,
                    root_cause TEXT,
                    root_resource TEXT,
                    confidence REAL,
                    affected_service TEXT,
                    risk_level TEXT,
                    verification_passed INTEGER,
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    repair_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    version INTEGER NOT NULL DEFAULT 1
                );
                CREATE INDEX IF NOT EXISTS idx_incidents_updated
                    ON incidents(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_incidents_scenario
                    ON incidents(scenario_id, updated_at DESC);

                CREATE TABLE IF NOT EXISTS incident_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(incident_id) REFERENCES incidents(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_events_incident
                    ON incident_events(incident_id, id);

                CREATE TABLE IF NOT EXISTS audit_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    incident_id TEXT,
                    actor TEXT NOT NULL,
                    role TEXT NOT NULL,
                    action TEXT NOT NULL,
                    result TEXT NOT NULL,
                    detail_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_audit_created
                    ON audit_records(created_at DESC);
                """
            )

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value or {}, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _decode_row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        for source, target in (("evidence_json", "evidence"), ("repair_json", "repair")):
            if source in data:
                data[target] = json.loads(data.pop(source) or "{}")
        if data.get("verification_passed") is not None:
            data["verification_passed"] = bool(data["verification_passed"])
        return data

    def upsert_incident(self, incident: dict[str, Any]) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO incidents (
                    id, site_id, scenario_id, title, severity, status,
                    root_cause, root_resource, confidence, affected_service,
                    risk_level, verification_passed, evidence_json, repair_json,
                    created_at, updated_at, version
                ) VALUES (
                    :id, :site_id, :scenario_id, :title, :severity, :status,
                    :root_cause, :root_resource, :confidence, :affected_service,
                    :risk_level, :verification_passed, :evidence_json, :repair_json,
                    :created_at, :updated_at, :version
                )
                ON CONFLICT(id) DO UPDATE SET
                    status=excluded.status,
                    root_cause=excluded.root_cause,
                    root_resource=excluded.root_resource,
                    confidence=excluded.confidence,
                    affected_service=excluded.affected_service,
                    risk_level=excluded.risk_level,
                    verification_passed=excluded.verification_passed,
                    evidence_json=excluded.evidence_json,
                    repair_json=excluded.repair_json,
                    updated_at=excluded.updated_at,
                    version=excluded.version
                """,
                {
                    **incident,
                    "verification_passed": (
                        None
                        if incident.get("verification_passed") is None
                        else int(bool(incident["verification_passed"]))
                    ),
                    "evidence_json": self._json(incident.get("evidence")),
                    "repair_json": self._json(incident.get("repair")),
                },
            )

    def get_incident(self, incident_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM incidents WHERE id = ?", (incident_id,)
            ).fetchone()
        return self._decode_row(row)

    def list_incidents(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM incidents ORDER BY updated_at DESC LIMIT ?", (int(limit),)
            ).fetchall()
        return [self._decode_row(row) for row in rows if row is not None]

    def latest_for_scenario(self, scenario_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM incidents
                WHERE scenario_id = ?
                ORDER BY updated_at DESC LIMIT 1
                """,
                (scenario_id,),
            ).fetchone()
        return self._decode_row(row)

    def add_event(
        self,
        incident_id: str,
        event_type: str,
        actor: str,
        message: str,
        payload: dict[str, Any],
        created_at: str,
    ) -> int:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO incident_events (
                    incident_id, event_type, actor, message, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    incident_id,
                    event_type,
                    actor,
                    message,
                    self._json(payload),
                    created_at,
                ),
            )
            return int(cursor.lastrowid)

    def list_events(self, incident_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, incident_id, event_type, actor, message, payload_json, created_at
                FROM incident_events WHERE incident_id = ? ORDER BY id
                """,
                (incident_id,),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["payload"] = json.loads(item.pop("payload_json") or "{}")
            result.append(item)
        return result

    def add_audit(
        self,
        incident_id: str | None,
        actor: str,
        role: str,
        action: str,
        result: str,
        detail: dict[str, Any],
        created_at: str,
    ) -> int:
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO audit_records (
                    incident_id, actor, role, action, result, detail_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    incident_id,
                    actor,
                    role,
                    action,
                    result,
                    self._json(detail),
                    created_at,
                ),
            )
            return int(cursor.lastrowid)

    def list_audit(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, incident_id, actor, role, action, result, detail_json, created_at
                FROM audit_records ORDER BY id DESC LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["detail"] = json.loads(item.pop("detail_json") or "{}")
            result.append(item)
        return result

    def clear(self) -> None:
        with self._lock, self._connect() as connection:
            connection.execute("DELETE FROM incident_events")
            connection.execute("DELETE FROM audit_records")
            connection.execute("DELETE FROM incidents")

    def health(self) -> dict[str, Any]:
        with self._connect() as connection:
            result = connection.execute("SELECT 1 AS ok").fetchone()
        return {
            "ok": bool(result and result["ok"] == 1),
            "database_path": str(self.database_path),
        }
