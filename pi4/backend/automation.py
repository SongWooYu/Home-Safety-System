from __future__ import annotations

import json
import logging
import os
from collections import deque
from datetime import datetime, timezone

from common import decode_payload, mqtt_client


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
LOG = logging.getLogger("automation")
EVENT_TOPIC = "home/vision/events"
COMMAND_TOPIC = "home/safety/fall/command"
STATE_TOPIC = "home/safety/fall/state"
ALARM_TOPIC = "home/safety/fall/alarm"

camera_states: dict[str, str] = {}
seen_event_ids: deque[str] = deque(maxlen=500)
cancelled = False


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def publish_state(client, state: str, camera_id: str | None = None, event_id: str | None = None) -> None:
    payload = {
        "schema_version": "1.0",
        "timestamp": now(),
        "state": state,
        "camera_id": camera_id,
        "event_id": event_id,
        "camera_states": camera_states,
    }
    client.publish(STATE_TOPIC, json.dumps(payload, ensure_ascii=False), qos=1, retain=True)
    alarm = state == "alarm"
    client.publish(
        ALARM_TOPIC,
        json.dumps({"active": alarm, "timestamp": payload["timestamp"], "camera_id": camera_id}),
        qos=1,
        retain=True,
    )
    LOG.info("fall safety state=%s camera=%s", state, camera_id)


def handle_event(client, payload: dict) -> None:
    global cancelled
    event_id = str(payload.get("event_id", ""))
    if event_id and event_id in seen_event_ids:
        return
    if event_id:
        seen_event_ids.append(event_id)

    event_type = str(payload.get("event_type", ""))
    camera_id = str(payload.get("camera_id", "unknown"))
    if event_type == "fall_suspected":
        camera_states[camera_id] = "suspected"
        if not any(value == "confirmed" for value in camera_states.values()):
            publish_state(client, "suspected", camera_id, event_id)
    elif event_type == "fall_confirmed":
        camera_states[camera_id] = "confirmed"
        cancelled = False
        publish_state(client, "alarm", camera_id, event_id)
    elif event_type == "fall_cleared":
        camera_states[camera_id] = "normal"
        if not any(value == "confirmed" for value in camera_states.values()):
            publish_state(client, "normal", camera_id, event_id)


def handle_command(client, payload: dict, raw: bytes) -> None:
    global cancelled
    action = str(payload.get("action") or raw.decode("utf-8", errors="ignore")).strip().lower()
    if action in {"cancel", "acknowledge"}:
        cancelled = True
        for camera_id in camera_states:
            camera_states[camera_id] = "cancelled"
        publish_state(client, "cancelled")
    elif action in {"test", "test_alarm"}:
        cancelled = False
        camera_states["manual-test"] = "confirmed"
        publish_state(client, "alarm", "manual-test", "dashboard-test")


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        client.subscribe([(EVENT_TOPIC, 1), (COMMAND_TOPIC, 1)])
        LOG.info("automation subscribed")
    else:
        LOG.error("MQTT connection failed: %s", reason_code)


def on_message(client, userdata, message):
    payload = decode_payload(message.payload)
    if message.topic == EVENT_TOPIC:
        handle_event(client, payload)
    elif message.topic == COMMAND_TOPIC:
        handle_command(client, payload, message.payload)


def main() -> None:
    client = mqtt_client("home-safety-pi4-automation")
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(os.getenv("MQTT_HOST", "mqtt"), int(os.getenv("MQTT_PORT", "1883")), 30)
    LOG.info("automation started")
    client.loop_forever(retry_first_connection=True)


if __name__ == "__main__":
    main()
