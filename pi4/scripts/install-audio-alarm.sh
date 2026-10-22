#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
pi4_dir="$(cd "$script_dir/.." && pwd)"
service_user="${ALARM_SERVICE_USER:-pi}"

if ! command -v aplay >/dev/null 2>&1 \
  || ! command -v amixer >/dev/null 2>&1 \
  || ! command -v mosquitto_sub >/dev/null 2>&1 \
  || ! command -v espeak-ng >/dev/null 2>&1; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y \
    alsa-utils mosquitto-clients espeak-ng
fi

for command_name in python3 aplay amixer mosquitto_sub espeak-ng systemctl; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "Missing required command after package installation: $command_name" >&2
    exit 2
  }
done

id "$service_user" >/dev/null 2>&1 || {
  echo "Service user does not exist: $service_user" >&2
  exit 3
}

install -d -m 0755 /usr/local/lib/home-safety
install -m 0755 "$pi4_dir/audio_alarm.py" /usr/local/lib/home-safety/audio_alarm.py
if [[ -n "${ALARM_TTS_ASSET:-}" ]]; then
  [[ -f "$ALARM_TTS_ASSET" ]] || { echo "TTS WAV does not exist." >&2; exit 4; }
  install -d -m 0755 /usr/local/share/home-safety
  install -m 0644 "$ALARM_TTS_ASSET" /usr/local/share/home-safety/fall-detected-ko.wav
fi
install -m 0644 \
  "$pi4_dir/systemd/smarthome-audio-alarm.service" \
  /etc/systemd/system/smarthome-audio-alarm.service

if [[ ! -e /etc/default/smarthome-audio-alarm ]]; then
  install -m 0644 /dev/null /etc/default/smarthome-audio-alarm
fi

usermod -aG audio "$service_user"
systemctl daemon-reload
systemctl enable smarthome-audio-alarm.service
systemctl restart smarthome-audio-alarm.service
systemctl --no-pager --full status smarthome-audio-alarm.service
