from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "pi4" / "audio_alarm.py"
SPEC = importlib.util.spec_from_file_location("pi4_audio_alarm_for_test", MODULE_PATH)
audio_alarm = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(audio_alarm)


class Pi4AudioAlarmTest(unittest.TestCase):
    def test_parses_boolean_alarm_state(self):
        self.assertTrue(audio_alarm.parse_alarm_active('{"active": true}'))
        self.assertFalse(audio_alarm.parse_alarm_active('{"active": false}'))

    def test_rejects_invalid_or_ambiguous_payload(self):
        self.assertIsNone(audio_alarm.parse_alarm_active("not-json"))
        self.assertIsNone(audio_alarm.parse_alarm_active('{"active": "true"}'))
        self.assertIsNone(audio_alarm.parse_alarm_active("{}"))


if __name__ == "__main__":
    unittest.main()
