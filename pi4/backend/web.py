from __future__ import annotations

import hmac
import json
import os

import requests

from flask import Flask, Response, abort, jsonify, render_template, request, stream_with_context
from paho.mqtt.publish import single

from common import database_connection, wait_for_database


app = Flask(__name__, template_folder="templates")
wait_for_database()
VISION_BASE_URL = os.getenv("VISION_BASE_URL", "http://192.168.1.20:8080").rstrip("/")
VISION_CAMERAS = tuple(
    camera.strip()
    for camera in os.getenv("VISION_CAMERAS", "cam3,webcam,dahua").split(",")
    if camera.strip()
)
try:
    VISION_STREAM_FPS = min(15.0, max(1.0, float(os.getenv("VISION_STREAM_FPS", "8"))))
except ValueError:
    VISION_STREAM_FPS = 8.0


def json_value(value):
    return value if isinstance(value, dict) else json.loads(value)


@app.get("/")
def index():
    return render_template("index.html", vision_cameras=VISION_CAMERAS)


@app.get("/vision/stream/<camera_id>")
def vision_stream(camera_id: str):
    if camera_id not in VISION_CAMERAS:
        abort(404)
    try:
        upstream = requests.get(
            f"{VISION_BASE_URL}/stream/{camera_id}?fps={VISION_STREAM_FPS:g}",
            stream=True,
            timeout=(3, 15),
        )
        upstream.raise_for_status()
    except requests.RequestException as exc:
        return jsonify({"error": "Pi5 vision stream unavailable", "detail": str(exc)}), 502

    @stream_with_context
    def relay():
        try:
            for chunk in upstream.iter_content(chunk_size=64 * 1024):
                if chunk:
                    yield chunk
        except requests.RequestException:
            return
        finally:
            upstream.close()

    response = Response(
        relay(),
        content_type=upstream.headers.get(
            "Content-Type", "multipart/x-mixed-replace; boundary=frame"
        ),
    )
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    return response


@app.get("/api/vision/health")
def vision_health():
    try:
        upstream = requests.get(f"{VISION_BASE_URL}/health", timeout=3)
        upstream.raise_for_status()
        return jsonify({"connected": True, "upstream": upstream.json()})
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
    expected = os.environ.get("ADMIN_TOKEN", "")
    supplied = request.headers.get("X-Admin-Token", "")
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        return jsonify({"error": "관리 키가 필요합니다."}), 401
    payload = json.dumps(
        {"action": "cancel", "source": "pi4-dashboard"},
        ensure_ascii=False,
    )
    single(
        "home/safety/fall/command",
        payload=payload,
        qos=1,
        hostname=os.getenv("MQTT_HOST", "mqtt"),
        port=int(os.getenv("MQTT_PORT", "1883")),
    )
    return jsonify({"sent": True})
