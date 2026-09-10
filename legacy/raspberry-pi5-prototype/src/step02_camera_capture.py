from pathlib import Path
import time

import cv2
from picamera2 import Picamera2


CAPTURE_DIR = Path("captures")
OUTPUT_FILE = CAPTURE_DIR / "python_capture.jpg"


def main():
    CAPTURE_DIR.mkdir(parents=True, exist_ok=True)

    picam2 = Picamera2()

    config = picam2.create_preview_configuration(
        main={
            "size": (640, 480),
            "format": "RGB888"
        }
    )

    picam2.configure(config)

    print("[INFO] Camera starting...")
    picam2.start()

    # 노출/화이트밸런스 안정화 대기
    time.sleep(2.0)

    print("[INFO] Capturing frame...")
    frame_rgb = picam2.capture_array()

    # OpenCV는 BGR 기준이므로 RGB → BGR 변환
    frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

    ok = cv2.imwrite(str(OUTPUT_FILE), frame_bgr)

    picam2.stop()

    if not ok:
        raise RuntimeError(f"Failed to save image: {OUTPUT_FILE}")

    print(f"[OK] Saved image: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
