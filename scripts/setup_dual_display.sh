#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -ne 0 ]] || {
  echo "Run this as the desktop user pi, without sudo." >&2
  exit 1
}

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
kanshi_dir="/home/pi/.config/kanshi"
labwc_dir="/home/pi/.config/labwc"
user_unit_dir="/home/pi/.config/systemd/user"
backup_suffix="$(date +%Y%m%d-%H%M%S)"

install -d -m 0755 "$kanshi_dir" "$labwc_dir" "$user_unit_dir"

if [[ -s "$kanshi_dir/config" ]] && ! cmp -s "$repo_dir/config/display/kanshi.config" "$kanshi_dir/config"; then
  cp -a "$kanshi_dir/config" "$kanshi_dir/config.backup-$backup_suffix"
fi
install -m 0644 "$repo_dir/config/display/kanshi.config" "$kanshi_dir/config"

if [[ ! -f "$labwc_dir/rc.xml" ]]; then
  cp /etc/xdg/labwc/rc.xml "$labwc_dir/rc.xml"
fi
if ! grep -q 'home-safety-demo-display' "$labwc_dir/rc.xml"; then
  temporary_rc="$(mktemp /tmp/home-safety-labwc.XXXXXX)"
  awk '
    /<\/windowRules>/ && !added {
      print "    <!-- home-safety-demo-display -->"
      print "    <windowRule identifier=\"HomeSafetyDemo\" matchOnce=\"true\">"
      print "      <skipTaskbar>yes</skipTaskbar>"
      print "      <skipWindowSwitcher>yes</skipWindowSwitcher>"
      print "      <action name=\"MoveToOutput\" output=\"HDMI-A-2\" />"
      print "      <action name=\"ToggleFullscreen\" />"
      print "    </windowRule>"
      added=1
    }
    { print }
  ' "$labwc_dir/rc.xml" > "$temporary_rc"
  cp -a "$labwc_dir/rc.xml" "$labwc_dir/rc.xml.backup-$backup_suffix"
  install -m 0644 "$temporary_rc" "$labwc_dir/rc.xml"
  rm -f -- "$temporary_rc"
fi

install -m 0644 \
  "$repo_dir/config/display/home-safety-demo-display.service" \
  "$user_unit_dir/home-safety-demo-display.service"

systemctl --user daemon-reload
systemctl --user enable --now home-safety-demo-display.service
pkill -HUP -x kanshi 2>/dev/null || true
labwc --reconfigure 2>/dev/null || true

echo "Dual-display demo is configured."
echo "HDMI-A-1: Raspberry Pi OS desktop"
echo "HDMI-A-2: http://127.0.0.1:8080 full-screen demo when both outputs are connected"
