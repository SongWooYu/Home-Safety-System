#!/usr/bin/env python3
"""Play a Pi4 host tone and Korean TTS while the MQTT fall alarm is active."""

from __future__ import annotations

import json
import logging
import math
import os
import queue
import shutil
import signal
import struct
import subprocess
import threading
import wave
from pathlib import Path


LOG = logging.getLogger("smarthome-audio-alarm")


def parse_alarm_active(raw: str) -> bool | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    active = payload.get("active")
    return active if isinstance(active, bool) else None


def parse_audio_volume(raw: str) -> int | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    volume = payload.get("volume")
    if isinstance(volume, bool) or not isinstance(volume, int):
        return None
    return volume if 0 <= volume <= 100 else None


def parse_audio_command(raw: str) -> str | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    action = payload.get("action")
    return action if action == "test_tts" else None


def split_topic_payload(line: str) -> tuple[str, str] | None:
    topic, separator, payload = line.strip().partition(" ")
    if not separator or not topic or not payload:
        return None
    return topic, payload


def generate_alarm_wav(path: Path, sample_rate: int = 48000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pattern = (
        (880.0, 0.28),
        (0.0, 0.12),
        (1046.5, 0.28),
        (0.0, 0.35),
    )
    amplitude = 0.18 * 32767
    samples: list[bytes] = []
    phase = 0.0
    for frequency, duration in pattern:
        count = int(sample_rate * duration)
        for index in range(count):
            if frequency == 0.0:
                value = 0
            else:
                envelope = min(1.0, index / 480.0, (count - index) / 480.0)
                value = int(amplitude * envelope * math.sin(phase))
                phase += 2.0 * math.pi * frequency / sample_rate
            samples.append(struct.pack("<h", value))

    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        output.writeframes(b"".join(samples))


def generate_tts_wav(path: Path, text: str) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Generate natural speech once during setup; alarm playback stays offline.
    cached = Path(os.getenv("ALARM_TTS_WAV", "/usr/local/share/home-safety/fall-detected-ko.wav"))
    if cached.is_file():
        try:
            with wave.open(str(cached), "rb") as audio:
                if (audio.getnchannels() not in (1, 2) or audio.getsampwidth() != 2
                        or not 0 < audio.getnframes() / audio.getframerate() <= 30):
                    raise ValueError("expected 16-bit PCM speech, at most 30 seconds")
            shutil.copyfile(cached, path)
            LOG.info("using cached natural TTS: %s", cached.name)
            return True
        except (OSError, EOFError, wave.Error, ValueError) as exc:
            LOG.error("cached TTS invalid, falling back to espeak-ng: %s", exc)
    try:
        completed = subprocess.run(
            [
                "espeak-ng",
                "-v",
                os.getenv("ALARM_TTS_VOICE", "ko"),
                "-s",
                os.getenv("ALARM_TTS_SPEED", "145"),
                "-a",
                "170",
                "-w",
                str(path),
                text,
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        LOG.error("could not generate TTS: %s", exc)
        return False
    if completed.returncode != 0:
        LOG.error("espeak-ng failed: %s", completed.stderr.strip())
        return False
    return path.is_file() and path.stat().st_size > 44


class AlarmPlayer:
    def __init__(
        self,
        device: str,
        playlist: list[Path],
        mixer_card: str,
        mixer_control: str,
        volume: int,
        repeat_pause: float = 1.2,
    ):
        self.device = device
        self.playlist = tuple(playlist)
        self.mixer_card = mixer_card
        self.mixer_control = mixer_control
        self.repeat_pause = max(0.0, repeat_pause)
        self._active = threading.Event()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._one_shots: queue.Queue[Path] = queue.Queue(maxsize=1)
        self._process: subprocess.Popen | None = None
        self._volume = -1
        self.set_volume(volume)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def set_active(self, active: bool) -> None:
        if active == self._active.is_set():
            return
        if active:
            LOG.warning("fall alarm audio activated")
            self._active.set()
        else:
            LOG.info("fall alarm audio stopped")
            self._active.clear()
            self._terminate_playback()

    def play_once(self, wav_path: Path) -> None:
        if not wav_path.is_file():
            LOG.error("one-shot audio file does not exist: %s", wav_path)
            return
        if self._active.is_set():
            LOG.info("TTS test skipped while real alarm is active")
            return
        try:
            self._one_shots.put_nowait(wav_path)
        except queue.Full:
            LOG.info("TTS test already queued")
            return
        LOG.info("queued one-shot TTS playback")

    def set_volume(self, volume: int) -> bool:
        volume = min(100, max(0, int(volume)))
        if volume == self._volume:
            return True
        try:
            completed = subprocess.run(
                [
                    "amixer",
                    "-q",
                    "-c",
                    self.mixer_card,
                    "sset",
                    self.mixer_control,
                    f"{volume}%",
                ],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            LOG.error("could not set alarm volume: %s", exc)
            return False
        if completed.returncode != 0:
            LOG.error("amixer failed: %s", completed.stderr.strip())
            return False
        self._volume = volume
        LOG.info("alarm volume set to %s%%", volume)
        return True

    def close(self) -> None:
        self._stop.set()
        self._active.clear()
        self._terminate_playback()
        self._thread.join(timeout=2.0)

    def _terminate_playback(self) -> None:
        with self._lock:
            process = self._process
        if process is not None and process.poll() is None:
            process.terminate()

    def _play(self, wav_path: Path) -> bool:
        try:
            process = subprocess.Popen(
                ["aplay", "-q", "-D", self.device, str(wav_path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
            with self._lock:
                self._process = process
            _, stderr = process.communicate()
            if process.returncode not in (0, -signal.SIGTERM):
                LOG.error("aplay failed (%s): %s", process.returncode, stderr.strip())
                self._stop.wait(1.0)
            return process.returncode == 0
        except OSError as exc:
            LOG.error("could not start aplay: %s", exc)
            self._stop.wait(2.0)
            return False
        finally:
            with self._lock:
                self._process = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                one_shot = self._one_shots.get_nowait()
            except queue.Empty:
                one_shot = None
            if one_shot is not None:
                if not self._active.is_set() and self._play(one_shot):
                    LOG.info("one-shot TTS playback completed")
                continue
            if not self._active.wait(0.2):
                continue
            for wav_path in self.playlist:
                if self._stop.is_set() or not self._active.is_set():
                    break
                self._play(wav_path)
            if self._active.is_set():
                self._stop.wait(self.repeat_pause)


def subscriber_command() -> list[str]:
    return [
        "mosquitto_sub",
        "-h",
        os.getenv("MQTT_HOST", "127.0.0.1"),
        "-p",
        os.getenv("MQTT_PORT", "1883"),
        "-t",
        os.getenv("ALARM_TOPIC", "home/safety/fall/alarm"),
        "-t",
        os.getenv("AUDIO_CONFIG_TOPIC", "home/safety/fall/audio/config"),
        "-t",
        os.getenv("AUDIO_COMMAND_TOPIC", "home/safety/fall/audio/command"),
        "-q",
        "1",
        "-v",
    ]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    runtime_dir = Path(
        os.getenv("ALARM_RUNTIME_DIR", "/run/smarthome-audio-alarm")
    )
    tone_path = runtime_dir / "alarm-tone.wav"
    speech_path = runtime_dir / "fall-detected-ko.wav"
    generate_alarm_wav(tone_path)
    playlist = [tone_path]
    tts_available = generate_tts_wav(
        speech_path,
        os.getenv("ALARM_TTS_TEXT", "낙상이 감지되었습니다."),
    )
    if tts_available:
        playlist.append(speech_path)

    player = AlarmPlayer(
        os.getenv("ALARM_AUDIO_DEVICE", "plughw:CARD=Headphones,DEV=0"),
        playlist,
        os.getenv("ALARM_MIXER_CARD", "0"),
        os.getenv("ALARM_MIXER_CONTROL", "PCM"),
        int(os.getenv("ALARM_VOLUME", "70")),
        float(os.getenv("ALARM_REPEAT_PAUSE", "1.2")),
    )
    stopping = threading.Event()
    alarm_topic = os.getenv("ALARM_TOPIC", "home/safety/fall/alarm")
    config_topic = os.getenv(
        "AUDIO_CONFIG_TOPIC",
        "home/safety/fall/audio/config",
    )
    command_topic = os.getenv(
        "AUDIO_COMMAND_TOPIC",
        "home/safety/fall/audio/command",
    )

    def stop_service(signum, frame):
        del signum, frame
        stopping.set()

    signal.signal(signal.SIGTERM, stop_service)
    signal.signal(signal.SIGINT, stop_service)

    try:
        while not stopping.is_set():
            command = subscriber_command()
            LOG.info("subscribing to MQTT fall alarm, audio config and commands")
            try:
                subscriber = subprocess.Popen(
                    command,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                )
            except OSError as exc:
                LOG.error("could not start mosquitto_sub: %s", exc)
                stopping.wait(3.0)
                continue

            assert subscriber.stdout is not None
            while not stopping.is_set():
                line = subscriber.stdout.readline()
                if not line:
                    break
                message = split_topic_payload(line)
                if message is None:
                    LOG.warning("ignored MQTT line without topic")
                    continue
                topic, raw = message
                if topic == alarm_topic:
                    active = parse_alarm_active(raw)
                    if active is None:
                        LOG.warning("ignored invalid alarm payload")
                        continue
                    player.set_active(active)
                elif topic == config_topic:
                    volume = parse_audio_volume(raw)
                    if volume is None:
                        LOG.warning("ignored invalid audio config payload")
                        continue
                    player.set_volume(volume)
                elif topic == command_topic:
                    action = parse_audio_command(raw)
                    if action is None:
                        LOG.warning("ignored invalid audio command payload")
                        continue
                    if tts_available:
                        player.play_once(speech_path)
                    else:
                        LOG.error("cannot play one-shot TTS because generation failed")

            subscriber.terminate()
            try:
                subscriber.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                subscriber.kill()
            if not stopping.is_set():
                LOG.warning("MQTT subscription ended; retrying")
                stopping.wait(3.0)
    finally:
        player.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
