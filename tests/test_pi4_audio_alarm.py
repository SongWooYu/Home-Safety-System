from __future__ import annotations

import importlib.util
import unittest
import tempfile
import wave
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "pi4" / "audio_alarm.py"
SPEC = importlib.util.spec_from_file_location("pi4_audio_alarm_for_test", MODULE_PATH)
audio_alarm = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(audio_alarm)


class Pi4AudioAlarmTest(unittest.TestCase):
    def test_cached_natural_speech_is_used_without_synthesis(self):
        with tempfile.TemporaryDirectory() as directory:
            cached = Path(directory) / "cached.wav"
            target = Path(directory) / "play.wav"
            with wave.open(str(cached), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(48000)
                wav.writeframes(b"\x00\x00" * 4800)
            with patch.dict(audio_alarm.os.environ, {"ALARM_TTS_WAV":str(cached)}), \
                    patch.object(audio_alarm.subprocess, "run") as run:
                self.assertTrue(audio_alarm.generate_tts_wav(target, "낙상이 감지되었습니다."))
                run.assert_not_called()
            self.assertEqual(cached.read_bytes(), target.read_bytes())

    def test_parses_boolean_alarm_state(self):
        self.assertTrue(audio_alarm.parse_alarm_active('{"active": true}'))
        self.assertFalse(audio_alarm.parse_alarm_active('{"active": false}'))

    def test_rejects_invalid_or_ambiguous_payload(self):
        self.assertIsNone(audio_alarm.parse_alarm_active("not-json"))
        self.assertIsNone(audio_alarm.parse_alarm_active('{"active": "true"}'))
        self.assertIsNone(audio_alarm.parse_alarm_active("{}"))

    def test_parses_only_bounded_integer_volume(self):
        self.assertEqual(audio_alarm.parse_audio_volume('{"volume": 70}'), 70)
        self.assertIsNone(audio_alarm.parse_audio_volume('{"volume": 0}'))
        self.assertIsNone(audio_alarm.parse_audio_volume('{"volume": 59}'))
        self.assertEqual(audio_alarm.parse_audio_volume('{"volume": 60}'), 60)
        self.assertEqual(audio_alarm.parse_audio_volume('{"volume": 100}'), 100)
        self.assertIsNone(audio_alarm.parse_audio_volume('{"volume": 101}'))
        self.assertIsNone(audio_alarm.parse_audio_volume('{"volume": "70"}'))

    def test_accepts_only_fixed_tts_test_command(self):
        self.assertEqual(
            audio_alarm.parse_audio_command('{"action": "test_tts"}'),
            "test_tts",
        )
        self.assertIsNone(
            audio_alarm.parse_audio_command('{"action": "arbitrary_text"}')
        )
        self.assertIsNone(audio_alarm.parse_audio_command("not-json"))

    def test_splits_verbose_mqtt_line(self):
        self.assertEqual(
            audio_alarm.split_topic_payload(
                'home/safety/fall/alarm {"active": true}'
            ),
            ('home/safety/fall/alarm', '{"active": true}'),
        )
        self.assertIsNone(audio_alarm.split_topic_payload("invalid"))

    def test_subscribes_to_alarm_config_and_audio_commands(self):
        command = audio_alarm.subscriber_command()
        self.assertIn("home/safety/fall/alarm", command)
        self.assertIn("home/safety/fall/audio/config", command)
        self.assertIn("home/safety/fall/audio/command", command)
        self.assertIn("-v", command)


if __name__ == "__main__":
    unittest.main()
