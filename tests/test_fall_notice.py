from datetime import datetime, timedelta, timezone
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from flask import Flask

path = Path(__file__).resolve().parents[1] / "pi4/integrations/fall_notice.py"
spec = importlib.util.spec_from_file_location("fall_notice", path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class FallNoticeTest(unittest.TestCase):
    def event(self, **kwargs):
        return json.dumps(dict(event_id="event1", event_type="fall_confirmed", camera_id="dahua",
                               timestamp=datetime.now(timezone.utc).isoformat()) | kwargs)

    def test_only_fresh_nonretained_confirmed_events_deduplicated(self):
        notices = module.FallNotices()
        for event_type in ("person_detected", "fall_suspected", "fall_cleared"):
            self.assertFalse(notices.ingest(self.event(event_type=event_type)))
        self.assertFalse(notices.ingest(self.event(), retained=True))
        self.assertFalse(notices.ingest(self.event(timestamp=(datetime.now(timezone.utc)-timedelta(minutes=3)).isoformat())))
        self.assertTrue(notices.ingest(self.event()))
        self.assertFalse(notices.ingest(self.event()))
        snapshot = notices.snapshot()
        self.assertEqual(len(snapshot["events"]), 1)
        self.assertEqual(notices.snapshot(snapshot["cursor"], snapshot["epoch"])["events"], [])

    def test_malformed_messages_cannot_kill_callback(self):
        notices = module.FallNotices()
        for raw in ("null", "[]", "no", b"\xff", self.event(timestamp=None), self.event(event_id=[]), self.event(camera_id=12)):
            self.assertFalse(notices.ingest(raw))

    def test_module_get_only_and_no_alarm_publish(self):
        app = Flask(__name__)
        with patch("paho.mqtt.client.Client") as client:
            notices = module.install(app)
            self.assertIs(module.install(app), notices)
            client.assert_called_once()
            notices.ingest(self.event())
            response = app.test_client().get("/api/fall-notices")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["Cache-Control"], "no-store")
            self.assertEqual(app.test_client().post("/api/fall-notices").status_code, 405)
            client.return_value.publish.assert_not_called()

    def test_snapshot_only_known_ids_fixed_origin_no_redirects(self):
        app = Flask(__name__)
        with patch("paho.mqtt.client.Client"):
            notices = module.install(app)
        identifier = "a"*32
        notices.ingest(self.event(event_id=identifier, details={"test":True, "snapshot":{"id":identifier, "url":"http://evil.example/"}}))
        event = notices.snapshot()["events"][0]
        self.assertTrue(event["test"] and event["snapshot_available"])
        client = app.test_client()
        self.assertEqual(client.get("/api/fall-notices/unknown/snapshot.jpg").status_code, 404)
        with patch.object(module, "build_opener") as factory:
            response = factory.return_value.open.return_value.__enter__.return_value
            response.headers.get_content_type.return_value = "image/jpeg"
            response.read.return_value = b"\xff\xd8jpeg"
            result = client.get(f"/api/fall-notices/{identifier}/snapshot.jpg")
            self.assertEqual(result.status_code, 200)
            self.assertEqual(factory.return_value.open.call_args.args[0].full_url,
                             f"http://192.168.1.20:8080/api/events/{identifier}/snapshot.jpg")
