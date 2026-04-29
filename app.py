import cv2
import numpy as np
from flask import Flask, Response
from picamera2 import Picamera2
import time
import sys
from unittest.mock import MagicMock

# kms와 pykms 모듈을 가짜(Mock)로 만들어 picamera2가 에러를 내지 않게 합니다.
sys.modules["kms"] = MagicMock()
sys.modules["pykms"] = MagicMock()

import cv2

app = Flask(__name__)

# 카메라 초기화
try:
    picam2 = Picamera2()
    cameras = picam2.list_cameras()
    print(f"🔍 발견된 카메라 목록: {cameras}")
    
    if len(cameras) == 0:
        print("❌ 사용 가능한 카메라가 하나도 없습니다! 연결을 확인하세요.")
        picam2 = None
    else:
        config = picam2.create_video_configuration(main={"format": "RGB888", "size": (640, 480)})
        picam2.configure(config)
        picam2.start()
        print("✅ Picamera2가 성공적으로 시작되었습니다!")
except Exception as e:
    print(f"❌ 카메라 초기화 중 치명적 에러: {e}")
    picam2 = None

def generate_frames():
    while True:
        if picam2 is None:
            time.sleep(1)
            continue
        
        # 프레임 캡처 및 변환
        frame = picam2.capture_array()
        frame_bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        
        ret, buffer = cv2.imencode('.jpg', frame_bgr)
        if not ret: continue
            
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

@app.route('/')
def index():
    return '<body style="margin:0; background:#000;"><img src="/video_feed" style="width:100%;"></body>'

@app.route('/video_feed')
def video_feed():
    return Response(generate_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)