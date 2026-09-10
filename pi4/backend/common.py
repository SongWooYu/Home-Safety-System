from __future__ import annotations

import json
import os
import time
from typing import Any

import paho.mqtt.client as mqtt
import psycopg


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS mqtt_message (
    id BIGSERIAL PRIMARY KEY,
    topic TEXT NOT NULL,
    payload JSONB NOT NULL,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS mqtt_message_received_at_idx
    ON mqtt_message (received_at DESC);
CREATE TABLE IF NOT EXISTS vision_event (
    event_id TEXT PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL,
    camera_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    confidence REAL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    received_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS vision_event_occurred_at_idx
    ON vision_event (occurred_at DESC);
CREATE TABLE IF NOT EXISTS vision_status (
    camera_id TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS safety_state (
    state_key TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""


def database_connection() -> psycopg.Connection:
    return psycopg.connect(
        host=os.getenv("POSTGRES_HOST", "postgres"),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        connect_timeout=5,
    )


def wait_for_database(attempts: int = 30) -> None:
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            with database_connection() as connection:
                connection.execute(SCHEMA_SQL)
            return
        except psycopg.Error as exc:
            last_error = exc
            time.sleep(2)
    raise RuntimeError("PostgreSQL did not become ready") from last_error


def mqtt_client(client_id: str) -> mqtt.Client:
    return mqtt.Client(
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id,
    )


def decode_payload(payload: bytes) -> dict[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
        return value if isinstance(value, dict) else {"value": value}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {"raw": payload.decode("utf-8", errors="replace")}
