#!/usr/bin/env python3
"""Play a Pi4 host alarm while the retained MQTT fall alarm is active."""

from __future__ import annotations

import json
import logging
import math
import os
import signal
import struct
import subprocess
import threading
import time
import wave
from pathlib import Path


LOG = logging.getLogger("smarthome-audio-alarm")


def parse_alarm_active(raw: str) -> bool | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    active = payload.get("active")
    return active if isinstance(active, bool) else None


def generate_alarm_wav(path: Path, sample_rate: int = 48000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pattern = (
        (880.0, 0.28),
        (0.0, 0.12),
        (1046.5, 0.28),
        (0.0, 0.72),
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


class AlarmPlayer:
    def __init__(self, device: str, wav_path: Path):
        self.device = device
        self.wav_path = wav_path
        self._active = threading.Event()
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._process: subprocess.Popen | None = None
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

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self._active.wait(0.2):
                continue
            try:
                process = subprocess.Popen(
                    ["aplay", "-q", "-D", self.device, str(self.wav_path)],
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
            except OSError as exc:
                LOG.error("could not start aplay: %s", exc)
                self._stop.wait(2.0)
            finally:
                with self._lock:
                    self._process = None


def subscriber_command() -> list[str]:
    return [
        "mosquitto_sub",
        "-h",
        os.getenv("MQTT_HOST", "127.0.0.1"),
        "-p",
        os.getenv("MQTT_PORT", "1883"),
        "-t",
        os.getenv("ALARM_TOPIC", "home/safety/fall/alarm"),
        "-q",
        "1",
    ]


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    wav_path = Path(os.getenv("ALARM_WAV_PATH", "/run/smarthome-audio-alarm/alarm.wav"))
    generate_alarm_wav(wav_path)
    player = AlarmPlayer(
        os.getenv("ALARM_AUDIO_DEVICE", "plughw:CARD=Headphones,DEV=0"),
        wav_path,
    )
    stopping = threading.Event()

    def stop_service(signum, frame):
        del signum, frame
        stopping.set()

    signal.signal(signal.SIGTERM, stop_service)
    signal.signal(signal.SIGINT, stop_service)

    try:
        while not stopping.is_set():
            command = subscriber_command()
            LOG.info("subscribing to MQTT fall alarm")
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
                active = parse_alarm_active(line.strip())
                if active is None:
                    LOG.warning("ignored invalid alarm payload")
                    continue
                player.set_active(active)

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
