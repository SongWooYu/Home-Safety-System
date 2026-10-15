from __future__ import annotations

import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import call, patch


fake_common = types.ModuleType("common")
fake_common.database_connection = lambda: None
fake_common.wait_for_database = lambda: None
fake_common.decode_payload = lambda payload: payload
fake_common.mqtt_client = lambda client_id: None
sys.modules.setdefault("common", fake_common)

WEB_PATH = Path(__file__).resolve().parents[1] / "pi4" / "backend" / "web.py"
SPEC = importlib.util.spec_from_file_location("pi4_web_for_test", WEB_PATH)
pi4_web = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(pi4_web)
pi4_web.app.template_folder = str(WEB_PATH.parent / "templates")


class FakeResponse:
    def __init__(self, payload=None):
        self.payload = payload or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class Pi4WebRtcDashboardTest(unittest.TestCase):
    def setUp(self):
        self.client = pi4_web.app.test_client()

    def test_dashboard_embeds_two_direct_pi5_webrtc_players(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"http://192.168.1.20:8889/cam3?", response.data)
        self.assertIn(b"http://192.168.1.20:8889/dahuaclean?", response.data)
        self.assertNotIn(b"/webcam?", response.data)
        self.assertNotIn(b"/vision/stream/", response.data)
        self.assertIn("시험 낙상 경보 발생".encode(), response.data)
        self.assertIn("낙상 경보 해제".encode(), response.data)
        self.assertIn(b"alarm-volume", response.data)

    def test_removed_mjpeg_proxy_route_is_not_available(self):
        response = self.client.get("/vision/stream/cam3")
        self.assertEqual(response.status_code, 404)

    def test_health_checks_vision_api_and_webrtc_gateway(self):
        responses = [
            FakeResponse({"status": "ok", "online_cameras": 2}),
            FakeResponse(),
        ]
        with patch.object(pi4_web.requests, "get", side_effect=responses) as request_get:
            response = self.client.get("/api/vision/health")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["connected"])
        self.assertTrue(response.get_json()["webrtc"])
        self.assertEqual(response.get_json()["upstream"]["online_cameras"], 2)
        self.assertEqual(
            request_get.call_args_list,
            [
                call("http://192.168.1.20:8080/health", timeout=3),
                call("http://192.168.1.20:8889/dahuaclean", timeout=3),
            ],
        )

    def test_alarm_test_cancel_and_volume_require_admin_key(self):
        with patch.dict(os.environ, {"ADMIN_TOKEN": "alarm-secret"}):
            self.assertEqual(self.client.post("/api/alarm/test").status_code, 401)
            self.assertEqual(self.client.post("/api/alarm/cancel").status_code, 401)
            self.assertEqual(
                self.client.post("/api/alarm/volume", json={"volume": 70}).status_code,
                401,
            )

            headers = {"X-Admin-Token": "alarm-secret"}
            with patch.object(pi4_web, "single") as publish:
                test_response = self.client.post("/api/alarm/test", headers=headers)
                cancel_response = self.client.post("/api/alarm/cancel", headers=headers)
                volume_response = self.client.post(
                    "/api/alarm/volume",
                    headers=headers,
                    json={"volume": 65},
                )

        self.assertEqual(test_response.status_code, 200)
        self.assertEqual(cancel_response.status_code, 200)
        self.assertEqual(volume_response.get_json()["volume"], 65)
        self.assertEqual(publish.call_count, 3)
        self.assertTrue(publish.call_args_list[-1].kwargs["retain"])

    def test_alarm_volume_rejects_out_of_range_value(self):
        with patch.dict(os.environ, {"ADMIN_TOKEN": "alarm-secret"}):
            response = self.client.post(
                "/api/alarm/volume",
                headers={"X-Admin-Token": "alarm-secret"},
                json={"volume": 101},
            )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
