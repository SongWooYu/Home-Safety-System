import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from flask import Flask
import yaml

from smarthome_vision.audio_api import register_audio_routes
from smarthome_vision.events import EventBus


class AudioApiTest(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        self.bus = Mock()
        register_audio_routes(app, SimpleNamespace(event_bus=self.bus))
        self.client = app.test_client()

    def test_no_admin_key_needed_and_test_does_not_create_alarm(self):
        self.assertEqual(self.client.post("/api/audio/test", json={}).status_code, 200)
        self.bus.publish_audio.assert_called_once_with("test_tts", None)
        self.assertEqual(self.client.post("/api/audio/test", json={}).status_code, 429)

    def test_volume_is_strict_bounded_integer(self):
        for value in (True, 1.5, "50", -1, 0, 50, 59, 101, None):
            self.assertEqual(self.client.post("/api/audio/volume", json={"volume":value}).status_code, 400)
        self.assertEqual(self.client.post("/api/audio/volume", json={"volume":60}).status_code, 200)
        self.bus.publish_audio.assert_called_once_with("volume", 60)

    def test_loopback_tunnel_https_is_allowed(self):
        response = self.client.post("/api/audio/test", json={}, base_url="http://vision.aihous.site",
                                    headers={"Origin":"https://vision.aihous.site", "X-Forwarded-Proto":"https", "Sec-Fetch-Site":"same-origin"},
                                    environ_overrides={"REMOTE_ADDR":"127.0.0.1"})
        self.assertEqual(response.status_code, 200)

    def test_forwarded_scheme_cannot_be_spoofed_from_lan(self):
        for peer, proto, origin in (("192.168.1.5", "https", "https://vision.aihous.site"),
                                    ("127.0.0.1", "https", "https://other.example"),
                                    ("::1", "https,http", "https://vision.aihous.site"),
                                    ("127.0.0.1", "https", "null")):
            response = self.client.post("/api/audio/test", json={}, base_url="http://vision.aihous.site",
                                        headers={"Origin":origin, "X-Forwarded-Proto":proto}, environ_overrides={"REMOTE_ADDR":peer})
            self.assertEqual(response.status_code, 403)
        self.bus.publish_audio.assert_not_called()

    def test_invalid_body_and_cross_origin_rejected(self):
        self.assertEqual(self.client.post("/api/audio/test", json=[]).status_code, 400)
        self.assertEqual(self.client.post("/api/audio/test", data="{}").status_code, 415)
        self.assertEqual(self.client.post("/api/audio/test", json={}, headers={"Origin":"https://other.example"}).status_code, 403)
        self.bus.publish_audio.assert_not_called()

    def test_broker_failure_is_not_shown_as_success(self):
        self.bus.publish_audio.side_effect = RuntimeError("offline")
        self.assertEqual(self.client.post("/api/audio/test", json={}).status_code, 503)

    def test_mqtt_topics_qos_retain_and_ack(self):
        bus = EventBus({})
        with self.assertRaises(RuntimeError):
            bus.publish_audio("test_tts")
        bus._connected = True
        bus._client = Mock()
        info = Mock(rc=0)
        info.is_published.return_value = True
        bus._client.publish.return_value = info
        bus.publish_audio("test_tts")
        args, kwargs = bus._client.publish.call_args
        self.assertEqual(args[0], "home/safety/fall/audio/command")
        self.assertEqual(json.loads(args[1])["action"], "test_tts")
        self.assertEqual(kwargs, {"qos":1, "retain":False})
        info.wait_for_publish.assert_called_with(timeout=2)
        bus.publish_audio("volume", 70)
        self.assertTrue(bus._client.publish.call_args.kwargs["retain"])
        self.assertEqual(bus.recent(), [])
        info.is_published.return_value = False
        with self.assertRaises(RuntimeError):
            bus.publish_audio("test_tts")
        with self.assertRaises(ValueError):
            bus.publish_audio("test_alarm")

    def test_duplicate_database_and_legacy_web_are_opt_in(self):
        root = Path(__file__).resolve().parents[1]
        services = yaml.safe_load((root / "pi4/compose.yml").read_text())["services"]
        enabled = {name for name, value in services.items() if not value.get("profiles")}
        self.assertEqual(enabled, {"mqtt", "automation"})
        self.assertNotIn("postgres", services["automation"]["depends_on"])
        installer = (root / "pi4/scripts/install.sh").read_text()
        self.assertIn("smarthome-postgres", installer)
        self.assertIn("smarthome-mqtt", installer)

    def test_mqtt_queue_is_bounded_and_rejections_visible(self):
        with patch("smarthome_vision.events.mqtt.Client") as factory:
            bus = EventBus({"enabled":True})
            bus.start()
            factory.return_value.max_queued_messages_set.assert_called_once_with(256)
            bus._connected = True
            factory.return_value.publish.return_value.rc = 15
            with patch("builtins.print"):
                bus.emit("dahua", "fall_confirmed")
            self.assertEqual(bus.rejected_events, 1)
            self.assertEqual(len(bus.recent()), 1)
