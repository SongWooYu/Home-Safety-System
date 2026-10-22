import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from flask import Flask
from smarthome_vision.evidence import EvidenceStore
from smarthome_vision.events import EventBus
from smarthome_vision.fall_demo import register_fall_demo_routes


class FallDemoTest(unittest.TestCase):
    def setUp(self):
        self.bus = EventBus({})
        self.bus._connected = True
        self.bus._client = Mock()
        self.bus._client.publish.return_value = Mock(rc=0)
        self.bus._client.publish.return_value.is_published.return_value = True
        self.bus.snapshot_provider = lambda camera, **kwargs: (b"\xff\xd8test", {"camera_id":camera})
        app = Flask(__name__)
        register_fall_demo_routes(app, SimpleNamespace(event_bus=self.bus))
        self.client = app.test_client()

    def test_stage_contract_distinct_identity_snapshot_and_broker_ack(self):
        response = self.client.post("/api/fall-test", json={"stage":"confirmed"})
        self.assertEqual(response.status_code, 200)
        event = response.json["event"]
        self.assertEqual(event["camera_id"], "manual-test")
        self.assertTrue(event["details"]["test"])
        self.assertEqual(event["details"]["snapshot"]["camera_id"], "dahua")
        args, kwargs = self.bus._client.publish.call_args
        self.assertEqual(args[0], "home/vision/events")
        self.assertEqual(json.loads(args[1])["event_type"], "fall_confirmed")
        self.assertEqual(kwargs, {"qos":1, "retain":False})
        self.assertEqual(self.client.get(f'/api/events/{event["event_id"]}/snapshot.jpg').data, b"\xff\xd8test")
        self.assertEqual(self.client.post("/api/fall-test", json={"stage":"cleared"}).status_code, 429)

    def test_offline_invalid_cross_origin_and_no_admin(self):
        for value in (None, [], True, "alarm", "normal"):
            self.assertEqual(self.client.post("/api/fall-test", json={"stage":value}).status_code, 400)
        self.assertEqual(self.client.post("/api/fall-test", json={}, headers={"Origin":"https://other.example"}).status_code, 403)
        self.bus._connected = False
        self.assertEqual(self.client.post("/api/fall-test", json={"stage":"confirmed"}).status_code, 503)
        self.assertEqual(self.bus.recent(), [])

    def test_real_confirmed_captured_but_other_events_not(self):
        self.bus.emit("dahua", "fall_suspected")
        self.assertFalse(self.bus.evidence.items)
        event = self.bus.emit("dahua", "fall_confirmed")
        self.assertNotIn("test", event["details"])
        self.assertIsNotNone(self.bus.evidence.get(event["event_id"]))
        self.bus.snapshot_provider = Mock(side_effect=RuntimeError("camera down"))
        with patch("builtins.print"):
            event = self.bus.emit("dahua", "fall_confirmed")
        self.assertEqual(event["event_type"], "fall_confirmed")
        self.assertNotIn("snapshot", event["details"])

    def test_store_memory_count_bytes_ttl_and_bad_id(self):
        store = EvidenceStore(limit=2, ttl=1, max_bytes=10)
        self.assertFalse(store.put("x", b"jpg"))
        self.assertFalse(store.put("a"*32, b"x"*11))
        for key in "abc": store.put(key*32, b"jpg")
        self.assertIsNone(store.get("a"*32))
        with patch("smarthome_vision.evidence.time.monotonic", return_value=1e20):
            self.assertIsNone(store.get("c"*32))
        self.assertEqual(len(store.items), 0)

    def test_pi4_state_subscription_and_whitelist(self):
        self.bus._on_connect(self.bus._client, None, None, 0)
        self.bus._client.subscribe.assert_called_once_with("home/safety/fall/state", qos=1)
        self.bus._on_message(None, None, SimpleNamespace(topic="home/safety/fall/state", payload=b'{"state":"alarm", "camera_id":"manual-test", "extra":"ignored"}'))
        self.assertEqual(self.client.get("/api/fall-test").json["pi4_state"]["state"], "alarm")
        self.assertNotIn("extra", self.bus.safety_state)
