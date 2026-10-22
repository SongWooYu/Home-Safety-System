#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PI4_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PI4_DIR/.env"
COMPOSE_FILE="$PI4_DIR/compose.yml"

[[ -f "$ENV_FILE" ]] || { echo "Run install.sh first."; exit 1; }
docker compose --profile standalone-db --profile legacy-web --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps -a
systemctl --no-pager status smarthome-audio-alarm.service sync-collaborator-smarthome.timer || true
echo "8081 is retired. Collaborator dashboard: http://192.168.1.10:8000 (not yet integrated)."
echo "Audio test controls: http://192.168.1.20:8080/#audio-test-panel"
