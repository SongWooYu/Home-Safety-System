from __future__ import annotations

from picamera2 import Picamera2

from .base import CameraSource


def select_full_fov_mode(modes: list[dict], width: int, height: int, fps: int) -> dict:
    """Prefer full sensor coverage, then the smallest adequate readout."""
    candidates = [m for m in modes if m["fps"] >= fps
                  and m["size"][0] >= width and m["size"][1] >= height]
    if not candidates:
        raise RuntimeError("No sensor mode supports the requested resolution and FPS")
    return min(candidates, key=lambda m: (
        -(m["crop_limits"][2] * m["crop_limits"][3]),
        m["size"][0] * m["size"][1],
    ))


class PiCameraSource(CameraSource):
    def __init__(self, width: int, height: int, fps: int):
        self.width = width
        self.height = height
        self.fps = fps
        self.camera: Picamera2 | None = None
        self.view_info: dict | None = None

    def open(self) -> None:
        self.camera = Picamera2(0)
        mode = select_full_fov_mode(self.camera.sensor_modes, self.width, self.height, self.fps)
        config = self.camera.create_video_configuration(
            main={"format": "RGB888", "size": (self.width, self.height)},
            controls={"FrameRate": self.fps},
            sensor={"output_size": mode["size"], "bit_depth": mode["bit_depth"]},
            raw=None,
            buffer_count=4,
            queue=False,
        )
        self.camera.configure(config)
        crop = tuple(self.camera.camera_properties["ScalerCropMaximum"])
        self.camera.set_controls({"ScalerCrop": crop})
        self.view_info = {
            "mode": "full_fov",
            "sensor_size": list(mode["size"]),
            "crop": list(crop),
            "output_size": [self.width, self.height],
        }
        print(f"Camera Module 3 full field of view: {self.view_info}", flush=True)
        self.camera.start()

    def read(self):
        if self.camera is None:
            raise RuntimeError("Camera Module 3 is not open")
        frame_bgr = self.camera.capture_array()
        return frame_bgr

    def close(self) -> None:
        if self.camera is not None:
            try:
                self.camera.stop()
                self.camera.close()
            finally:
                self.camera = None

