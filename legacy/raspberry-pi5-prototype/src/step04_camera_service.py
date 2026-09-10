import time
from pathlib import Path

import cv2
from picamera2 import Picamera2

from common.config_loader import load_config
from common.logger import get_logger


def main():
    logger = get_logger("camera_service")
    config = load_config()

    width = int(config["camera"]["width"])
    height = int(config["camera"]["height"])
    image_format = config["camera"]["format"]
    warmup_sec = float(config["camera"]["warmup_sec"])

    captures_dir = Path(config["path"]["captures_dir"])
    captures_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Camera service starting")
    logger.info(f"Camera config: {width}x{height}, format={image_format}")

    picam2 = Picamera2()

    camera_config = picam2.create_preview_configuration(
        main={
            "size": (width, height),
            "format": image_format
        }
    )

    picam2.configure(camera_config)
    picam2.start()

    logger.info(f"Camera warmup: {warmup_sec} sec")
    time.sleep(warmup_sec)

    frame_count = 0
    fps_start_time = time.time()
    last_save_time = 0.0

    try:
        while True:
            frame_rgb = picam2.capture_array()
            frame_count += 1

            now = time.time()
            elapsed = now - fps_start_time

            if elapsed >= 5.0:
                fps = frame_count / elapsed
                logger.info(f"Camera running: fps={fps:.2f}, frame_shape={frame_rgb.shape}")
                frame_count = 0
                fps_start_time = now

            # 10초마다 샘플 이미지 저장
            if now - last_save_time >= 10.0:
                output_path = captures_dir / "latest.jpg"
                frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
                cv2.imwrite(str(output_path), frame_bgr)
                logger.info(f"Saved latest frame: {output_path}")
                last_save_time = now

    except KeyboardInterrupt:
        logger.info("Camera service stopped by user")

    finally:
        picam2.stop()
        logger.info("Camera stopped")


if __name__ == "__main__":
    main()
