#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }
[[ "$(uname -m)" == "aarch64" ]] || { echo "This installer expects aarch64." >&2; exit 2; }

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
version="${MEDIAMTX_VERSION:-1.21.0}"
archive="mediamtx_v${version}_linux_arm64.tar.gz"
base_url="https://github.com/bluenviron/mediamtx/releases/download/v${version}"
tmp_dir="$(mktemp -d /tmp/home-safety-mediamtx.XXXXXX)"
trap 'rm -rf -- "$tmp_dir"' EXIT

for command_name in curl sha256sum tar ffmpeg systemctl; do
  command -v "$command_name" >/dev/null 2>&1 || {
    echo "Missing required command: $command_name" >&2
    exit 3
  }
done

curl -fL --retry 3 -o "$tmp_dir/$archive" "$base_url/$archive"
curl -fL --retry 3 -o "$tmp_dir/checksums.sha256" "$base_url/checksums.sha256"
expected_line="$(grep "[ *]$archive$" "$tmp_dir/checksums.sha256")"
[[ -n "$expected_line" ]] || { echo "Checksum for $archive not found." >&2; exit 4; }
printf '%s\n' "$expected_line" | (cd "$tmp_dir" && sha256sum -c -)
tar -xzf "$tmp_dir/$archive" -C "$tmp_dir" mediamtx
install -m 0755 "$tmp_dir/mediamtx" /usr/local/bin/mediamtx

install -m 0644 "$repo_dir/config/systemd/smarthome-mediamtx.service" /etc/systemd/system/smarthome-mediamtx.service
if [[ ! -e /etc/default/smarthome-webrtc ]]; then
  install -m 0644 "$repo_dir/config/webrtc.env" /etc/default/smarthome-webrtc
fi

for camera_id in cam3 webcam dahua; do
  systemctl disable --now "smarthome-webrtc-publisher@${camera_id}.service" 2>/dev/null || true
done
rm -f /etc/systemd/system/smarthome-webrtc-publisher@.service
systemctl daemon-reload
systemctl enable smarthome-mediamtx.service
systemctl restart smarthome-mediamtx.service

for _ in $(seq 1 20); do
  if curl -fsSL http://127.0.0.1:8889/cam3 >/dev/null; then
    echo "WebRTC gateway ready: http://192.168.1.20:8889/cam3"
    exit 0
  fi
  sleep 1
done

echo "Services started but the WebRTC page is not ready." >&2
systemctl --no-pager --full status smarthome-mediamtx.service || true
exit 5
