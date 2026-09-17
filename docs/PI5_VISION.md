# Raspberry Pi 5 비전 노드

## 목적

서로 다른 세 카메라 인터페이스를 하나의 처리 결과와 MQTT 계약으로 통합한다.
영상 분석 결과를 개발 대시보드에서 검증한다. Pi4에는 MQTT로 작은 JSON
상태·이벤트를 보내고, AI 오버레이 영상은 Pi5에서 H.264/WebRTC로 변환해
전시 브라우저에 직접 전달한다.

## 입력별 경로

| 입력 | 수집 계층 | 입력 형식 | 현재 설정 |
|---|---|---|---|
| Camera Module 3 | Picamera2/libcamera | 센서 프레임을 Picamera2가 배열로 제공 | 960×540, 30 FPS |
| ABKO APC720 | V4L2/OpenCV | 카메라에 MJPG 요청 후 OpenCV가 BGR로 디코딩 | 1280×720, 30 FPS 요청 |
| Dahua | RTSP/OpenCV/FFmpeg | 메인 스트림 압축 영상을 디코딩 | `subtype=0`, 실제 1280×720 약 25 FPS |

즉 Camera Module 3 자체를 웹캠처럼 “MJPEG 카메라”라고 부르지 않는다. 세 입력은
수집 방식이 다르지만 분석 시점에는 모두 OpenCV BGR 배열이다. 개발 웹 화면으로
보낼 때만 분석·오버레이가 끝난 프레임을 JPEG로 다시 압축해 multipart MJPEG로
전송한다.

## 처리 순서

```text
카메라별 캡처
  -> 최신 BGR 프레임 보관
  -> 제한된 analysis_fps로 객체 검출
  -> person 결과만 필터
  -> 제한된 별도 주기로 pose와 face 분석
  -> 시간 기반 상태 추적
  -> 상태 변화 이벤트 + 주기 상태 MQTT 발행
  -> 박스/상태 오버레이
  -> 개발 화면용 JPEG 인코딩
  -> 전시용 FFmpeg H.264 인코딩 -> MediaMTX -> WebRTC 브라우저
```

AI 처리는 전송 형식으로 바꾸기 전에 한다. `/stream/<camera_id>?fps=8`의 최신
분석 JPEG를 Pi5 로컬 FFmpeg가 받아 H.264 Baseline 640×360, 8 FPS,
700 kbit/s로 소프트웨어 인코딩한다. MediaMTX에는 loopback RTSP로 게시하고,
브라우저에는 WebRTC로 전달한다. Pi4는 영상 경로에 들어가지 않는다.

Pi5에는 H.264 하드웨어 인코더가 없으므로 `libx264`를 쓴다. 2026-09-17 실측에서
세 영상을 동시에 볼 때 FFmpeg 프로세스는 각각 약 3~5% CPU와 약 60MB RSS, MediaMTX는 약 46MB
RSS를 사용했다. 장면과 접속자 수에 따라 달라지므로 전시 전 장시간 측정한다.

## 모델과 필터

- 객체 검출: `models/yolo11n_ncnn_model`
- 자세 추정: `models/yolo11n-pose_ncnn_model`
- 실행기: NCNN aarch64, Vulkan 비활성, CPU 스레드 제한
- 입력 크기: 320
- 객체 임계값: 0.35
- NMS IoU: 0.45

객체 모델은 COCO 여러 클래스를 계산하지만 현재 코드가 `person`만 남긴다.
출력 필터는 화면을 단순화할 뿐 모델 연산량을 줄이지 않는다. 실제 경량화를
하려면 person 전용으로 학습·변환한 모델, 작은 입력, 분석 FPS 조정 또는 Hailo
가속이 필요하다.

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

이벤트 종류는 `person_detected`, `person_cleared`, `fall_suspected`,
`fall_confirmed`, `fall_cleared`다. `event_id`는 Pi4가 QoS 1 재전송을
중복 저장하지 않기 위한 키다.

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

Dahua 인증 정보, MQTT 인증 정보, 얼굴 관리 키는 Git 밖의
`/home/pi/Home-Safety-System/.env`에만 둔다. RTSP URL은 메인 스트림
`subtype=0`을 사용한다.

WebRTC 서비스 확인:

```bash
systemctl status smarthome-mediamtx.service
ffprobe -v error -rtsp_transport tcp rtsp://127.0.0.1:8554/cam3
curl -L -I http://127.0.0.1:8889/cam3
```

설치와 포트·비트레이트 조정은 [WebRTC 스트리밍 문서](WEBRTC_STREAMING.md)를
따른다.
