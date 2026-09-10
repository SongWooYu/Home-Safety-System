from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


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


class FakeUpstream:
    headers = {"Content-Type": "multipart/x-mixed-replace; boundary=frame"}

    def __init__(self):
        self.closed = False

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size):
        self.chunk_size = chunk_size
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\nJPEG\r\n"

    def json(self):
        return {"status": "ok", "online_cameras": 3}

    def close(self):
        self.closed = True


class Pi4VideoProxyTest(unittest.TestCase):
    def setUp(self):
        self.client = pi4_web.app.test_client()

    def test_relays_allowed_camera_with_limited_upstream_fps(self):
        upstream = FakeUpstream()
        with patch.object(pi4_web.requests, "get", return_value=upstream) as request_get:
            response = self.client.get("/vision/stream/cam3", buffered=False)
            first_chunk = next(response.response)
            response.close()

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"JPEG", first_chunk)
        request_get.assert_called_once_with(
            "http://192.168.1.20:8080/stream/cam3?fps=8",
            stream=True,
            timeout=(3, 15),
        )
        self.assertTrue(upstream.closed)

    def test_dashboard_embeds_three_local_proxy_streams(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        for camera_id in ("cam3", "webcam", "dahua"):
            self.assertIn(f'/vision/stream/{camera_id}'.encode(), response.data)

    def test_rejects_camera_not_in_allowlist(self):
        response = self.client.get("/vision/stream/not-configured")
        self.assertEqual(response.status_code, 404)

    def test_reports_pi5_health(self):
        with patch.object(pi4_web.requests, "get", return_value=FakeUpstream()):
            response = self.client.get("/api/vision/health")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["connected"])
        self.assertEqual(response.get_json()["upstream"]["online_cameras"], 3)


if __name__ == "__main__":
    unittest.main()
