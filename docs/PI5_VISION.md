# Raspberry Pi 5 비전 노드

> **2026-10-19 운영 기준:** 낙상은 Hailo YOLOv8s-Pose + EdgeFallKit 단일
> 경로다. 자세한 현재 구성은
> [운영 전환 보고서](HAILO_EDGEFALL_PRODUCTION_2026-10-19.md)를 우선한다.

## 목적

Camera Module 3와 Dahua RTSP를 하나의 처리 결과와 MQTT 계약으로 통합한다.
영상 분석 결과를 개발 대시보드에서 검증한다. Pi4에는 MQTT로 작은 JSON
상태·이벤트를 보내고, AI 오버레이 영상은 Pi5에서 H.264/WebRTC로 변환해
전시 브라우저에 직접 전달한다.

## 입력별 경로

| 입력 | 수집 계층 | 입력 형식 | 현재 설정 |
|---|---|---|---|
| Camera Module 3 | Picamera2/libcamera | 센서 프레임을 Picamera2가 배열로 제공 | 960×540, 15 FPS |
| Dahua | RTSP/GStreamer | 메인 스트림 H.264를 최신 프레임 우선으로 디코딩 | `subtype=0`, 1920×1080 약 15 FPS → 내부 960×540 |

Camera Module 3 자체를 웹캠처럼 “MJPEG 카메라”라고 부르지 않는다. 두 입력은
수집 방식이 다르지만 분석 시점에는 모두 OpenCV BGR 배열이다. 개발 웹 화면은
Camera Module 3를 640×360/15 FPS/JPEG70, Dahua를 960×540/10 FPS/JPEG80
multipart MJPEG로 전송한다. Dahua는 Pi5 내부에서 960×540으로 내린 프레임을
pose와 개발 표시에 함께 사용하며 Pose 모델 입력은 별도로 320이다. Camera Module 3의
얼굴 등록용 원본 프레임은 표시 축소 영향을 받지 않는다.

## 처리 순서

```text
카메라별 캡처
  -> 최신 BGR 프레임과 frame sequence 보관
  -> Dahua의 새 프레임만 10 FPS로 pose 분석
  -> pose에서 person bbox와 17 keypoint 생성
  -> 사람별 tracking과 B76 GRU shadow 분석
  -> Camera Module 3는 별도 0.5 FPS로 face 분석
  -> rule/GRU 상태 추적
  -> 상태 변화 이벤트 + 주기 상태 MQTT 발행
  -> 박스/상태 오버레이
  -> 카메라별 개발 화면용 JPEG 인코딩
  -> 전시용 FFmpeg H.264 인코딩 -> MediaMTX -> WebRTC 브라우저
```

AI 처리는 전송 형식으로 바꾸기 전에 한다. Camera Module 3의 clean JPEG는 Pi5
로컬 FFmpeg가 H.264 Baseline 640×360, 15 FPS, 1,000 kbit/s로 소프트웨어
인코딩한다. Dahua는 원본 H.264를 MediaMTX가 직접 pass-through한다. 브라우저에는
WebRTC로 전달하며 Pi4는 영상 바이트 경로에 들어가지 않는다.

Pi5에는 H.264 하드웨어 인코더가 없으므로 `libx264`를 쓴다. 2026-09-17 실측에서
원본 크기 Camera Module 3 JPEG를 사용했을 때 FFmpeg 프로세스는 약 10~14%
CPU였으나, 640×360으로 낮춘 뒤 약 7%로 감소했다. 장면과 접속자 수에 따라
달라지므로 전시 전 장시간 측정한다.

## Dahua 최신 프레임 정책

OpenCV/FFmpeg RTSP 내부 큐는 소비자가 잠시 느려질 때 과거 프레임을 쌓아
10초 지연 뒤 건너뛰기를 만들었다. 현재 Dahua는 GStreamer `rtspsrc`와
`appsink max-buffers=1, drop=true`를 사용한다. 디코드 뒤 queue도 한 프레임으로
제한하므로 처리량이 부족하면 과거 프레임을 버리고 최신 시점으로 복귀한다.

Pi5 상태 API의 `source_backend`는 `gstreamer`, `source_buffer_age_ms`는 로컬
GStreamer PTS 기준 입력 지연을 나타낸다. 3~6명 장면 90초 실측에서 입력 age는
약 0.39~0.50초, 캡처는 대부분 14.4~15.4 FPS, Pose는 9.1~9.5 FPS였다.
세부 원인과 합격 기준은
[Dahua 저지연 비전 POC](DAHUA_LOW_LATENCY_POC_2026-10-15.md)를 따른다.

## 모델과 필터

- 자세 추정: `models/yolo11n-pose_ncnn_model`
- 실행기: NCNN aarch64, Vulkan 비활성, 4 threads
- 입력 크기: 320
- person confidence: 0.10
- NMS IoU: 0.45
- 시간 모델: `models/fall_gru/b76_sqrt_ensemble/numpy`
- 시간 입력: 20 frames × 76 features, 10 FPS

현재 fall runtime은 별도 COCO object detector를 생성하지 않는다. pose 모델이
person bbox와 17개 keypoint를 한 번에 제공하므로 화면에도 사람만 표시된다.
2026-10-08 실측에서 640 pose는 전체 서비스 7.88 FPS, 960 pose는 단독 약
5.35 FPS여서 10 FPS 시간 계약을 만족하는 320을 Hailo 전 운영값으로 유지한다.

## 사람 이벤트 안정화

모든 분석 프레임을 이벤트로 쌓지 않는다. 사람이 연속으로 감지될 때 등장 상태를
확정하고 마지막 감지 뒤 짧은 유지 시간을 둔 뒤 퇴장을 확정한다. 따라서 최근
이벤트 시간이 멈춘 것처럼 보이는 것은 동일 상태를 반복 기록하지 않는 정상
동작일 수 있다. 카메라의 현재 상태는 이벤트와 별도로 5초마다 retain 발행된다.

## 낙상 MVP

가장 큰 사람 포즈의 어깨·골반 중심으로 몸통 각도를 계산한다.

- 몸통 각도 58도 이상이고 바운딩박스 가로/세로비가 0.85 이상이면 `lying`
- 직립 또는 앉은 상태가 최근 3초 안에 있었을 때만 낙상 의심 시작
- 의심 상태가 1.2초 지속되면 `fall_confirmed`
- 직립·앉은 상태가 2초 지속되면 해제
- 몸통 각도 42도 이하는 직립 계열로 처리

의자에 앉은 사람을 낙상으로 오인한 공격적인 규칙은 되돌렸다. 현재 방식은
전시용 MVP라 카메라 각도, 가림, 사람이 세로 방향으로 넘어지는 동작에 따라
미탐이 가능하다. 모델 고도화보다 먼저 각 카메라별 실제 시연 장면을 녹화하지
않는 범위에서 수치 로그로 수집하고 기준을 조정한다.

## MQTT 계약

### 이벤트

토픽: `home/vision/events`, QoS 1, retain 없음

```json
{
  "schema_version": "1.1",
  "event_id": "32자리 고유 ID",
  "timestamp": "UTC ISO-8601",
  "camera_id": "cam3",
  "event_type": "fall_confirmed",
  "confidence": 0.87,
  "details": {}
}
```

MQTT 이벤트 종류는 `person_detected`, `person_cleared`, `fall_suspected`,
`fall_confirmed`, `fall_cleared`다. `event_id`는 Pi4가 QoS 1 재전송을
중복 저장하지 않기 위한 키다. GRU의 `fall_shadow_confirmed/cleared`는 Pi5 로컬
개발 이벤트와 JSONL에만 기록하고 MQTT로 보내지 않는다. rule은 설정의
`fall_detection.rule.mode`가 `active`일 때만 MQTT로 발행한다.

### 상태

토픽: `home/vision/status/<camera_id>`, QoS 0, retain

카메라 온라인 여부, 입력·분석 FPS, 사람 수, 자세/낙상 상태, 얼굴 등록 여부를
담는다. 실제 등록자 이름은 공개 상태에 넣지 않는다.

## 실행과 확인

```bash
sudo systemctl status smarthome-vision.service
curl -s http://127.0.0.1:8080/health
curl -s http://127.0.0.1:8080/api/status
journalctl -u smarthome-vision.service -f
```

Dahua 인증 정보, MQTT 인증 정보, 얼굴 목록·삭제용 관리 키는 Git 밖의
`/home/pi/Home-Safety-System/.env`에만 둔다. RTSP URL은 메인 스트림
`subtype=0`을 사용한다.

WebRTC 서비스 확인:

```bash
systemctl status smarthome-mediamtx.service
ffprobe -v error -rtsp_transport tcp rtsp://127.0.0.1:8554/cam3
curl -L -I http://127.0.0.1:8889/cam3
```

설치와 포트·비트레이트 조정은 [WebRTC 스트리밍 문서](WEBRTC_STREAMING.md)를
따른다. 최신 CPU 벤치마크, shadow 위험과 Hailo 전 완료 조건은
[Hailo 장착 전 비전·통합 상태](PRE_HAILO_STATUS_2026-10-08.md)를 본다.
