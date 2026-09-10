#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PI4_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PI4_DIR/.env"
COMPOSE_FILE="$PI4_DIR/compose.yml"

[[ -f "$ENV_FILE" ]] || { echo "Run install.sh first."; exit 1; }
docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps
web_port="$(sed -n 's/^WEB_PORT=//p' "$ENV_FILE")"
curl -fsS "http://127.0.0.1:${web_port:-8081}/health"
echo
