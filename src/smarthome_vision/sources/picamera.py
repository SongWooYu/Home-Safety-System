from __future__ import annotations

import cv2
from picamera2 import Picamera2

from .base import CameraSource


class PiCameraSource(CameraSource):
    def __init__(self, width: int, height: int, fps: int):
        self.width = width
        self.height = height
        self.fps = fps
        self.camera: Picamera2 | None = None

    def open(self) -> None:
        self.camera = Picamera2(0)
        config = self.camera.create_video_configuration(
            main={"format": "RGB888", "size": (self.width, self.height)},
            controls={"FrameRate": self.fps},
        )
        self.camera.configure(config)
        self.camera.start()

    def read(self):
        if self.camera is None:
            raise RuntimeError("Camera Module 3 is not open")
        frame_rgb = self.camera.capture_array()
        return cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

    def close(self) -> None:
        if self.camera is not None:
            try:
                self.camera.stop()
                self.camera.close()
            finally:
                self.camera = None

