"""LAN-only demonstration audio controls; deliberately no admin token.

No camera data, alarm state, or arbitrary text is sent. Cross-origin browser
requests and rapid repeated clicks are rejected. Not an Internet auth scheme.
"""
import threading
import time
from urllib.parse import urlsplit

from flask import jsonify, request


def register_audio_routes(app, pipeline):
    lock = threading.Lock()
    last_request = {}

    def send(action):
        origin = request.headers.get("Origin")
        if (request.headers.get("Sec-Fetch-Site") == "cross-site"
                or (origin and (urlsplit(origin).netloc != request.host
                                or urlsplit(origin).scheme != request.scheme))):
            return jsonify(error="다른 사이트에서는 음성을 제어할 수 없습니다."), 403
        if not request.is_json:
            return jsonify(error="JSON 요청이 필요합니다."), 415
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="JSON 객체가 필요합니다."), 400
        volume = payload.get("volume")
        if action == "volume" and (type(volume) is not int or not 0 <= volume <= 100):
            return jsonify(error="음량은 0~100 정수여야 합니다."), 400
        with lock:
            now = time.monotonic()
            if now - last_request.get(action, -100) < (3 if action == "test_tts" else 0.5):
                return jsonify(error="잠시 후 다시 눌러 주세요."), 429
            last_request[action] = now
        try:
            pipeline.event_bus.publish_audio(action, volume)
        except (RuntimeError, ValueError) as exc:
            return jsonify(error=str(exc)), 503
        return jsonify(sent=True, action=action, volume=volume,
                       note="MQTT 브로커 전달 확인입니다. 실제 스피커 소리는 현장에서 확인하세요.")

    app.add_url_rule("/api/audio/test", "audio_test", lambda: send("test_tts"), methods=["POST"])
    app.add_url_rule("/api/audio/volume", "audio_volume", lambda: send("volume"), methods=["POST"])
