from picamera2 import Picamera2
import time

picam2 = Picamera2()
config = picam2.create_preview_configuration(
    main={"size": (640, 480), "format": "RGB888"}
)
picam2.configure(config)
picam2.start()
time.sleep(1)

frame = picam2.capture_array()
print("Frame shape:", frame.shape)

picam2.close()
