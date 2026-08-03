from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch
from dataclasses import asdict
from pathlib import Path

from app.netheal.advanced_diagnosis import (
    FusionDiagnosisEngine,
    GraphReasoner,
    VectorCaseRetriever,
)
from app.netheal.auth import AuthRole, TokenService
from app.netheal.configuration import model_config_status
from app.netheal.interfaces import (
    ChangeCommand,
    SimulationChangeExecutor,
    SyntheticAlarmRepository,
    SyntheticKpiRepository,
    SyntheticKnowledgeRepository,
    SyntheticTopologyRepository,
)
from app.netheal.reporting import ReportSearchEngine
from app.netheal.streaming import EventBus, StreamEvent, StreamEventType
from app.netheal.task_queue import TaskQueue, TaskStatus


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "app" / "netheal" / "data"


class AdvancedDiagnosisTests(unittest.TestCase):
    def test_vector_search_matches_chinese_and_network_terms(self) -> None:
        retriever = VectorCaseRetriever(DATA_DIR / "knowledge_base.json")
        results = retriever.search("UPF CPU 过载 视频时延", top_k=2)

        self.assertTrue(results)
        self.assertEqual(results[0].root_cause, "UPF_OVERLOAD")
        self.assertGreater(results[0].score, 0)

    def test_graph_and_rule_fusion_preserves_available_evidence_weight(self) -> None:
        topology = json.loads(
            (DATA_DIR / "topology.json").read_text(encoding="utf-8")
        )
        reasoner = GraphReasoner(topology)
        engine = FusionDiagnosisEngine(reasoner)
        diagnosis = {
            "primary_diagnosis": {
                "root_cause": "UPF_OVERLOAD",
                "title": "UPF节点过载",
                "root_resource": "UPF-01",
                "confidence": 0.9,
            },
            "ranked_candidates": [],
        }

        result = engine.fuse(
            diagnosis,
            ["UPF-01", "UPF-01", "UPF-01", "slice-video", "video-service"],
        )

        self.assertEqual(result.primary_resource, "UPF-01")
        self.assertGreaterEqual(result.confidence, 0.9)
        self.assertFalse(result.review_required)


class ProductionInterfaceTests(unittest.TestCase):
    def test_synthetic_repositories_follow_current_data_contract(self) -> None:
        alarms = SyntheticAlarmRepository(DATA_DIR).fetch_alarms(
            "campus-5g", "upf-overload"
        )
        kpis = SyntheticKpiRepository(DATA_DIR).fetch_kpis(
            "campus-5g", "upf-overload", phase="incident"
        )
        topology = SyntheticTopologyRepository(DATA_DIR).fetch_topology("campus-5g")
        rules = SyntheticKnowledgeRepository(DATA_DIR).fetch_rules(["UPF"])

        self.assertGreaterEqual(len(alarms), 3)
        self.assertGreaterEqual(len(kpis), 3)
        self.assertEqual(len(topology.nodes), 10)
        self.assertEqual(len(topology.links), 10)
        self.assertEqual(topology.nodes[0].name, topology.nodes[0].id)
        self.assertEqual(rules[0].root_cause, "UPF_OVERLOAD")

    def test_simulation_executor_is_idempotent_and_never_writes_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            executor = SimulationChangeExecutor(tmp)
            command = ChangeCommand("traffic-steering validate", target="UPF-01")
            first = executor.execute(
                [command], idempotency_key="case-1", dry_run=True
            )
            second = executor.execute(
                [command], idempotency_key="case-1", dry_run=True
            )

            self.assertTrue(first.success)
            self.assertEqual(first.transaction_id, second.transaction_id)
            self.assertFalse(executor.health()["real_network_write_enabled"])


class RuntimeEnhancementTests(unittest.TestCase):
    def test_task_queue_tracks_result_and_idempotency(self) -> None:
        task_queue = TaskQueue(max_workers=1)
        try:
            task_id = task_queue.submit(
                lambda: {"ok": True},
                idempotency_key="demo-once",
                max_retries=0,
            )
            duplicate_id = task_queue.submit(
                lambda: {"ok": False},
                idempotency_key="demo-once",
                max_retries=0,
            )
            result = task_queue.get_result(task_id)

            self.assertEqual(task_id, duplicate_id)
            self.assertIsNotNone(result)
            self.assertEqual(result.status, TaskStatus.COMPLETED)
            self.assertEqual(result.result, {"ok": True})
        finally:
            task_queue.shutdown()

    def test_event_bus_delivers_structured_events(self) -> None:
        bus = EventBus()
        subscriber = bus.subscribe()
        bus.publish(
            StreamEvent(
                event_type=StreamEventType.STATUS_CHANGED,
                data={"status": "closed"},
                incident_id="NH-001",
            )
        )

        events = bus.get_events(subscriber, timeout=0.01)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].incident_id, "NH-001")
        self.assertEqual(events[0].data["status"], "closed")

    def test_report_search_indexes_generated_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "incident.md"
            report.write_text(
                "UPF-01 CPU过载导致视频业务高时延", encoding="utf-8"
            )
            engine = ReportSearchEngine(tmp)
            engine.index_incident(
                {
                    "id": "NH-001",
                    "scenario_id": "upf-overload",
                    "title": "UPF过载",
                    "root_cause": "UPF_OVERLOAD",
                    "status": "closed",
                    "repair": {"report": {"markdown_path": str(report)}},
                }
            )

            results = engine.search("UPF-01")
            self.assertEqual(len(results), 1)
            self.assertEqual(asdict(results[0])["incident_id"], "NH-001")


class SecurityConfigurationTests(unittest.TestCase):
    def test_signed_token_rejects_tampering(self) -> None:
        service = TokenService(secret_key="unit-test-secret", max_age_seconds=60)
        token = service.issue("operator-a", AuthRole.OPERATOR, "campus-5g")
        context = service.verify(token)

        self.assertEqual(context.actor, "operator-a")
        self.assertEqual(context.role, AuthRole.OPERATOR)
        self.assertEqual(context.tenant_id, "campus-5g")
        with self.assertRaises(PermissionError):
            service.verify(f"{token}tampered")

    def test_configuration_status_never_returns_secret_values(self) -> None:
        secret = "sk-unit-test-do-not-leak"
        with patch.dict(
            os.environ,
            {
                "API_KEY": secret,
                "API_BASE_URL": "https://provider.example/v1",
                "MODEL_NAME": "unit-model",
            },
            clear=False,
        ):
            status = model_config_status()

        self.assertTrue(status["llm"]["configured"])
        self.assertTrue(status["llm"]["api_key_present"])
        self.assertNotIn(secret, json.dumps(status, ensure_ascii=False))
        self.assertFalse(status["security"]["real_network_write_enabled"])


if __name__ == "__main__":
    unittest.main()
