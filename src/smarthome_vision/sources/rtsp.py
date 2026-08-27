from __future__ import annotations

import os

import cv2

from .base import CameraSource


class RtspSource(CameraSource):
    def __init__(self, url: str, transport: str = "tcp"):
        self.url = url
        self.transport = transport
        self.capture: cv2.VideoCapture | None = None

    def open(self) -> None:
        if not self.url:
            raise RuntimeError("DAHUA_RTSP_URL is not configured")

        old_options = os.environ.get("OPENCV_FFMPEG_CAPTURE_OPTIONS")
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = f"rtsp_transport;{self.transport}"
        try:
            capture = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
        finally:
            if old_options is None:
                os.environ.pop("OPENCV_FFMPEG_CAPTURE_OPTIONS", None)
            else:
                os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = old_options

        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not capture.isOpened():
            capture.release()
            raise RuntimeError("Dahua RTSP stream open failed")
        self.capture = capture

    def read(self):
        if self.capture is None:
            raise RuntimeError("Dahua RTSP stream is not open")
        ok, frame = self.capture.read()
        if not ok or frame is None:
            raise RuntimeError("Dahua RTSP frame read failed")
        return frame

    def close(self) -> None:
        if self.capture is not None:
            self.capture.release()
            self.capture = None

