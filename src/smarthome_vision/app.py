from __future__ import annotations

import argparse
import time
from pathlib import Path

from flask import Flask, Response, abort, jsonify, render_template

from .config import load_config
from .pipeline import VisionPipeline


def create_app(pipeline: VisionPipeline) -> Flask:
    app = Flask(__name__, template_folder="templates")

    @app.get("/")
    def index():
        return render_template("index.html", cameras=list(pipeline.workers.keys()))

    @app.get("/stream/<camera_id>")
    def stream(camera_id: str):
        if camera_id not in pipeline.workers:
            abort(404)

        def frames():
            while True:
                jpeg = pipeline.camera_jpeg(camera_id)
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Cache-Control: no-store\r\n\r\n" + jpeg + b"\r\n"
                )
                time.sleep(0.04)

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

