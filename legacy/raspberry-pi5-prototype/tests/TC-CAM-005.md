# TC-CAM-005 Python Picamera2 FPS 테스트

## 목적
Python Picamera2를 이용하여 640x480 해상도에서 프레임 획득 FPS를 측정한다.

## 테스트 명령어
```bash
python3 src/step03_camera_fps.py
기대 결과
평균 FPS가 10 이상이어야 한다.
실제 결과
측정 FPS: 약 117 FPS
판정
 PASS
 FAIL
비고

초기 프로토타입 기준 성능 충분.
