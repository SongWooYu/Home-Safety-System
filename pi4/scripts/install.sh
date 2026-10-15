#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PI4_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$PI4_DIR/.env"
COMPOSE_FILE="$PI4_DIR/compose.yml"
LEGACY_DIR=""
MIGRATE=false

usage() {
  echo "Usage: sudo ./pi4/scripts/install.sh [--migrate-legacy /opt/smarthome]"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --migrate-legacy)
      MIGRATE=true
      LEGACY_DIR="${2:-}"
      [[ -n "$LEGACY_DIR" ]] || { usage; exit 2; }
      shift 2
      ;;
    -h|--help) usage; exit 0 ;;
    *) usage; exit 2 ;;
  esac
done

[[ $EUID -eq 0 ]] || { echo "Run with sudo."; exit 1; }

OPERATOR_USER="${PI4_OPERATOR_USER:-${SUDO_USER:-pi}}"
id "$OPERATOR_USER" >/dev/null 2>&1 || {
  echo "Operator user does not exist: $OPERATOR_USER"
  exit 1
}
OPERATOR_GROUP="$(id -gn "$OPERATOR_USER")"

if ! command -v curl >/dev/null 2>&1 || ! command -v openssl >/dev/null 2>&1; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y curl openssl
fi
if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y docker.io docker-compose-v2
fi
systemctl enable --now docker

install -d -m 0755 /srv/smarthome-data
install -d -m 0755 "$PI4_DIR/runtime/mqtt/data"
install -d -m 0700 "$PI4_DIR/backups"

set_env() {
  local key="$1" value="$2" escaped
  escaped="$(printf '%s' "$value" | sed 's/[&|]/\\&/g')"
  sed -i "s|^$key=.*|$key=$escaped|" "$ENV_FILE"
}

ensure_env() {
  local key="$1" value="$2"
  if ! grep -q "^${key}=" "$ENV_FILE"; then
    printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
}

if [[ ! -f "$ENV_FILE" ]]; then
  cp "$PI4_DIR/.env.example" "$ENV_FILE"
  chmod 0600 "$ENV_FILE"
  set_env POSTGRES_PASSWORD "$(openssl rand -hex 24)"
  set_env ADMIN_TOKEN "$(openssl rand -hex 24)"
fi


ensure_env VISION_API_URL "http://192.168.1.20:8080"
ensure_env WEBRTC_BASE_URL "http://192.168.1.20:8889"
ensure_env WEBRTC_CAMERAS "cam3,dahua"
ensure_env WEBRTC_PATHS "cam3=cam3,dahua=dahuaclean"

# 2026-10-15: retire the ABKO webcam without overwriting custom camera lists.
if grep -qx 'WEBRTC_CAMERAS=cam3,webcam,dahua' "$ENV_FILE"; then
  set_env WEBRTC_CAMERAS "cam3,dahua"
fi
if grep -qx 'WEBRTC_PATHS=cam3=cam3,webcam=webcam,dahua=dahuaclean' "$ENV_FILE"; then
  set_env WEBRTC_PATHS "cam3=cam3,dahua=dahuaclean"
fi

# 운영 사용자에게만 compose/status 실행에 필요한 읽기 권한을 준다.
chown root:"$OPERATOR_GROUP" "$ENV_FILE"
chmod 0640 "$ENV_FILE"

legacy_pg=""
for candidate in smarthome_postgres postgres; do
  if docker inspect "$candidate" >/dev/null 2>&1; then
    legacy_pg="$candidate"
    break
  fi
done
legacy_mqtt=""
for candidate in smarthome_mosquitto mosquitto mqtt; do
  if docker inspect "$candidate" >/dev/null 2>&1; then
    legacy_mqtt="$candidate"
    break
  fi
done

if [[ -n "$legacy_pg$legacy_mqtt" && "$MIGRATE" != true ]]; then
  echo "A legacy MQTT/PostgreSQL stack was detected."
  echo "Nothing was stopped. Re-run explicitly:"
  echo "  sudo ./pi4/scripts/install.sh --migrate-legacy /opt/smarthome"
  exit 3
fi

if [[ "$MIGRATE" == true ]]; then
  [[ -d "$LEGACY_DIR" ]] || { echo "Legacy directory not found: $LEGACY_DIR"; exit 4; }

  if [[ -n "$legacy_pg" ]]; then
    legacy_user="$(docker inspect "$legacy_pg" --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^POSTGRES_USER=//p' | head -1)"
    legacy_db="$(docker inspect "$legacy_pg" --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^POSTGRES_DB=//p' | head -1)"
    legacy_password="$(docker inspect "$legacy_pg" --format '{{range .Config.Env}}{{println .}}{{end}}' | sed -n 's/^POSTGRES_PASSWORD=//p' | head -1)"
    [[ -n "$legacy_user" && -n "$legacy_db" && -n "$legacy_password" ]] || {
      echo "Could not read legacy PostgreSQL settings; migration stopped before changes."
      exit 5
    }
    set_env POSTGRES_USER "$legacy_user"
    set_env POSTGRES_DB "$legacy_db"
    set_env POSTGRES_PASSWORD "$legacy_password"

    backup_dir="/srv/smarthome-data/backups"
    install -d -m 0700 "$backup_dir"
    backup_file="$backup_dir/pre-git-migration-$(date +%Y%m%d-%H%M%S).sql"
    docker exec "$legacy_pg" pg_dumpall -U "$legacy_user" > "$backup_file"
    chmod 0600 "$backup_file"
    echo "Database backup created: $backup_file"
  fi

  for unit in smarthome-collector.service smarthome-automation.service smarthome-fakesensor.service collector.service automation.service fakesensor.service; do
    if systemctl list-unit-files "$unit" --no-legend 2>/dev/null | grep -q "$unit"; then
      systemctl disable --now "$unit"
    fi
  done

  legacy_compose=""
  for candidate in docker-compose.yml docker-compose.yaml compose.yml compose.yaml; do
    if [[ -f "$LEGACY_DIR/$candidate" ]]; then
      legacy_compose="$LEGACY_DIR/$candidate"
      break
    fi
  done
  if [[ -n "$legacy_compose" ]]; then
    docker compose -f "$legacy_compose" down
  else
    [[ -z "$legacy_mqtt" ]] || docker stop "$legacy_mqtt"
    [[ -z "$legacy_pg" ]] || docker stop "$legacy_pg"
  fi
  echo "Legacy application stopped; its directory and database files were not deleted."
fi

postgres_data="$(sed -n 's/^POSTGRES_DATA_DIR=//p' "$ENV_FILE")"
[[ -n "$postgres_data" && "$postgres_data" == /srv/smarthome-data/* ]] || {
  echo "POSTGRES_DATA_DIR must stay under /srv/smarthome-data."; exit 6;
}
install -d -m 0700 "$postgres_data"
chown 999:999 "$postgres_data" || true
chown 1883:1883 "$PI4_DIR/runtime/mqtt/data" || true

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" up -d --build

if [[ "${INSTALL_AUDIO_ALARM:-1}" == "1" ]]; then
  ALARM_SERVICE_USER="$OPERATOR_USER" "$SCRIPT_DIR/install-audio-alarm.sh"
fi

web_port="$(sed -n 's/^WEB_PORT=//p' "$ENV_FILE")"
web_port="${web_port:-8081}"
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$web_port/health" >/dev/null; then
    echo "Pi4 stack is ready: http://$(hostname -I | awk '{print $1}'):$web_port"
    echo "Admin token: sudo sed -n 's/^ADMIN_TOKEN=//p' $ENV_FILE"
    exit 0
  fi
  sleep 2
done

docker compose --env-file "$ENV_FILE" -f "$COMPOSE_FILE" ps
echo "Stack started but health check did not become ready. See: ./pi4/scripts/status.sh"
exit 7
