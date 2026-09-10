from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timezone

from psycopg.types.json import Jsonb

from common import database_connection, decode_payload, mqtt_client, wait_for_database


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("collector")
EVENT_TOPIC = "home/vision/events"
STATUS_PREFIX = "home/vision/status/"
STATE_TOPIC = "home/safety/fall/state"


def store_message(topic: str, payload: dict, raw: bytes) -> None:
    with database_connection() as connection:
        if not topic.startswith(STATUS_PREFIX):
            connection.execute(
                "INSERT INTO mqtt_message(topic, payload) VALUES (%s, %s)",
                (topic, Jsonb(payload)),
            )
        if topic == EVENT_TOPIC:
            event_id = str(payload.get("event_id") or hashlib.sha256(raw).hexdigest())
            occurred_at = payload.get("timestamp") or datetime.now(timezone.utc).isoformat()
            connection.execute(
                """
                INSERT INTO vision_event(
                    event_id, occurred_at, camera_id, event_type, confidence, details
                ) VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (event_id) DO NOTHING
                """,
                (
                    event_id,
                    occurred_at,
                    str(payload.get("camera_id", "unknown")),
                    str(payload.get("event_type", "unknown")),
                    payload.get("confidence"),
                    Jsonb(payload.get("details") or {}),
                ),
            )
        elif topic.startswith(STATUS_PREFIX):
            camera_id = topic.removeprefix(STATUS_PREFIX)
            connection.execute(
                """
                INSERT INTO vision_status(camera_id, payload, updated_at)
                VALUES (%s, %s, now())
                ON CONFLICT (camera_id) DO UPDATE
                SET payload = EXCLUDED.payload, updated_at = now()
                """,
                (camera_id, Jsonb(payload)),
            )
        elif topic == STATE_TOPIC:
            connection.execute(
                """
                INSERT INTO safety_state(state_key, payload, updated_at)
                VALUES ('fall', %s, now())
                ON CONFLICT (state_key) DO UPDATE
                SET payload = EXCLUDED.payload, updated_at = now()
                """,
                (Jsonb(payload),),
            )


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        client.subscribe("home/#", qos=1)
        LOG.info("subscribed to home/#")
    else:
        LOG.error("MQTT connection failed: %s", reason_code)


def on_message(client, userdata, message):
    payload = decode_payload(message.payload)
    try:
        store_message(message.topic, payload, message.payload)
    except Exception:
        LOG.exception("could not store MQTT message on %s", message.topic)


def main() -> None:
    wait_for_database()
    client = mqtt_client("home-safety-pi4-collector")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(os.getenv("MQTT_HOST", "mqtt"), int(os.getenv("MQTT_PORT", "1883")), 30)
    LOG.info("collector started")
    client.loop_forever(retry_first_connection=True)


if __name__ == "__main__":
    main()
