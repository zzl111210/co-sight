from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.netheal.service import NetHealService
from cosight_server.deep_research.routers import netheal as netheal_router


class NetHealServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.service = NetHealService(
            workspace_path=self.root / "workspace",
            database_path=self.root / "netheal.db",
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_full_incident_lifecycle_is_auditable(self) -> None:
        diagnosed = self.service.diagnose(
            "upf-overload",
            incident_id="NH-DEMO-001",
            actor="operator-a",
            role="operator",
        )
        incident = diagnosed["incident"]

        self.assertEqual(incident["status"], "approval_pending")
        self.assertEqual(incident["root_cause"], "UPF_OVERLOAD")
        self.assertEqual(incident["root_resource"], "UPF-01")
        self.assertGreaterEqual(incident["confidence"], 0.8)
        self.assertTrue(
            {"alarm_summary", "kpi_violations", "downstream_impact"}
            <= set(incident["evidence"])
        )

        with self.assertRaises(PermissionError):
            self.service.approve(
                incident["id"],
                "operator-a",
                "operator",
                "越权审批",
            )

        approved = self.service.approve(
            incident["id"],
            "approver-a",
            "approver",
            "已核查仿真变更风险",
        )
        self.assertEqual(approved["incident"]["status"], "approved")

        executed = self.service.execute(
            incident["id"],
            "operator-a",
            "operator",
        )
        self.assertEqual(executed["incident"]["status"], "verifying")
        self.assertTrue(executed["incident"]["repair"]["commands"]["dry_run"])

        verified = self.service.verify(
            incident["id"],
            "operator-a",
            "operator",
        )
        self.assertEqual(verified["incident"]["status"], "closed")
        self.assertTrue(verified["incident"]["verification_passed"])
        self.assertTrue(verified["incident"]["repair"]["verification"]["passed"])
        self.assertGreaterEqual(len(verified["events"]), 8)

        report = verified["incident"]["repair"]["report"]
        self.assertTrue(Path(report["markdown_path"]).is_file())
        self.assertTrue(Path(report["html_path"]).is_file())

        audit_actions = {record["action"] for record in self.service.audit()}
        self.assertTrue(
            {"diagnose", "approve", "execute_simulation", "verify_recovery"}
            <= audit_actions
        )

    def test_state_machine_rejects_out_of_order_execution(self) -> None:
        with self.assertRaisesRegex(ValueError, "transition"):
            self.service.execute("NH-DEMO-001", "operator-a", "operator")

    def test_store_persists_incidents_between_service_instances(self) -> None:
        self.service.diagnose(
            "upf-overload",
            incident_id="NH-DEMO-001",
            actor="operator-a",
            role="operator",
        )
        restored = NetHealService(
            workspace_path=self.root / "workspace",
            database_path=self.service.store.database_path,
        )
        incident = restored.detail("NH-DEMO-001")["incident"]

        self.assertEqual(incident["status"], "approval_pending")
        self.assertEqual(incident["root_cause"], "UPF_OVERLOAD")
        self.assertTrue(restored.health()["database"]["ok"])

    def test_rest_api_enforces_role_permissions(self) -> None:
        original_service = netheal_router._service
        netheal_router._service = self.service
        try:
            app = FastAPI()
            app.include_router(netheal_router.nethealRouter)
            client = TestClient(app)

            health = client.get("/api/netheal/v1/health")
            self.assertEqual(health.status_code, 200)
            self.assertTrue(health.json()["simulation_mode"])
            self.assertFalse(health.json()["real_network_write_enabled"])

            scenarios = client.get("/api/netheal/v1/scenarios")
            self.assertEqual(scenarios.status_code, 200)
            self.assertEqual(len(scenarios.json()["items"]), 4)
            self.assertEqual(
                {item["test_case_id"] for item in scenarios.json()["items"]},
                {"TC-01", "TC-02", "TC-03", "TC-06"},
            )

            incidents = client.get("/api/netheal/v1/incidents")
            self.assertEqual(incidents.status_code, 200)
            self.assertEqual(len(incidents.json()["items"]), 3)

            forbidden = client.post(
                "/api/netheal/v1/incidents/diagnose",
                json={
                    "scenario_id": "upf-overload",
                    "incident_id": "NH-DEMO-001",
                },
                headers={
                    "X-NetHeal-Actor": "viewer-a",
                    "X-NetHeal-Role": "viewer",
                },
            )
            self.assertEqual(forbidden.status_code, 403)

            diagnosed = client.post(
                "/api/netheal/v1/incidents/diagnose",
                json={
                    "scenario_id": "upf-overload",
                    "incident_id": "NH-DEMO-001",
                },
                headers={
                    "X-NetHeal-Actor": "operator-a",
                    "X-NetHeal-Role": "operator",
                },
            )
            self.assertEqual(diagnosed.status_code, 200)
            self.assertEqual(
                diagnosed.json()["incident"]["status"],
                "approval_pending",
            )

            denied_approval = client.post(
                "/api/netheal/v1/incidents/NH-DEMO-001/approve",
                json={"comment": "越权尝试"},
                headers={
                    "X-NetHeal-Actor": "operator-a",
                    "X-NetHeal-Role": "operator",
                },
            )
            self.assertEqual(denied_approval.status_code, 403)

            approval = client.post(
                "/api/netheal/v1/incidents/NH-DEMO-001/approve",
                json={"comment": "测试批准"},
                headers={
                    "X-NetHeal-Actor": "approver-a",
                    "X-NetHeal-Role": "approver",
                },
            )
            self.assertEqual(approval.status_code, 200)
            self.assertEqual(approval.json()["incident"]["status"], "approved")
        finally:
            netheal_router._service = original_service

    def test_demo_reset_requires_admin(self) -> None:
        with self.assertRaises(PermissionError):
            self.service.reset_demo("operator-a", "operator")

        reset = self.service.reset_demo("admin-a", "admin")
        self.assertEqual(reset["active_incidents"], 2)
        self.assertEqual(len(self.service.incidents()), 3)


    def test_advanced_api_and_background_demo(self) -> None:
        original_service = netheal_router._service
        original_insights = netheal_router._insights
        netheal_router._service = self.service
        netheal_router._insights = None
        try:
            app = FastAPI()
            app.include_router(netheal_router.nethealRouter)
            client = TestClient(app)

            vector = client.get(
                "/api/netheal/v1/diagnosis/vector-search",
                params={"q": "UPF CPU 视频时延"},
            )
            self.assertEqual(vector.status_code, 200)
            self.assertEqual(
                vector.json()["items"][0]["root_cause"],
                "UPF_OVERLOAD",
            )

            graph = client.get(
                "/api/netheal/v1/diagnosis/graph-reasoning",
                params={"scenario_id": "alarm-storm-composite"},
            )
            self.assertEqual(graph.status_code, 200)
            self.assertTrue(graph.json()["root_candidates"])

            fusion = client.get(
                "/api/netheal/v1/diagnosis/fusion",
                params={"scenario_id": "alarm-storm-composite"},
            )
            self.assertEqual(fusion.status_code, 200)
            self.assertEqual(
                fusion.json()["primary_root_cause"],
                "COMPOSITE_UPF_OVERLOAD_AND_TRANSMISSION_JITTER",
            )

            submitted = client.post(
                "/api/netheal/v1/demo/run",
                params={"async_mode": "true"},
                json={
                    "scenario_id": "upf-overload",
                    "idempotency_key": f"test-{self.root.name}",
                },
                headers={
                    "X-NetHeal-Actor": "approver-a",
                    "X-NetHeal-Role": "approver",
                },
            )
            self.assertEqual(submitted.status_code, 200)
            task_id = submitted.json()["task_id"]

            deadline = time.time() + 5
            progress_payload = {}
            while time.time() < deadline:
                progress = client.get(
                    f"/api/netheal/v1/tasks/{task_id}/progress"
                )
                self.assertEqual(progress.status_code, 200)
                progress_payload = progress.json()
                if progress_payload["status"] in {"completed", "failed"}:
                    break
                time.sleep(0.02)

            self.assertEqual(progress_payload["status"], "completed")
            self.assertEqual(progress_payload["progress"]["percent"], 100.0)

            result = client.get(f"/api/netheal/v1/tasks/{task_id}/result")
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json()["status"], "completed")
            incident_id = result.json()["result"]["incident"]["id"]

            report = client.get(
                f"/api/netheal/v1/incidents/{incident_id}/report"
            )
            self.assertEqual(report.status_code, 200)
            self.assertTrue(report.json()["available"]["markdown"])

            download = client.get(
                f"/api/netheal/v1/incidents/{incident_id}/report/download/md",
                headers={
                    "X-NetHeal-Actor": "viewer-a",
                    "X-NetHeal-Role": "viewer",
                },
            )
            self.assertEqual(download.status_code, 200)
            self.assertIn("NetHeal-Agent", download.text)

            search = client.get(
                "/api/netheal/v1/reports/search",
                params={"q": "UPF"},
            )
            self.assertEqual(search.status_code, 200)
            self.assertGreaterEqual(search.json()["total"], 1)

            explanation = client.get(
                f"/api/netheal/v1/diagnosis/explain/{incident_id}"
            )
            self.assertEqual(explanation.status_code, 200)
            self.assertTrue(explanation.json()["reasoning_hops"])
        finally:
            netheal_router._service = original_service
            netheal_router._insights = original_insights

    def test_bearer_auth_and_safe_configuration_api(self) -> None:
        original_service = netheal_router._service
        original_token_service = netheal_router._token_service
        netheal_router._service = self.service
        netheal_router._token_service = None
        try:
            app = FastAPI()
            app.include_router(netheal_router.nethealRouter)
            client = TestClient(app)

            login = client.post(
                "/api/netheal/v1/auth/login",
                json={
                    "actor": "operator-token",
                    "role": "operator",
                    "tenant_id": "campus-5g",
                },
            )
            self.assertEqual(login.status_code, 200)
            token = login.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            identity = client.get(
                "/api/netheal/v1/auth/me",
                headers=headers,
            )
            self.assertEqual(identity.status_code, 200)
            self.assertEqual(identity.json()["actor"], "operator-token")
            self.assertEqual(identity.json()["tenant_id"], "campus-5g")

            sites = client.get("/api/netheal/v1/sites")
            self.assertEqual(sites.status_code, 200)
            self.assertEqual(sites.json()["items"][0]["id"], "campus-5g")
            self.assertTrue(sites.json()["items"][0]["simulation_mode"])

            config = client.get("/api/netheal/v1/config/status")
            self.assertEqual(config.status_code, 200)
            self.assertNotIn("api_key", config.json()["llm"])
            self.assertFalse(
                config.json()["security"]["real_network_write_enabled"]
            )

            diagnosed = client.post(
                "/api/netheal/v1/incidents/diagnose",
                json={
                    "scenario_id": "upf-overload",
                    "incident_id": "NH-DEMO-001",
                },
                headers=headers,
            )
            self.assertEqual(diagnosed.status_code, 200)
            self.assertEqual(
                diagnosed.json()["incident"]["status"],
                "approval_pending",
            )
        finally:
            netheal_router._service = original_service
            netheal_router._token_service = original_token_service


if __name__ == "__main__":
    unittest.main()
