"""Optional collaborator-dashboard fall notices. No DB writes or alarm control.

Deploy beside /opt/smarthome/web/app.py; call install(app) once. Removing that
hook and the script tag disables this isolated module without a DB migration.
"""
import atexit
from collections import deque
from datetime import datetime, timezone
import json
import threading
import time
import uuid

from flask import jsonify, request


class FallNotices:
    def __init__(self):
        self.lock = threading.Lock()
        self.events = deque(maxlen=50)
        self.seen = deque(maxlen=256)
        self.sequence = 0
        self.epoch = uuid.uuid4().hex
        self.connected = False

    def ingest(self, raw, retained=False):
        if retained or len(raw) > 65536:
            return False
        try:
            event = json.loads(raw)
            if not isinstance(event, dict) or event.get("event_type") != "fall_confirmed":
                return False
            event_id = event.get("event_id")
            camera = event.get("camera_id")
            if not isinstance(event_id, str) or not 1 <= len(event_id) <= 128:
                return False
            if not isinstance(camera, str) or len(camera) > 80:
                return False
            timestamp = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                return False
            age = (datetime.now(timezone.utc) - timestamp).total_seconds()
            if not -30 <= age <= 120:
                return False  # Never replay old alarms on reconnect.
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
            return False
        with self.lock:
            if event_id in self.seen:
                return False
            self.seen.append(event_id)
            self.sequence += 1
            self.events.append({"sequence": self.sequence, "event_id": event_id,
                                "camera_id": camera, "timestamp": timestamp.isoformat(),
                                "received_at": time.time()})
        return True

    def snapshot(self, after=None, epoch=None):
        with self.lock:
            # First load/restart shows only recent arrivals, not stored history.
            selected = [dict(event) for event in self.events
                        if time.time() - event["received_at"] <= 30
                        and (epoch != self.epoch or after is None or event["sequence"] > after)]
            for event in selected:
                event.pop("received_at")
            return {"epoch": self.epoch, "cursor": self.sequence,
                    "connected": self.connected, "events": selected}


def install(app):
    if "home_safety_fall_notices" in app.extensions:
        return app.extensions["home_safety_fall_notices"]
    import paho.mqtt.client as mqtt
    notices = FallNotices()
    app.extensions["home_safety_fall_notices"] = notices

    @app.get("/api/fall-notices")
    def fall_notices():
        try:
            after = int(request.args["after"]) if "after" in request.args else None
        except ValueError:
            return jsonify(error="invalid cursor"), 400
        response = jsonify(notices.snapshot(after, request.args.get("epoch")))
        response.headers["Cache-Control"] = "no-store"
        return response

    client = mqtt.Client(client_id="pi4-fall-notice-" + uuid.uuid4().hex[:8])

    def connected(client, userdata, flags, rc):
        notices.connected = rc == 0
        if rc == 0:
            client.subscribe("home/vision/events", qos=1)

    def disconnected(client, userdata, rc):
        notices.connected = False

    client.on_connect = connected
    client.on_disconnect = disconnected
    client.on_message = lambda client, userdata, msg: notices.ingest(msg.payload, msg.retain)
    client.reconnect_delay_set(min_delay=1, max_delay=30)
    client.connect_async("127.0.0.1", 1883, keepalive=30)
    client.loop_start()

    def shutdown():
        client.disconnect()
        client.loop_stop()

    atexit.register(shutdown)
    return notices
