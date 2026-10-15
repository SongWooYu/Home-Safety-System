# AI 스마트홈 낙상감지 — Raspberry Pi 진입 전 통합 정리

> **Historical hardware note (2026-10-15):** ABKO APC720 has been retired from the active system. Camera Module 3 now performs face enrollment and recognition; ABKO/V4L2 details below are retained only as experiment history.

> 기준일: 2026-10-06
> 프로젝트: `SongWooYu/Home-Safety-System`
> 목적: Mac 학습 결과, 최신 다중 seed 실험, 현재 GitHub 구현 상태, 3개 카메라 역할을 하나의 기준 문서로 정리한 뒤 Raspberry Pi 5 통합 단계로 넘어가기 위한 설계 기준

## 1. 지금 가장 중요한 수정 사항

이전 단일-seed 실험에서는 `D_125_sqrt`가 가장 좋아 보였지만, 이후 3개 seed(42, 123, 2026) 재현성 평가와 event-level robustness 분석을 수행한 결과 D 모델은 seed 변화에 따라 event operating point가 크게 흔들렸다.

따라서 현재 prototype 배포 후보는:

`B_76_sqrt_3seed_ensemble`

즉 76-feature skeleton/global feature + sqrt inverse class weighting + 3개 독립 GRU의 class probability 평균을 사용한다.

이 문서 이후에는 `D_125_sqrt` single-seed를 기본 배포 모델로 취급하지 않는다. D는 ablation 비교용으로 보존한다.

## 2. 현재 temporal model 후보

- Sequence: 20 frames
- Sampling: 10 FPS
- Window: 약 2초, causal
- Feature dimension: 76
- GRU hidden: 128
- GRU layers: 2
- Dropout: 0.2
- Classes: Normal / Falling / Fallen
- Class weighting: sqrt inverse-frequency

76-feature 구성:

- 17 joints × `[bbox-relative x, bbox-relative y, confidence, valid mask]` = 68
- bbox center x/y, width/height, log(height/width), bbox confidence, frame valid, visible keypoint ratio = 8
- 총 76

3-seed ensemble member:

- `runs/gru_multiseed/B_76_sqrt/seed_42/best.pt`
- `runs/gru_multiseed/B_76_sqrt/seed_123/best.pt`
- `runs/gru_multiseed/B_76_sqrt/seed_2026/best.pt`

Ensemble:

1. 각 GRU softmax
2. 세 모델의 class probability arithmetic mean
3. `alert_score = P(falling) + P(fallen)`

## 3. 현재 ensemble operating profile

Development validation 기준 임시 profile:

- Balanced: threshold 0.92, consecutive 1, provisional default
- Quiet: threshold 0.89, consecutive 4, provisional
- Safety: threshold 0.80, consecutive 3, CORE_ONLY / not frozen

기존 corrected evaluator의 `release_frames = 3`을 runtime reference로 유지한다.

## 4. 평가상 주의사항

현재 model selection과 threshold tuning에는 AI Hub 공식 Validation-derived development split을 광범위하게 사용했다.

따라서 현재 성능은 final untouched evaluation이 아니라 prototype/development 성능이다.

또 internal test도 과거 v1 결과를 이미 확인한 뒤 모델 구조를 변경했으므로 최종 독립 test 역할을 할 수 없다.

정식 최종 평가 구조는 다음이 이상적이다.

AI Hub Training -> train/internal validation
AI Hub official Validation -> final evaluation only

## 5. Pose reference domain

Mac offline pose extraction 기준:

- Model: YOLO11n-Pose pretrained
- imgsz: 960
- confidence: 0.10
- sample FPS: 10
- device: Apple M4 MPS

현재 GRU가 본 skeleton distribution은 `YOLO11n-Pose / 960 / conf 0.10 / 10 Hz`다.

## 6. GitHub 현재 구현 상태

Repository:
`https://github.com/SongWooYu/Home-Safety-System`

Pi5 project path:
`/home/pi/Home-Safety-System`

현재 GitHub `config/cameras.yaml`에는 다음 세 카메라가 들어 있다.

- Camera Module 3
- ABKO APC720 USB webcam
- Dahua IP Camera

그러나 실제 현재 하드웨어는 사용자 설명 기준:

1. Dahua IP Camera — 192.168.1.64
2. Anker USB Webcam
3. Raspberry Pi Camera Module 3

따라서 GitHub의 ABKO webcam 정보는 현재 실제 장비와 불일치한다.

Pi 단계에서 Anker의 실제 `/dev/v4l/by-id/...`, 지원 해상도, FPS, pixel format을 확인한 뒤 config를 갱신한다.

## 7. 현재 네트워크

- Router: 192.168.1.1
- Pi5: 192.168.1.20 — Vision node
- Pi4: 192.168.1.10 — MQTT/PostgreSQL/automation/final web
- Dahua: 192.168.1.64 — RTSP

Dahua는 Pi5에 직결하지 않고 공유기를 통해 접근한다.

## 8. 카메라 입력 구조

### Camera Module 3
- Picamera2/libcamera
- 현재 config: 960×540, 30 FPS

### 기존 USB webcam
- OpenCV CAP_V4L2
- MJPG
- 1280×720, 30 FPS 요청
- 구현 클래스는 generic `UsbCameraSource`

따라서 Anker가 V4L2 장치로 정상 인식되면 같은 source class를 재사용할 가능성이 높다.

### Dahua
- RTSP/OpenCV/FFmpeg
- RTSP/TCP
- 현재 문서상 main stream `subtype=0`
- 실제 약 1280×720 / 25 FPS

## 9. 표시 해상도와 AI 해상도를 구분

현재 640×360 / 15 FPS는 개발 MJPEG/WebRTC 표시용이다.

AI는 원본 frame에서 수행한 뒤 overlay frame만 축소한다.

즉 낙상 pose를 640×360 브라우저 stream에 걸면 안 된다.

## 10. 현재 GitHub 낙상 구현은 구형 MVP

현재 repo:

- Pose model: `models/yolo11n-pose_ncnn_model`
- input_size: 320
- confidence: 0.35
- pose analysis_fps: 1.5

그리고 `PI5_VISION.md`의 낙상 판단은 torso angle, bbox ratio, transition time을 이용한 규칙 기반 MVP다.

즉 최신 20-frame GRU ensemble은 아직 repo에 통합되어 있지 않다.

## 11. 가장 큰 deployment domain gap

Offline:
- pose 960
- conf 0.10
- 10 FPS

현재 Pi repo:
- pose 320
- conf 0.35
- 1.5 FPS

차이가 크다.

특히 B_76 model은 20 frames @ 10 FPS ≈ 2초를 전제로 학습했다. Pi에서 20 frames @ 2 FPS로 실행하면 약 10초가 되어 training distribution과 크게 달라진다.

따라서 Pi에서 새 GRU를 사용하려면 우선 10 Hz pose sequence 확보를 목표로 한다. 불가능하면 FPS를 낮춘 새 dataset/model 재학습이 필요하다.

## 12. 세 카메라의 권장 역할

| 카메라 | 주 역할 | Face | Fall Pose/GRU |
|---|---|---:|---:|
| Dahua IP 192.168.1.64 | 메인 낙상 카메라 | OFF | ON |
| Anker Webcam | 얼굴 등록 + 근거리 얼굴 인식 | ON | OFF |
| Camera Module 3 | 보조 시점 / event verification / second view | OFF | 기본 OFF 또는 후순위 |

## 13. Dahua — 메인 낙상 카메라

권장 핵심 경로:

Dahua RTSP
-> capture/decode
-> YOLO Pose
-> person tracker
-> track별 20-frame 76-feature buffer
-> 3-seed GRU ensemble
-> alert score
-> state machine
-> MQTT fall event

Dahua는 고정 위치, RTSP, 해상도/FPS 조절 가능이라는 점 때문에 메인 fall source로 가장 적합하다.

## 14. Dahua source 해상도는 Pi 실측 후 확정

초기 비교 권장:

- 1280×720 / 15 FPS
- 1920×1080 / 15 FPS

Pose detector:
- imgsz 640
- imgsz 960

핵심 평가지표:
- person pixel height
- pose/keypoint coverage
- 10 FPS pose 처리 가능 여부
- CPU/NPU load
- decode stability

AI Hub 원본이 4K였어도 실제 pose detector input은 960이었으므로 운영 카메라를 4K로 맞출 필요는 없다.

## 15. Anker — 얼굴 등록 전용

권장:

Anker
-> YuNet
-> SFace
-> front/left/right template
-> faces.json

기존 repo face 방식:
- YuNet
- SFace
- cosine similarity
- threshold 약 0.45
- front / left / right
- 등록 시 5 frame
- 최소 3 valid face

Anker를 controlled enrollment station으로 쓰는 것이 적합하다.

낙상 pose나 일반 YOLO object detection은 끈다.

## 16. 얼굴 ID와 Dahua 낙상 track은 바로 동일인으로 간주하지 않는다

Anker에서 인식한 ID와 Dahua에서 넘어진 사람을 연결하려면 tracking/re-identification/camera-to-camera association이 필요하다.

졸업작품에서는 얼굴 등록/등록자 판별과 낙상 감지를 독립 기능으로 시연해도 충분하다.

## 17. Camera Module 3 — 추천 용도

현재 가장 적합한 역할은 `secondary view / event verification camera`다.

권장 구조:

- Dahua가 primary authoritative fall detector
- Camera Module 3는 second-angle evidence
- Dahua alert를 Camera Module 3 동의가 있어야만 발생시키는 AND 구조는 사용하지 않음

즉:

Dahua FALL -> alert

Camera Module 3에도 fall evidence -> `secondary_verified=true` 또는 confidence 강화

이렇게 사용한다.

초기에는 Camera Module 3 AI를 끄고 second live view / operator verification으로 사용해도 된다.

Pi 여유가 확인된 뒤 secondary pose를 추가한다.

## 18. 세 카메라에 같은 AI를 모두 돌리지 않는다

새 역할 분배:

Dahua:
- pose/tracker/GRU ON
- face OFF

Anker:
- face ON
- pose/fall OFF
- generic YOLO OFF

Camera Module 3:
- face OFF
- generic YOLO 기본 OFF
- fall 기본 OFF 또는 secondary mode

## 19. Generic YOLO detector는 main fall path에서 필수 아님

Pose model 자체가 person bbox + 17 keypoints를 제공하므로 낙상 main path는 가능하면:

Dahua -> YOLO11n-Pose -> tracker -> GRU

로 단순화한다.

다른 객체 탐지가 필요한 경우에만 일반 YOLO11n detector를 별도 기능으로 유지한다.

## 20. Tracker는 실제 운영에서 필수

실제 스마트홈에서는 여러 사람이 있을 수 있으므로 largest-person only 로직을 그대로 쓰면 안 된다.

필요 구조:

Pose detections
-> tracker
-> track_id
-> track별 20-frame buffer
-> GRU state
-> alert state
-> cooldown state

## 21. Pi5에서 검증할 순서

1. Pi5 시스템/패키지 inventory
2. 세 카메라 실제 device/mode 확인
3. Dahua 단독 RTSP 안정성
4. Dahua Pose benchmark
   - source 720p vs 1080p
   - pose 640 vs 960
5. 10 FPS pose sequence 가능 여부
6. B 3-seed ensemble GRU 연결
7. 단일 사람 실시간 fall simulation
8. Anker face registration
9. Camera Module 3 second view
10. 전체 3-camera 부하 시험

## 22. Pi benchmark 기록값

Capture:
- source FPS
- decode latency
- dropped frames
- reconnect

Pose:
- imgsz
- mean/p95 inference ms
- effective FPS
- person detection
- visible keypoint ratio
- pose coverage

GRU:
- feature generation ms
- 3-model ensemble inference ms
- total temporal inference ms

System:
- CPU
- RAM
- temperature
- throttling
- network bitrate

Event:
- fall-end recall
- +1s recall
- latency
- false alarms

## 23. GitHub에서 앞으로 수정할 핵심

카메라별 feature switch가 필요하다.

예시:

Dahua:
- role: primary_fall
- pose_enabled: true
- fall_enabled: true
- face_recognition: false
- face_enrollment: false

Anker:
- role: face_station
- pose_enabled: false
- fall_enabled: false
- face_recognition: true
- face_enrollment: true

Camera Module 3:
- role: secondary_view
- pose_enabled: false
- fall_enabled: false
- face_recognition: false
- face_enrollment: false

추후 필요 시 Camera Module 3 pose만 켠다.

## 24. Temporal detector 교체 방식

현재 규칙 기반 detector를 바로 삭제하지 않는다.

권장 인터페이스:

- RuleFallDetector
- TemporalGruFallDetector

설정:

- backend: rule
- backend: gru

GRU에 문제가 생기면 기존 rule MVP를 전시 fallback으로 사용할 수 있다.

## 25. 현재 기준

Temporal model:
`B_76_sqrt_3seed_ensemble`

Main fall camera:
`Dahua 192.168.1.64`

Face camera:
`Anker USB Webcam`

Secondary camera:
`Raspberry Pi Camera Module 3`

Primary event policy:
`STRICT`

Provisional profiles:
- Balanced: threshold 0.92 / consecutive 1
- Quiet: threshold 0.89 / consecutive 4
- Safety: threshold 0.80 / consecutive 3 / not frozen

## 26. 아직 Pi 실측 전 확정하지 않을 항목

- Dahua source resolution
- Dahua source FPS
- pose imgsz 640 vs 960
- NCNN vs Hailo
- Camera Module 3 secondary pose 사용 여부
- Anker exact capture mode
- 최종 event threshold
- 실제 household FA/hour

## 27. 한 줄 결론

앞으로 Raspberry Pi는 세 카메라에 같은 AI를 모두 돌리는 구조가 아니라:

- Dahua = 낙상
- Anker = 얼굴
- Camera Module 3 = 보조 검증

으로 역할을 나눈다.

핵심 실시간 경로는:

Dahua
-> YOLO Pose 10Hz
-> tracker
-> B_76_sqrt 3-seed GRU ensemble
-> event state machine
-> MQTT

를 먼저 안정화하는 것이다.
