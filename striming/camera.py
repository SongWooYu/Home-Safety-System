import cv2
from ultralytics import YOLO
from picamera2 import Picamera2
import numpy as np

class VideoCamera:
    def __init__(self):
        # 1. 모델 로드 (가장 가벼운 'n' 모델 사용)
        # 'yolo11n.pt'는 객체 인식, 'yolo11n-pose.pt'는 관절 추출용입니다.
        self.model = YOLO('yolo11n.pt') 
        
        # 2. 카메라 설정
        self.picam2 = Picamera2()
        config = self.picam2.create_video_configuration(main={"format": "RGB888", "size": (640, 480)})
        self.picam2.configure(config)
        self.picam2.start()

    def __del__(self):
        self.picam2.stop()

    def get_frame(self):
        # 카메라로부터 RGB 프레임 캡처
        frame = self.picam2.capture_array()
        
        # 3. 머신러닝 추론 (Object Detection)
        # 만약 관절 추출을 원하면 위에서 yolo11n-pose.pt를 로드하면 됩니다.
        results = self.model(frame, verbose=False)
        
        # 4. 결과 그리기
        # results[0].plot()은 추론 결과를 프레임 위에 그려주는데, 
        # 이때 내부적으로 BGR로 처리될 수 있으므로 주의가 필요합니다.
        annotated_frame = results[0].plot() 

        # 5. 색상 보정 (중요!)
        # picamera2(RGB) -> YOLO(처리) -> annotated_frame
        # 웹 스트리밍(JPEG)은 RGB를 기대하므로, 만약 plot() 결과가 BGR이라면 변환해줍니다.
        # 일반적으로 YOLO의 plot()은 입력 포맷을 따르지만, 색상이 이상하면 아래 줄 주석을 해제하세요.
        # annotated_frame = cv2.cvtColor(annotated_frame, cv2.COLOR_BGR2RGB)

        # JPEG 인코딩
        _, buffer = cv2.imencode('.jpg', annotated_frame)
        return buffer.tobytes()

def generate_frames(camera):
    while True:
        frame_bytes = camera.get_frame()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')