from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from flask import Flask

path = Path(__file__).resolve().parents[1] / "pi4/integrations/fall_notice.py"
spec = importlib.util.spec_from_file_location("fall_review_module", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FallReviewTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        with patch("paho.mqtt.client.Client") as mqtt:
            self.notices = module.install(app)
            self.mqtt = mqtt.return_value
        self.client = app.test_client()

    def ingest(self, number=1):
        identifier = f"{number:032x}"
        self.assertTrue(self.notices.ingest(json.dumps({
            "event_id": identifier, "event_type": "fall_confirmed", "camera_id": "dahua",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "details": {"snapshot": {"id": identifier}},
        })))
        return identifier

    def test_history_survives_popup_window_and_bounds_to_50(self):
        for number in range(1, 52):
            self.ingest(number)
        self.assertEqual(len(self.notices.events), 50)
        with patch.object(module.time, "time", return_value=module.time.time()+40):
            self.assertEqual(self.notices.snapshot()["events"], [])
            history = self.client.get("/api/fall-history").json
        self.assertEqual(len(history["events"]), 50)
        self.assertEqual(history["events"][0]["event_id"], f"{51:032x}")
        self.assertEqual(history["events"][-1]["event_id"], f"{2:032x}")
        self.assertNotIn("received_at", history["events"][0])
        self.assertEqual(self.client.get(f"/api/fall-notices/{1:032x}/snapshot.jpg").status_code, 404)

    def test_expired_photo_keeps_history_but_does_not_replace_image(self):
        identifier = self.ingest()
        with patch.object(module.time, "time", return_value=module.time.time()+3601):
            events = self.client.get("/api/fall-history").json["events"]
            self.assertEqual(len(events), 1)
            self.assertFalse(events[0]["snapshot_available"])
            self.assertEqual(self.client.get(f"/api/fall-notices/{identifier}/snapshot.jpg").status_code, 404)

    def test_assets_isolated_and_read_only(self):
        for url in ("/fall-review", "/fall-review/assets/review.js", "/fall-review/assets/review.css"):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            response.close()
        self.assertEqual(self.client.get("/fall-review/assets/fall_notice.py").status_code, 404)
        self.assertEqual(self.client.post("/api/fall-history").status_code, 405)
        self.mqtt.publish.assert_not_called()

    def post_sdp(self, **headers):
        return self.client.post("/api/fall-review/whep", data="v=0\r\n", content_type="application/sdp", headers=headers)

    def test_whep_fixed_clean_source_and_session_rewrite(self):
        with patch.object(module, "build_opener") as factory:
            upstream = factory.return_value.open.return_value.__enter__.return_value
            upstream.status = 201
            upstream.read.return_value = b"v=0\r\n"
            upstream.headers.get.return_value = "/dahuaclean/whep/session-123"
            response = self.post_sdp(Origin="http://localhost")
            self.assertEqual(response.status_code, 201)
            self.assertEqual(response.headers["Location"], "/api/fall-review/whep/session-123")
            self.assertEqual(factory.return_value.open.call_args.args[0].full_url,
                             "http://192.168.1.20:8889/dahuaclean/whep")
            upstream.status = 200
            upstream.headers.get.return_value = None
            self.assertEqual(self.client.delete(response.headers["Location"]).status_code, 200)
            self.assertEqual(factory.return_value.open.call_args.args[0].method, "DELETE")
            self.assertEqual(factory.return_value.open.call_args.args[0].full_url,
                             "http://192.168.1.20:8889/dahuaclean/whep/session-123")

    def test_whep_no_cross_site_arbitrary_paths_or_large_body(self):
        self.assertEqual(self.post_sdp(Origin="http://evil.example").status_code, 403)
        self.assertEqual(self.post_sdp(**{"Sec-Fetch-Site":"cross-site"}).status_code, 403)
        self.assertEqual(self.client.post("/api/fall-review/whep",data="bad").status_code, 415)
        self.assertEqual(self.client.post("/api/fall-review/whep",data="x"*131073,content_type="application/sdp").status_code, 413)
        self.assertEqual(self.client.delete("/api/fall-review/whep/invalid.id").status_code, 404)
        with patch.object(module, "build_opener") as factory:
            upstream = factory.return_value.open.return_value.__enter__.return_value
            upstream.status = 201
            upstream.read.return_value = b"v=0"
            for location in (None, "http://evil.example/dahuaclean/whep/id", "/other/whep/id", "/dahuaclean/whep/id?bad=1", "file:///dahuaclean/whep/id"):
                upstream.headers.get.return_value = location
                self.assertEqual(self.post_sdp().status_code, 503)
        with patch.object(module, "build_opener") as factory:
            factory.return_value.open.side_effect = URLError("offline")
            self.assertEqual(self.post_sdp().status_code, 503)

    def test_whep_delete_already_closed_is_idempotent(self):
        with patch.object(module, "build_opener") as factory:
            factory.return_value.open.side_effect = HTTPError("http://fixed", 404, "gone", {}, None)
            self.assertEqual(self.client.delete("/api/fall-review/whep/closed-session").status_code, 204)
            self.assertEqual(self.post_sdp().status_code, 503)

    def test_current_status_whitelisted_cached_and_offline_unknown(self):
        with patch.object(module, "build_opener") as factory:
            upstream = factory.return_value.open.return_value.__enter__.return_value
            upstream.read.return_value = json.dumps({"mqtt_connected":True,"cameras":[{
                "camera_id":"dahua", "online":True, "fall_state":"normal", "last_frame_age":0.1,
                "person_count":2,"secret":"not exposed", "analysis":{"label":"분석 중","detail":"test"},
            }]}).encode()
            response = self.client.get("/api/fall-review/current")
            self.assertTrue(response.json["available"])
            self.assertNotIn("secret", response.json)
            self.client.get("/api/fall-review/current")
            self.assertEqual(factory.return_value.open.call_count, 1)
            factory.return_value.open.side_effect = URLError("offline")
            with patch.object(module.time, "monotonic", return_value=module.time.monotonic()+5):
                response = self.client.get("/api/fall-review/current")
            self.assertFalse(response.json["available"])
            self.assertEqual(response.json["fall_state"], "unknown")

    def test_stale_camera_cannot_claim_normal_current_state(self):
        with patch.object(module, "build_opener") as factory:
            upstream = factory.return_value.open.return_value.__enter__.return_value
            upstream.read.return_value = json.dumps({"cameras":[{
                "camera_id":"dahua","online":True,"last_frame_age":10,"fall_state":"normal",
            }]}).encode()
            data = self.client.get("/api/fall-review/current").json
            self.assertFalse(data["available"])
            self.assertEqual(data["fall_state"], "unknown")
