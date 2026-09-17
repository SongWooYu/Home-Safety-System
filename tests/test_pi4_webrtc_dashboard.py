from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import call, patch


fake_common = types.ModuleType("common")
fake_common.database_connection = lambda: None
fake_common.wait_for_database = lambda: None
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

    def test_dashboard_embeds_three_direct_pi5_webrtc_players(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        for camera_id in ("cam3", "webcam", "dahua"):
            self.assertIn(
                f'http://192.168.1.20:8889/{camera_id}?'.encode(), response.data
            )
        self.assertNotIn(b"/vision/stream/", response.data)

    def test_removed_mjpeg_proxy_route_is_not_available(self):
        response = self.client.get("/vision/stream/cam3")
        self.assertEqual(response.status_code, 404)

    def test_health_checks_vision_api_and_webrtc_gateway(self):
        responses = [
            FakeResponse({"status": "ok", "online_cameras": 3}),
            FakeResponse(),
        ]
        with patch.object(pi4_web.requests, "get", side_effect=responses) as request_get:
            response = self.client.get("/api/vision/health")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["connected"])
        self.assertTrue(response.get_json()["webrtc"])
        self.assertEqual(response.get_json()["upstream"]["online_cameras"], 3)
        self.assertEqual(
            request_get.call_args_list,
            [
                call("http://192.168.1.20:8080/health", timeout=3),
                call("http://192.168.1.20:8889/cam3", timeout=3),
            ],
        )


if __name__ == "__main__":
    unittest.main()
