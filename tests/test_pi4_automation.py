from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path


fake_common = types.ModuleType("common")
fake_common.decode_payload = lambda payload: json.loads(payload)
fake_common.mqtt_client = lambda client_id: None
fake_common.database_connection = lambda: None
fake_common.wait_for_database = lambda: None
sys.modules.setdefault("common", fake_common)

MODULE_PATH = Path(__file__).resolve().parents[1] / "pi4" / "backend" / "automation.py"
SPEC = importlib.util.spec_from_file_location("pi4_automation_for_test", MODULE_PATH)
automation = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(automation)


class FakeClient:
    def __init__(self):
        self.messages = []

    def publish(self, topic, payload, qos, retain):
        self.messages.append((topic, json.loads(payload), qos, retain))


class Pi4AutomationTest(unittest.TestCase):
    def setUp(self):
        automation.camera_states.clear()
        automation.cancelled = False
        self.client = FakeClient()

    def test_dashboard_test_alarm_and_cancel(self):
        automation.handle_command(
            self.client,
            {"action": "test_alarm"},
            b'{"action":"test_alarm"}',
        )

        self.assertEqual(automation.camera_states["manual-test"], "confirmed")
        alarm_messages = [
            payload
            for topic, payload, _, _ in self.client.messages
            if topic == automation.ALARM_TOPIC
        ]
        self.assertTrue(alarm_messages[-1]["active"])

        automation.handle_command(
            self.client,
            {"action": "cancel"},
            b'{"action":"cancel"}',
        )

        self.assertEqual(automation.camera_states["manual-test"], "cancelled")
        alarm_messages = [
            payload
            for topic, payload, _, _ in self.client.messages
            if topic == automation.ALARM_TOPIC
        ]
        self.assertFalse(alarm_messages[-1]["active"])


if __name__ == "__main__":
    unittest.main()
