# Home Safety Vision Node

Raspberry Pi 5에서 서로 다른 카메라 입력을 하나의 웹 화면과 AI 이벤트 형식으로 통합하는 Vision Node입니다.

## 현재 입력

- Camera Module 3: Picamera2/libcamera
- ABKO APC720: V4L2 MJPEG
- Dahua IP Camera: RTSP (환경변수 `DAHUA_RTSP_URL` 필요)

## 처리 흐름

카메라는 한 번만 캡처합니다. 캡처 프레임은 웹 MJPEG 출력과 NCNN 사람 검출로 분기됩니다. 사람의 등장/퇴장 이벤트는 웹 API와 MQTT `home/vision/events`로 전달됩니다.

## 실행

```bash
cd /home/pi/Home-Safety-System
source .venv/bin/activate
export PYTHONPATH=/home/pi/Home-Safety-System/src
python -m smarthome_vision.app
```

브라우저에서 `http://192.168.1.20:8080`으로 접속합니다.

## Dahua 연결

비밀번호를 Git에 기록하지 않습니다. `/home/pi/Home-Safety-System/.env`에 다음 값을 설정합니다.

```bash
DAHUA_RTSP_URL=rtsp://USER:PASSWORD@192.168.1.64:554/cam/realmonitor?channel=1&subtype=1
```

## 주요 API

- `/api/status`: 카메라·AI·MQTT 상태
- `/api/events`: 최근 사람 감지 이벤트
- `/stream/<camera_id>`: MJPEG 영상
- `/health`: 서비스 상태

