#!/usr/bin/env bash
set -euo pipefail

demo_url="${HOME_SAFETY_DEMO_URL:-http://127.0.0.1:8080}"
chromium_binary="/usr/lib/chromium/chromium"
profile_dir="/home/pi/.config/chromium-home-safety-demo"

command -v wlr-randr >/dev/null 2>&1 || {
  echo "wlr-randr is required." >&2
  exit 1
}
[[ -x "$chromium_binary" ]] || {
  echo "Chromium binary not found: $chromium_binary" >&2
  exit 1
}

# HDMI-A-2 is always the demonstration output, even when it is the only display.
while true; do
  outputs="$(wlr-randr 2>/dev/null || true)"
  if grep -q '^HDMI-A-2 ' <<<"$outputs"; then
    break
  fi
  sleep 2
done

# Wait for the local AI dashboard instead of showing Chromium's error page at boot.
until curl -fsS --max-time 2 "${demo_url%/}/health" >/dev/null; do
  sleep 2
done

if pgrep -u "$(id -u)" -f -- "--user-data-dir=${profile_dir}" >/dev/null; then
  exit 0
fi

exec "$chromium_binary" \
  --ozone-platform=wayland \
  --class=HomeSafetyDemo \
  --user-data-dir="$profile_dir" \
  --app="$demo_url" \
  --no-first-run \
  --no-default-browser-check \
  --noerrdialogs \
  --disable-session-crashed-bubble \
  --disable-features=Translate \
  --autoplay-policy=no-user-gesture-required
