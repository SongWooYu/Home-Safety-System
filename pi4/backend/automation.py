from __future__ import annotations

import json
import logging
import os
import threading
import time
from functools import wraps
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
test_deadline = None
state_lock = threading.RLock()


def serialized(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        with state_lock:
            return function(*args, **kwargs)
    return wrapped


@serialized
def expire_test(client):
    """Receiver-side deadline survives a Pi5 disconnect or browser close."""
    global test_deadline
    if test_deadline is not None and time.monotonic() >= test_deadline:
        test_deadline = None
        camera_states["manual-test"] = "normal"
        state = "alarm" if "confirmed" in camera_states.values() else "suspected" if "suspected" in camera_states.values() else "normal"
        publish_state(client, state, "manual-test", "test-auto-clear")
        LOG.info("manual fall test expired; real camera states preserved")


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


@serialized
def handle_event(client, payload: dict) -> None:
    global cancelled, test_deadline
    event_id = str(payload.get("event_id", ""))
    if event_id and event_id in seen_event_ids:
        return
    if event_id:
        seen_event_ids.append(event_id)

    event_type = str(payload.get("event_type", ""))
    camera_id = str(payload.get("camera_id", "unknown"))
    if camera_id == "manual-test" and event_type in {"fall_suspected", "fall_confirmed"}:
        test_deadline = time.monotonic() + 30
    elif camera_id == "manual-test" and event_type == "fall_cleared":
        test_deadline = None
    if event_type == "fall_suspected":
        camera_states[camera_id] = "suspected"
        publish_state(client, "alarm" if "confirmed" in camera_states.values() else "suspected", camera_id, event_id)
    elif event_type == "fall_confirmed":
        camera_states[camera_id] = "confirmed"
        cancelled = False
        publish_state(client, "alarm", camera_id, event_id)
    elif event_type == "fall_cleared":
        camera_states[camera_id] = "normal"
        state = "alarm" if "confirmed" in camera_states.values() else "suspected" if "suspected" in camera_states.values() else "normal"
        publish_state(client, state, camera_id, event_id)


@serialized
def handle_command(client, payload: dict, raw: bytes) -> None:
    global cancelled, test_deadline
    action = str(payload.get("action") or raw.decode("utf-8", errors="ignore")).strip().lower()
    if action in {"cancel", "acknowledge"}:
        cancelled = True
        test_deadline = None
        for camera_id in camera_states:
            camera_states[camera_id] = "cancelled"
        publish_state(client, "cancelled")
    elif action in {"test", "test_alarm"}:
        cancelled = False
        camera_states["manual-test"] = "confirmed"
        test_deadline = time.monotonic() + 30
        publish_state(client, "alarm", "manual-test", "dashboard-test")


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        client.subscribe([(EVENT_TOPIC, 1), (COMMAND_TOPIC, 1)])
        LOG.info("automation subscribed")
    else:
        LOG.error("MQTT connection failed: %s", reason_code)


def on_message(client, userdata, message):
    if message.retain:
        return  # Never replay an old retained test/vision command.
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
    client.loop_start()
    try:
        while True:
            expire_test(client)
            time.sleep(0.5)
    finally:
        client.disconnect()
        client.loop_stop()


if __name__ == "__main__":
    main()
