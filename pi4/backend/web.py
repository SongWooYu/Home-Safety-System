from __future__ import annotations

import hmac
import json
import os

import requests

from flask import Flask, jsonify, render_template, request
from paho.mqtt.publish import single

from common import database_connection, wait_for_database


app = Flask(__name__, template_folder="templates")
wait_for_database()
VISION_API_URL = os.getenv(
    "VISION_API_URL", os.getenv("VISION_BASE_URL", "http://192.168.1.20:8080")
).rstrip("/")
WEBRTC_BASE_URL = os.getenv("WEBRTC_BASE_URL", "http://192.168.1.20:8889").rstrip("/")
WEBRTC_CAMERAS = tuple(
    camera.strip()
    for camera in os.getenv(
        "WEBRTC_CAMERAS", os.getenv("VISION_CAMERAS", "cam3,dahua")
    ).split(",")
    if camera.strip()
)
WEBRTC_PATHS = {
    camera_id: path
    for camera_id, separator, path in (
        item.strip().partition("=")
        for item in os.getenv(
            "WEBRTC_PATHS", "cam3=cam3,dahua=dahuaclean"
        ).split(",")
    )
    if separator and camera_id and path
}
ALARM_COMMAND_TOPIC = "home/safety/fall/command"
AUDIO_CONFIG_TOPIC = "home/safety/fall/audio/config"


def json_value(value):
    return value if isinstance(value, dict) else json.loads(value)


def admin_authorized() -> bool:
    expected = os.environ.get("ADMIN_TOKEN", "")
    supplied = request.headers.get("X-Admin-Token", "")
    return bool(expected and supplied and hmac.compare_digest(expected, supplied))


def publish_alarm_command(action: str) -> None:
    single(
        ALARM_COMMAND_TOPIC,
        payload=json.dumps(
            {"action": action, "source": "pi4-dashboard"},
            ensure_ascii=False,
        ),
        qos=1,
        hostname=os.getenv("MQTT_HOST", "mqtt"),
        port=int(os.getenv("MQTT_PORT", "1883")),
    )


@app.get("/")
def index():
    return render_template(
        "index.html",
        vision_cameras=WEBRTC_CAMERAS,
        webrtc_base_url=WEBRTC_BASE_URL,
        webrtc_paths=WEBRTC_PATHS,
    )


@app.get("/api/vision/health")
def vision_health():
    try:
        upstream = requests.get(f"{VISION_API_URL}/health", timeout=3)
        upstream.raise_for_status()
        health_camera = "dahua" if "dahua" in WEBRTC_CAMERAS else WEBRTC_CAMERAS[0]
        health_path = WEBRTC_PATHS.get(health_camera, health_camera)
        media = requests.get(f"{WEBRTC_BASE_URL}/{health_path}", timeout=3)
        media.raise_for_status()
        return jsonify(
            {"connected": True, "upstream": upstream.json(), "webrtc": True}
        )
    except (requests.RequestException, ValueError) as exc:
        return jsonify({"connected": False, "error": str(exc)}), 503


@app.get("/health")
def health():
    try:
        with database_connection() as connection:
            connection.execute("SELECT 1").fetchone()
        return jsonify({"status": "ok"})
    except Exception as exc:
        return jsonify({"status": "degraded", "error": str(exc)}), 503


@app.get("/api/overview")
def overview():
    with database_connection() as connection:
        statuses = connection.execute(
            "SELECT camera_id, payload, updated_at FROM vision_status ORDER BY camera_id"
        ).fetchall()
        events = connection.execute(
            """
            SELECT event_id, occurred_at, camera_id, event_type, confidence, details
            FROM vision_event ORDER BY occurred_at DESC LIMIT 50
            """
        ).fetchall()
        state = connection.execute(
            "SELECT payload, updated_at FROM safety_state WHERE state_key = 'fall'"
        ).fetchone()
    return jsonify(
        {
            "cameras": [
                {
                    "camera_id": row[0],
                    "status": json_value(row[1]),
                    "updated_at": row[2].isoformat(),
                }
                for row in statuses
            ],
            "events": [
                {
                    "event_id": row[0],
                    "timestamp": row[1].isoformat(),
                    "camera_id": row[2],
                    "event_type": row[3],
                    "confidence": row[4],
                    "details": json_value(row[5]),
                }
                for row in events
            ],
            "fall": (
                {"status": json_value(state[0]), "updated_at": state[1].isoformat()}
                if state
                else None
            ),
        }
    )


@app.post("/api/alarm/cancel")
def cancel_alarm():
    if not admin_authorized():
        return jsonify({"error": "관리 키가 필요합니다."}), 401
    publish_alarm_command("cancel")
    return jsonify({"sent": True, "state": "cancelled"})


@app.post("/api/alarm/test")
def test_alarm():
    if not admin_authorized():
        return jsonify({"error": "관리 키가 필요합니다."}), 401
    publish_alarm_command("test_alarm")
    return jsonify({"sent": True, "state": "alarm"})


@app.post("/api/alarm/volume")
def set_alarm_volume():
    if not admin_authorized():
        return jsonify({"error": "관리 키가 필요합니다."}), 401
    payload = request.get_json(silent=True) or {}
    try:
        volume = int(payload.get("volume"))
    except (TypeError, ValueError):
        return jsonify({"error": "음량은 0~100 정수여야 합니다."}), 400
    if not 0 <= volume <= 100:
        return jsonify({"error": "음량은 0~100 범위여야 합니다."}), 400
    single(
        AUDIO_CONFIG_TOPIC,
        payload=json.dumps({"volume": volume}, ensure_ascii=False),
        qos=1,
        retain=True,
        hostname=os.getenv("MQTT_HOST", "mqtt"),
        port=int(os.getenv("MQTT_PORT", "1883")),
    )
    return jsonify({"sent": True, "volume": volume})
