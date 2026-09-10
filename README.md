# Home Safety Vision Node

Raspberry Pi 5에서 서로 다른 카메라 입력을 하나의 AI 분석 파이프라인과 이벤트 형식으로 통합하는 Vision Node입니다.

## 현재 입력

- Camera Module 3: Picamera2/libcamera
- ABKO APC720: V4L2 MJPEG
- Dahua IP Camera: RTSP (환경변수 `DAHUA_RTSP_URL` 필요)

## 개발 대시보드

`:8080` 웹 화면은 최종 사용자 서비스가 아닙니다. 카메라별 원본 입력, NCNN 객체 탐지 결과, FPS, 연결 상태와 사람 이벤트를 개발 중 검증하기 위한 관제 화면입니다. 브라우저 절전·탭 복귀·네트워크 복구 시 MJPEG 스트림을 자동으로 다시 연결합니다.


## 처리 흐름

카메라는 한 번만 캡처합니다. 캡처 프레임은 개발용 웹 MJPEG 출력과 YOLO11n NCNN 객체 검출로 분기됩니다. 모델은 COCO 클래스를 계산하지만 현재 파이프라인은 사람 결과만 남겨 화면·상태·MQTT에 사용합니다. 출력 필터만으로 모델 자체가 경량화되지는 않습니다.

## 이벤트와 낙상 MVP

- 사람 이벤트는 매 프레임이 아니라 등장/퇴장 상태가 바뀔 때만 기록합니다.
- 짧은 오탐을 줄이기 위해 2회 연속 감지 후 등장으로 확정하고, 마지막 감지 후 3초 동안 존재 상태를 유지합니다.
- 카메라 상태와 현재 자세는 MQTT `home/vision/status/<camera_id>`에 5초마다 retain 발행합니다.
- YOLO11n-pose 키포인트로 기존 직립 자세가 수평 자세로 전환되는지를 추적합니다.
- `fall_suspected`가 1.2초 지속되면 `fall_confirmed`를 발행합니다.
- 이 기능은 전시용 위험 징후 감지이며 의료 진단 기능이 아닙니다.


## 얼굴 등록

공식 OpenCV YuNet/SFace 모델을 설치합니다.

```bash
./scripts/setup_face_models.sh
```

`.env`의 `FACE_ADMIN_TOKEN` 관리 키를 대시보드에 입력한 뒤 Camera Module 3 또는 웹캠으로 등록합니다. 한 명만 정면을 보고 등록해야 하며, 원본 얼굴 사진은 저장하지 않고 `data/faces.json`에 특징 벡터만 저장합니다. 일반 상태 화면에는 실제 이름 대신 등록자/미등록자 여부만 표시합니다.

관리 키 확인:

```bash
sed -n 's/^FACE_ADMIN_TOKEN=//p' /home/pi/Home-Safety-System/.env
```
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
DAHUA_RTSP_URL=rtsp://USER:PASSWORD@192.168.1.64:554/cam/realmonitor?channel=1&subtype=0
```

## 주요 API

- `/api/status`: 카메라·AI·MQTT 상태
- `/api/events`: 최근 사람 감지 이벤트
- `/api/faces`: 관리 키가 필요한 등록자 목록
- `/api/faces/enroll`: Camera Module 3/웹캠 얼굴 등록
- `/api/faces/<person_id>`: 등록 삭제
- `/stream/<camera_id>`: MJPEG 영상
- `/health`: 서비스 상태

## Raspberry Pi 4

중앙 MQTT·이벤트 저장·경보·최종 서비스 화면 작업은 [docs/PI4_NEXT_STEPS.md](docs/PI4_NEXT_STEPS.md)에 정리했습니다.

