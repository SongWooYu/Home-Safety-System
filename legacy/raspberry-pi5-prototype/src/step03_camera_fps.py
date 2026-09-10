import time
from picamera2 import Picamera2


WIDTH = 640
HEIGHT = 480
TEST_SECONDS = 10


def main():
    picam2 = Picamera2()

    config = picam2.create_preview_configuration(
        main={
            "size": (WIDTH, HEIGHT),
            "format": "RGB888"
        }
    )

    picam2.configure(config)

    print("[INFO] Camera starting...")
    picam2.start()
    time.sleep(2.0)

    frame_count = 0
    start_time = time.time()

    while True:
        _ = picam2.capture_array()
        frame_count += 1

        elapsed = time.time() - start_time
        if elapsed >= TEST_SECONDS:
            break

    picam2.stop()

    fps = frame_count / elapsed

    print("========== FPS Result ==========")
    print(f"Resolution : {WIDTH}x{HEIGHT}")
    print(f"Frames     : {frame_count}")
    print(f"Elapsed    : {elapsed:.2f} sec")
    print(f"FPS        : {fps:.2f}")

    if fps >= 10:
        print("[PASS] FPS is acceptable for initial prototype.")
    else:
        print("[WARN] FPS is below initial target. Need optimization.")


if __name__ == "__main__":
    main()
