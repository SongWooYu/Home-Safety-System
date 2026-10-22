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
import re
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler, ProxyHandler
from urllib.error import HTTPError, URLError

from flask import Response, abort, jsonify, request, send_from_directory

PI5 = "http://192.168.1.20:8080"
MEDIA = "http://192.168.1.20:8889"
MEDIA_PATH = "/dahuaclean/whep"
REVIEW_PATH = "/api/fall-review/whep"
SESSION = re.compile(r"^[a-zA-Z0-9_-]{1,80}$")


def same_origin():
    if request.headers.get("Sec-Fetch-Site") == "cross-site":
        return False
    origin = request.headers.get("Origin")
    if not origin:
        return True
    scheme = request.scheme
    forwarded = request.headers.get("X-Forwarded-Proto", "")
    # The existing Cloudflare connector lives on Pi5, not on this Pi4.
    # Trust only its exact LAN address and expected public Host, not all LAN
    # peers or arbitrary X-Forwarded-Host supplied by clients.
    trusted = request.remote_addr in {"127.0.0.1", "::1"} or (
        request.remote_addr == "192.168.1.20" and request.host == "www.aihous.site")
    if trusted and forwarded in {"http", "https"}:
        scheme = forwarded
    try:
        source, target = urlsplit(origin), urlsplit(f"{scheme}://{request.host}")
        return (source.scheme in {"http", "https"} and source.scheme == target.scheme
                and not source.username and not source.password
                and not source.path and not source.query and not source.fragment
                and source.hostname == target.hostname
                and (source.port or (443 if source.scheme == "https" else 80))
                == (target.port or (443 if target.scheme == "https" else 80)))
    except ValueError:
        return False


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


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
            details = event.get("details")
            details = details if isinstance(details, dict) else {}
            snapshot = details.get("snapshot")
            snapshot_id = snapshot.get("id") if isinstance(snapshot, dict) else None
            has_snapshot = snapshot_id == event_id and re.fullmatch(r"[0-9a-f]{32}", event_id) is not None
        except (ValueError, TypeError, KeyError, AttributeError, UnicodeError):
            return False
        with self.lock:
            if event_id in self.seen:
                return False
            self.seen.append(event_id)
            self.sequence += 1
            self.events.append({"sequence": self.sequence, "event_id": event_id,
                                "camera_id": camera, "timestamp": timestamp.isoformat(),
                                "event_type": "fall_confirmed",
                                "test": details.get("test") is True,
                                "snapshot_available": has_snapshot,
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

    def history(self):
        with self.lock:
            events = []
            for event in reversed(self.events):
                item = dict(event)
                age = time.time() - item.pop("received_at")
                item["snapshot_available"] = item["snapshot_available"] and age < 3600
                events.append(item)
            return {"epoch": self.epoch, "connected": self.connected, "events": events,
                    "limit": 50, "snapshot_ttl_seconds": 3600, "persistent": False}


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

    @app.get("/api/fall-history")
    def fall_history():
        response = jsonify(notices.history())
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/fall-review")
    @app.get("/fall-review/assets/<name>")
    def fall_review(name="index.html"):
        if name not in {"index.html", "review.css", "review.js"}:
            abort(404)
        response = send_from_directory(Path(__file__).resolve().parent / "fall_review", name)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    status_lock = threading.Lock()
    status_cache = {"at": float("-inf"), "data": None}

    @app.get("/api/fall-review/current")
    def current_camera():
        # One small status request per second at most, regardless of viewers.
        # Never reuse a previous successful status after a failed refresh.
        with status_lock:
            if time.monotonic() - status_cache["at"] >= 1:
                try:
                    opener = build_opener(ProxyHandler({}), NoRedirect())
                    with opener.open(Request(PI5 + "/api/status"), timeout=2) as upstream:
                        body = upstream.read(131073)
                        if len(body) > 131072:
                            raise ValueError("status too large")
                        payload = json.loads(body)
                    camera = next(c for c in payload["cameras"] if c.get("camera_id") == "dahua")
                    age = camera.get("last_frame_age")
                    fresh = (camera.get("online") is True and isinstance(age, (int, float))
                             and 0 <= age <= 3 and not camera.get("error"))
                    analysis = camera.get("analysis") or {}
                    status_cache["data"] = {
                        "available": fresh, "online": camera.get("online") is True,
                        "fall_state": camera.get("fall_state") if fresh else "unknown",
                        "analysis_label": analysis.get("label", ""),
                        "analysis_detail": analysis.get("detail", ""),
                        "person_count": camera.get("person_count") if fresh else None,
                        "frame_age_seconds": age, "checked_at": datetime.now(timezone.utc).isoformat(),
                        "mqtt_connected": payload.get("mqtt_connected") is True,
                    }
                except (HTTPError, URLError, OSError, TimeoutError, ValueError, KeyError, TypeError, AttributeError, StopIteration):
                    status_cache["data"] = {"available": False, "fall_state": "unknown",
                                            "checked_at": datetime.now(timezone.utc).isoformat()}
                status_cache["at"] = time.monotonic()
            response = jsonify(status_cache["data"])
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.route(REVIEW_PATH, methods=["POST"])
    @app.route(REVIEW_PATH + "/<session_id>", methods=["DELETE"])
    def review_whep(session_id=None):
        # SDP/session control only: no video, MJPEG, RTSP, or encoding on Pi4.
        if session_id and not SESSION.fullmatch(session_id):
            abort(404)
        if not same_origin():
            abort(403)
        if request.method == "POST":
            if request.mimetype != "application/sdp":
                abort(415)
            if request.content_length is None:
                abort(411)
        if (request.content_length or 0) > 131072:
            abort(413)
        target = MEDIA + MEDIA_PATH + ("/" + session_id if session_id else "")
        try:
            opener = build_opener(ProxyHandler({}), NoRedirect())
            with opener.open(Request(target, method=request.method,
                                     data=request.get_data() if session_id is None else None,
                                     headers={"Content-Type": "application/sdp"}), timeout=8) as upstream:
                body = upstream.read(131073)
                if len(body) > 131072:
                    raise ValueError("SDP too large")
                response = Response(body, status=upstream.status, mimetype="application/sdp")
                location = upstream.headers.get("Location")
                if request.method == "POST" and not location:
                    raise ValueError("missing WHEP session")
                if location:
                    parsed = urlsplit(location)
                    identifier = parsed.path.removeprefix(MEDIA_PATH + "/")
                    if (parsed.netloc and parsed.netloc != "192.168.1.20:8889") or parsed.scheme not in {"", "http"} or parsed.query or parsed.fragment or not parsed.path.startswith(MEDIA_PATH + "/") or not SESSION.fullmatch(identifier):
                        raise ValueError("invalid WHEP session")
                    response.headers["Location"] = REVIEW_PATH + "/" + identifier
                response.headers["Cache-Control"] = "no-store"
                return response
        except HTTPError as exc:
            # Closing the peer can already remove the MediaMTX session before
            # DELETE arrives. Treat that cleanup race as successful/idempotent.
            if request.method == "DELETE" and exc.code == 404:
                return Response(status=204, headers={"Cache-Control": "no-store"})
            return jsonify(error="Pi5 WebRTC 연결을 사용할 수 없습니다."), 503
        except (URLError, TimeoutError, OSError, ValueError):
            return jsonify(error="Pi5 WebRTC 연결을 사용할 수 없습니다."), 503

    @app.get("/api/fall-notices/<event_id>/snapshot.jpg")
    def event_snapshot(event_id):
        # Only a known event can select an image; never accept a URL from MQTT.
        with notices.lock:
            found = any(e["event_id"] == event_id and e["snapshot_available"]
                        and time.time() - e["received_at"] < 3600 for e in notices.events)
        if not found or not re.fullmatch(r"[0-9a-f]{32}", event_id):
            abort(404)
        try:
            opener = build_opener(ProxyHandler({}), NoRedirect())
            with opener.open(Request(f"{PI5}/api/events/{event_id}/snapshot.jpg"), timeout=3) as upstream:
                data = upstream.read(512001)
                if upstream.headers.get_content_type() != "image/jpeg" or len(data) > 512000 or not data.startswith(b"\xff\xd8"):
                    abort(502)
            return Response(data, mimetype="image/jpeg", headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})
        except HTTPError as exc:
            abort(404 if exc.code == 404 else 502)
        except (URLError, OSError, TimeoutError):
            abort(503)

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
