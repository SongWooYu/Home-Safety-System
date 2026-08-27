from __future__ import annotations

import cv2

from .base import CameraSource


class UsbCameraSource(CameraSource):
    def __init__(self, device: str, width: int, height: int, fps: int, input_format: str = "MJPG"):
        self.device = device
        self.width = width
        self.height = height
        self.fps = fps
        self.input_format = input_format
        self.capture: cv2.VideoCapture | None = None

    def open(self) -> None:
        capture = cv2.VideoCapture(self.device, cv2.CAP_V4L2)
        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*self.input_format))
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
        capture.set(cv2.CAP_PROP_FPS, self.fps)
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not capture.isOpened():
            capture.release()
            raise RuntimeError("USB webcam open failed")
        self.capture = capture

    def read(self):
        if self.capture is None:
            raise RuntimeError("USB webcam is not open")
        ok, frame = self.capture.read()
        if not ok or frame is None:
            raise RuntimeError("USB webcam frame read failed")
        return frame

    def close(self) -> None:
        if self.capture is not None:
            self.capture.release()
            self.capture = None

