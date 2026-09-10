#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PI4_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PI4_DIR/.env"
COMPOSE_FILE="$PI4_DIR/compose.yml"

[[ -f "$ENV_FILE" ]] || { echo "Run install.sh first."; exit 1; }
event_id="manual-$(date +%s)"
payload="{\"schema_version\":\"1.1\",\"event_id\":\"$event_id\",\"timestamp\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"camera_id\":\"smoke-test\",\"event_type\":\"fall_confirmed\",\"confidence\":0.99,\"details\":{\"source\":\"smoke-test\"}}"

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" exec -T mqtt \
  mosquitto_pub -h 127.0.0.1 -t home/vision/events -q 1 -m "$payload"
sleep 2
web_port="$(sed -n 's/^WEB_PORT=//p' "$ENV_FILE")"
curl -fsS "http://127.0.0.1:${web_port:-8081}/api/overview"
echo
echo "Smoke event sent. Cancel it from the dashboard after verifying the alarm."
