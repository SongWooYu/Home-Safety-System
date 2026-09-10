# TC-CAM-004 Python Picamera2 이미지 캡처 테스트

## 목적
Python Picamera2를 이용하여 Camera Module 3 프레임을 획득하고 이미지로 저장할 수 있는지 확인한다.

## 테스트 명령어
```bash
python3 src/step02_camera_capture.py
ls -lh captures/python_capture.jpg
기대 결과
captures/python_capture.jpg 파일이 생성되어야 한다.
실제 결과
captures/python_capture.jpg 생성 확인
판정
 PASS
 FAIL
