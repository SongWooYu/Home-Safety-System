from __future__ import annotations

import json
import os
import threading
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any

import paho.mqtt.client as mqtt


class EventBus:
    def __init__(self, config: dict[str, Any], max_events: int = 100):
        self._events: deque[dict[str, Any]] = deque(maxlen=max_events)
        self._lock = threading.Lock()
        self._config = config
        self._client: mqtt.Client | None = None
        self._connected = False

    def start(self) -> None:
        if not self._config.get("enabled", False):
            return

        try:
            try:
                client = mqtt.Client(
                    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
                    client_id="smarthome-vision-pi5",
                )
            except (AttributeError, TypeError):
                client = mqtt.Client(client_id="smarthome-vision-pi5")

            username = os.getenv("MQTT_USERNAME", "")
            password = os.getenv("MQTT_PASSWORD", "")
            if username:
                client.username_pw_set(username, password)

            client.on_connect = self._on_connect
            client.on_disconnect = self._on_disconnect
            client.connect_async(
                self._config.get("host", "192.168.1.10"),
                int(self._config.get("port", 1883)),
                keepalive=30,
            )
            client.loop_start()
            self._client = client
        except Exception:
            self._client = None
            self._connected = False

    def stop(self) -> None:
        if self._client is not None:
            self._client.loop_stop()
            self._client.disconnect()

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        self._connected = getattr(reason_code, "value", reason_code) == 0

    def _on_disconnect(self, client, userdata, disconnect_flags=None, reason_code=0, properties=None):
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def emit(
        self,
        camera_id: str,
        event_type: str,
        confidence: float | None = None,
        details: dict[str, Any] | None = None,
        *,
        publish: bool = True,
    ) -> dict[str, Any]:
        event = {
            "schema_version": "1.1",
            "event_id": uuid.uuid4().hex,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "camera_id": camera_id,
            "event_type": event_type,
            "confidence": round(confidence, 4) if confidence is not None else None,
            "details": details or {},
        }
        with self._lock:
            self._events.appendleft(event)

        if (
            publish
            and self._client is not None
            and self._connected
        ):
            self._client.publish(
                self._config.get("topic_events", "home/vision/events"),
                json.dumps(event, ensure_ascii=False),
                qos=1,
                retain=False,
            )
        return event

    def publish_status(self, camera_id: str, status: dict[str, Any]) -> None:
        if self._client is None or not self._connected:
            return
        prefix = self._config.get("topic_status_prefix", "home/vision/status")
        self._client.publish(
            f"{prefix}/{camera_id}",
            json.dumps(status, ensure_ascii=False),
            qos=0,
            retain=True,
        )

    def recent(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events)

