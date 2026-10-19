from __future__ import annotations
import hashlib
import hmac

import argparse
import time
from datetime import timedelta
from pathlib import Path

from flask import Flask, Response, abort, jsonify, render_template, request, session

from .config import load_config
from .pipeline import VisionPipeline


def create_app(pipeline: VisionPipeline) -> Flask:
    app = Flask(__name__, template_folder="templates")
    face_admin_token = str(
        pipeline.config.get("face_recognition", {}).get("admin_token", "")
    )
    app.secret_key = hashlib.sha256(
        ("home-safety-face-session:" + face_admin_token).encode("utf-8")
    ).digest()
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    )

    def face_admin_authorized() -> bool:
        if face_admin_token and session.get("face_admin") is True:
            return True
        supplied = request.headers.get("X-Face-Admin-Token", "")
        return bool(
            face_admin_token
            and supplied
            and hmac.compare_digest(face_admin_token, supplied)
        )

    @app.get("/")
    def index():
        face_cameras = [
            camera_id
            for camera_id, worker in pipeline.workers.items()
            if worker.face_enrollment
        ]
        return render_template(
            "index.html",
            cameras=list(pipeline.workers.keys()),
            face_cameras=face_cameras,
        )

    @app.get("/stream/<camera_id>")
    def stream(camera_id: str):
        if camera_id not in pipeline.workers:
            abort(404)
        overlay = request.args.get("overlay", "true").strip().lower() not in {
            "0",
            "false",
            "no",
            "off",
        }
        default_stream_fps = float(
            getattr(
                pipeline.workers[camera_id],
                "stream_fps",
                pipeline.config.get("server", {}).get("stream_fps", 15),
            )
        )
        try:
            stream_fps = min(
                30.0,
                max(1.0, float(request.args.get("fps", default_stream_fps))),
            )
        except ValueError:
            stream_fps = default_stream_fps

        def frames():
            pipeline.add_stream_client(camera_id, overlay)
            try:
                while True:
                    jpeg = pipeline.camera_jpeg(camera_id, overlay=overlay)
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Cache-Control: no-store\r\n\r\n" + jpeg + b"\r\n"
                    )
                    time.sleep(1.0 / stream_fps)
            finally:
                pipeline.remove_stream_client(camera_id, overlay)

        response = Response(frames(), mimetype="multipart/x-mixed-replace; boundary=frame")
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        response.headers["X-Accel-Buffering"] = "no"
        return response

    @app.get("/api/status")
    def status():
        return jsonify(pipeline.status())

    @app.get("/api/events")
    def events():
        return jsonify(pipeline.event_bus.recent())

    @app.post("/api/faces/admin/session")
    def create_face_admin_session():
        payload = request.get_json(silent=True) or {}
        supplied = str(payload.get("token", ""))
        if (
            not face_admin_token
            or not supplied
            or not hmac.compare_digest(face_admin_token, supplied)
        ):
            return jsonify({"error": "얼굴 관리 키가 올바르지 않습니다."}), 401
        session.permanent = True
        session["face_admin"] = True
        return jsonify({"authenticated": True, "expires_days": 30})

    @app.get("/api/faces")
    def faces():
        if not face_admin_authorized():
            return jsonify({"error": "얼굴 관리 키가 필요합니다."}), 401
        return jsonify(
            {
                "enabled": pipeline.face_registry is not None,
                "error": pipeline.face_error,
                "people": pipeline.registered_faces(),
            }
        )

    @app.post("/api/faces/enroll")
    def enroll_face():
        payload = request.get_json(silent=True) or {}
        try:
            person = pipeline.enroll_face(
                str(payload.get("camera_id", "")),
                str(payload.get("name", "")),
                str(payload.get("view", "front")),
            )
            return jsonify(person), 201
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 503

    @app.post("/api/faces/enroll/auto")
    def enroll_face_auto():
        payload = request.get_json(silent=True) or {}
        try:
            person = pipeline.enroll_face_auto(
                str(payload.get("camera_id", "")),
                str(payload.get("name", "")),
            )
            return jsonify(person), 201
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except RuntimeError as exc:
            return jsonify({"error": str(exc)}), 503

    @app.delete("/api/faces/<person_id>")
    def delete_face(person_id: str):
        if not face_admin_authorized():
            return jsonify({"error": "얼굴 관리 키가 필요합니다."}), 401
        if not pipeline.delete_face(person_id):
            return jsonify({"error": "등록자를 찾을 수 없습니다."}), 404
        return jsonify({"deleted": True})

    @app.get("/health")
    def health():
        status_data = pipeline.status()
        online = sum(1 for item in status_data["cameras"] if item["online"])
        return jsonify({"status": "ok" if online else "degraded", "online_cameras": online})

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Smart Home Vision Node")
    default_config = Path(__file__).resolve().parents[2] / "config" / "cameras.yaml"
    parser.add_argument("--config", default=str(default_config))
    args = parser.parse_args()

    config = load_config(args.config)
    pipeline = VisionPipeline(config)
    app = create_app(pipeline)
    pipeline.start()
    try:
        app.run(
            host=config["server"].get("host", "0.0.0.0"),
            port=int(config["server"].get("port", 8080)),
            threaded=True,
            use_reloader=False,
        )
    finally:
        pipeline.stop()


if __name__ == "__main__":
    main()
