#!/usr/bin/env python3
import time
import threading
from typing import Optional

import cv2
from flask import Flask, Response, render_template_string
from picamera2 import Picamera2


USB_CAMERA_PATH = "/dev/v4l/by-id/usb-SunplusIT_Inc_ABKO_APC720_HD_WEBCAM_N2020120301-video-index0"

CAM_WIDTH = 1280
CAM_HEIGHT = 720
CAM_FPS = 30

JPEG_QUALITY = 80


app = Flask(__name__)


class UsbCamera:
    def __init__(self, device: str):
        self.device = device
        self.cap: Optional[cv2.VideoCapture] = None
        self.lock = threading.Lock()
        self.frame = None
        self.running = False
        self.thread: Optional[threading.Thread] = None

    def start(self):
        self.cap = cv2.VideoCapture(self.device, cv2.CAP_V4L2)

        if not self.cap.isOpened():
            raise RuntimeError(f"USB camera open failed: {self.device}")

        # APC720은 720p30 사용 시 MJPG 지정이 중요합니다.
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAM_WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAM_HEIGHT)
        self.cap.set(cv2.CAP_PROP_FPS, CAM_FPS)

        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

    def _capture_loop(self):
        while self.running:
            ok, frame = self.cap.read()
            if not ok:
                time.sleep(0.05)
                continue

            with self.lock:
                self.frame = frame

    def get_jpeg(self):
        with self.lock:
            if self.frame is None:
                return None
            frame = self.frame.copy()

        ok, encoded = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY],
        )
        if not ok:
            return None

        return encoded.tobytes()

    def stop(self):
        self.running = False
        if self.cap is not None:
            self.cap.release()


class PiCamera3:
    def __init__(self):
        self.picam2 = Picamera2()
        self.lock = threading.Lock()
        self.frame = None
        self.running = False
        self.thread: Optional[threading.Thread] = None

    def start(self):
        config = self.picam2.create_video_configuration(
            main={
                "size": (CAM_WIDTH, CAM_HEIGHT),
                "format": "RGB888",
            },
            controls={
                "FrameRate": CAM_FPS,
            },
        )
        self.picam2.configure(config)
        self.picam2.start()

        # 센서 안정화 대기
        time.sleep(1.0)

        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

    def _capture_loop(self):
        while self.running:
            frame_rgb = self.picam2.capture_array()

            # OpenCV JPEG 인코딩은 BGR 기준이므로 변환
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

            with self.lock:
                self.frame = frame_bgr

    def get_jpeg(self):
        with self.lock:
            if self.frame is None:
                return None
            frame = self.frame.copy()

        ok, encoded = cv2.imencode(
            ".jpg",
            frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY],
        )
        if not ok:
            return None

        return encoded.tobytes()

    def stop(self):
        self.running = False
        self.picam2.stop()


usb_cam = UsbCamera(USB_CAMERA_PATH)
pi_cam = PiCamera3()


def mjpeg_generator(camera):
    while True:
        jpg = camera.get_jpeg()

        if jpg is None:
            time.sleep(0.05)
            continue

        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n"
            b"Content-Length: " + str(len(jpg)).encode() + b"\r\n"
            b"\r\n" + jpg + b"\r\n"
        )

        # 브라우저/CPU 부하 완화. 필요 시 0.0~0.03 범위 조정.
        time.sleep(0.01)


@app.route("/")
def index():
    html = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Raspberry Pi 5 Dual Camera Stream</title>
  <style>
    body {
      font-family: Arial, sans-serif;
      background: #111;
      color: #eee;
      margin: 0;
      padding: 20px;
    }
    h1 {
      font-size: 22px;
      margin-bottom: 20px;
    }
    .grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }
    .card {
      background: #222;
      border-radius: 8px;
      padding: 12px;
    }
    .card h2 {
      margin: 0 0 10px 0;
      font-size: 16px;
    }
    img {
      width: 100%;
      height: auto;
      background: #000;
      border-radius: 4px;
    }
    .meta {
      margin-top: 16px;
      color: #aaa;
      font-size: 13px;
    }
  </style>
</head>
<body>
  <h1>Raspberry Pi 5 Dual Camera Stream</h1>

  <div class="grid">
    <div class="card">
      <h2>Camera Module 3 / IMX708</h2>
      <img src="/stream/cam3">
    </div>

    <div class="card">
      <h2>ABKO APC720 USB Webcam</h2>
      <img src="/stream/usb">
    </div>
  </div>

  <div class="meta">
    Resolution: 1280x720 / Target FPS: 30 / Stream: MJPEG over HTTP
  </div>
</body>
</html>
"""
    return render_template_string(html)


@app.route("/stream/cam3")
def stream_cam3():
    return Response(
        mjpeg_generator(pi_cam),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/stream/usb")
def stream_usb():
    return Response(
        mjpeg_generator(usb_cam),
        mimetype="multipart/x-mixed-replace; boundary=frame",
    )


@app.route("/health")
def health():
    return {
        "status": "ok",
        "camera_module_3": pi_cam.frame is not None,
        "usb_camera": usb_cam.frame is not None,
        "usb_camera_path": USB_CAMERA_PATH,
        "width": CAM_WIDTH,
        "height": CAM_HEIGHT,
        "fps": CAM_FPS,
    }


def main():
    print("[INFO] Starting Camera Module 3...")
    pi_cam.start()

    print("[INFO] Starting USB camera...")
    usb_cam.start()

    print("[INFO] Web server: http://0.0.0.0:8080")
    app.run(host="0.0.0.0", port=8080, threaded=True)


if __name__ == "__main__":
    try:
        main()
    finally:
        usb_cam.stop()
        pi_cam.stop()
