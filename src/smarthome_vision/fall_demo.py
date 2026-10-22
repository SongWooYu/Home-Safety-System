"""Test the real MQTT contract without altering the detector or real alarms."""
import threading
import time
from flask import Response, abort, jsonify, request
from .evidence import EVENT_ID
from .request_origin import same_origin_request


def register_fall_demo_routes(app, pipeline):
    bus = pipeline.event_bus
    lock = threading.Lock()
    last_send = -100.0

    @app.get("/api/fall-test")
    def demo_status():
        response = jsonify(connected=bus.connected, pi4_state=bus.safety_state)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.post("/api/fall-test")
    def demo_send():
        nonlocal last_send
        if not same_origin_request():
            return jsonify(error="다른 사이트에서는 시험 경보를 보낼 수 없습니다."), 403
        if not request.is_json:
            return jsonify(error="JSON 요청이 필요합니다."), 415
        payload = request.get_json(silent=True)
        stage = payload.get("stage") if isinstance(payload, dict) else None
        if stage not in ("suspected", "confirmed", "cleared"):
            return jsonify(error="시험 단계가 올바르지 않습니다."), 400
        with lock:
            if time.monotonic() - last_send < 0.75:
                return jsonify(error="잠시 후 다시 눌러 주세요."), 429
            last_send = time.monotonic()
            try:
                event = bus.emit("manual-test", "fall_" + stage, details={
                    "test": True, "backend": "manual_demo", "source_camera_id": "dahua",
                    "test_timeout_seconds": 30,
                    "note": "수동 통신 시험입니다. AI 감지 결과가 아닙니다.",
                }, require_delivery=True)
            except RuntimeError as exc:
                return jsonify(error=str(exc)), 503
        return jsonify(sent=True, event=event, note="MQTT 전달 확인 · Pi4 수신 상태는 별도로 표시합니다.")

    @app.get("/api/events/<event_id>/snapshot.jpg")
    def evidence(event_id):
        if not EVENT_ID.fullmatch(event_id):
            abort(404)
        jpeg = bus.evidence.get(event_id)
        if jpeg is None:
            abort(404)
        return Response(jpeg, mimetype="image/jpeg", headers={"Cache-Control": "no-store",
                                                              "X-Content-Type-Options": "nosniff"})
