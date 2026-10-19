# Hailo YOLOv8 + EdgeFall 운영 전환 보고서

기준일: 2026-10-19

대상: Raspberry Pi 5 8GB + Raspberry Pi AI HAT+ (Hailo-8, 26 TOPS)

같은 날 후속 UI 개선: [대시보드·한글·전체 화각](VISION_DASHBOARD_2026-10-19.md).
기존 `준비 중/0%` 대신 무인·관절 부족·초기 관측을 구분한다. 모델/낙상 정책 변경 없음.

운영 카메라: Dahua IP Camera(낙상), Camera Module 3(얼굴)

## 1. 결론부터

현재 정식 낙상 경로는 다음 하나다.

```text
Dahua RTSP 최신 프레임
  -> GStreamer 저지연 decode (960x540)
  -> Hailo-8 YOLOv8s-Pose v2.15 HEF
  -> 사람별 EdgeFallKit tracker
  -> 48-frame Hailo 전용 temporal MLP
  -> 기하·시간 상태기계
  -> fall_suspected / fall_confirmed / fall_cleared
  -> MQTT home/vision/events
  -> Pi4 자동화·스피커·DB
```

따라서 “HAT+용으로 튜닝된 정식 버전이 YOLOv8인가?”에 대한 답은 **그렇다**.
다만 정확히는 일반 YOLOv8 객체 검출 모델이 아니라, Hailo Model Zoo v2.15의
`yolov8s_pose.hef`로 사람 박스와 COCO 17개 관절을 얻는다. 낙상 최종 판단은
YOLO가 직접 하는 것이 아니라 EdgeFallKit의 tracker, 시간 분류기와 상태기계가
한다.

운영 파일과 검증값은 다음과 같다.

| 항목 | 고정값 |
|---|---|
| Hailo pose | `runtime/models/yolov8s_pose_v2_15_h8.hef` |
| HEF SHA-256 | `e19856699ed47cf866d23265827f960b263f287dab5e54e82c7ce37e12525a2d` |
| EdgeFallKit | `suharvest/edgefallkit` |
| 고정 commit | `ef3bda2fd865fe6b80119fb1c896a63bfc4228ee` |
| 로컬 C ABI | `native/edgefall_shadow/edgefall_c_api.cpp` |
| 로컬 정책 patch | `native/edgefall_shadow/strict_confirmation.patch` |
| 분석 목표 | 15 FPS |
| keypoint 기준 | 0.25 |

`shadow`가 들어간 네이티브 파일명과 C 함수명은 이미 검증한 ABI와 재현 가능한
빌드를 깨지 않기 위해 유지한다. 현재 정책은 Shadow가 아니며 Python adapter가
표준 MQTT 경보를 발행한다.

## 2. 2026-10-19에 바뀐 것

### 실행에서 제거

- YOLO11n-Pose NCNN 모델 3종과 YOLO11n 객체 모델
- `ncnn` Python 패키지
- `NcnnPoseEstimator`, `NcnnObjectDetector`
- 가장 큰 사람 한 명을 보던 `RuleFallDetector`
- B76 3-seed GRU 배포 가중치와 NumPy runtime
- Rule/GRU용 Shadow JSONL 생성과 요약 스크립트
- NCNN와 Hailo를 같은 프레임에서 동시에 돌리던 병렬 비교

과거 AI Hub 연구 결과, 분할 방식, 평가 CSV와 설계 문서는 삭제하지 않았다.
즉 실패한 접근은 발표와 재현용 기록으로 남되 운영 프로세스는 로드하지 않는다.
기존 JSONL 관측 로그도 기록 보존 목적으로 유지한다.

### 실행에 승격

- Hailo YOLOv8s-Pose를 Dahua의 유일한 pose backend로 사용
- 대시보드를 열지 않아도 15 FPS 목표로 계속 분석
- EdgeFall 상태를 Pi4가 이미 이해하는 표준 `fall_*` 이벤트로 변환
- 동일 native `event_id` 재전송 방지
- 추적이 사라진 채 2초가 지나면 `fall_cleared`를 보내 경보 고착 방지
- 대시보드에는 Hailo/EdgeFall 운영 상태만 표시

전환 전 실측은 CPU 136%, RSS 약 531MB였다. 당시 한 Dahua 프레임에 NCNN pose
약 9.5 FPS, Hailo 약 13 FPS, B76 GRU를 중복 실행하고 있었다. 전환 후에는 Hailo
pose 한 번의 메타데이터를 사람 표시와 EdgeFall이 함께 사용하므로 NCNN 추론과
GRU 계산, 중복 관절 오버레이가 사라진다.

재시작 후 대시보드 미접속 상태의 초기 실측:

| 항목 | 전환 전 병렬 경로 | 전환 후 단일 경로 |
|---|---:|---:|
| Dahua pose | NCNN 9.5 FPS + Hailo 13.1 FPS | Hailo 14.0 FPS |
| Hailo 평균 / p95 | 16.25 / 23.49 ms | 15.84 / 24.18 ms |
| pose 입력 age | 65.18 ms | 2.08 ms |
| 프로세스 RSS | 약 531 MB | 약 414 MB |
| 프로세스 CPU 초기 평균 | 약 136% | 약 120% |

CPU 감소가 메모리만큼 크지는 않다. RTSP decode, GStreamer와 5 FPS 얼굴 인식은
계속 CPU를 사용하기 때문이다. 중요한 변화는 대시보드를 닫아도 약 14 FPS를
유지하면서 pose 입력 age가 낮고 과거 프레임을 누적하지 않는다는 점이다.

## 3. GitHub에서 가져온 EdgeFallKit은 무엇을 하는가

### 3.1 공간 모델: YOLOv8s-Pose

Hailo HEF는 한 프레임에서 다음을 낸다.

- 사람 bounding box와 confidence
- COCO 형식 17개 관절의 x, y, confidence

Python은 GStreamer의 Hailo metadata만 받아 원본 960x540 좌표로 복원한다.
Hailo 파이프라인에 화면 표시나 JPEG 인코딩 분기를 넣지 않았다. 그래서 추론은
브라우저 표시 부하와 분리된다.

### 3.2 사람별 tracker

EdgeFallKit tracker는 IoU와 중심 거리로 프레임 간 사람을 연결한다. 각 track은
자기 pose history, temporal classifier, fall state와 event ID를 가진다. 따라서
과거 Rule처럼 화면에서 가장 큰 사람 하나만 판정하지 않는다.

### 3.3 48-frame temporal MLP

Hailo 전용 profile은 15 FPS 기준 48프레임, 약 3.13초의 움직임을 본다.

```text
frame feature: 56
  = 17 joints x (x, y, confidence) + 5 global values

sequence summary: 504
  = 6 temporal-bin means (6 x 56)
  + per-feature standard deviation (56)
  + first-to-last delta (56)
  + min/max span (56)
```

504개 값을 학습 시 mean/scale로 정규화한 뒤 다음 작은 MLP로 계산한다.

```text
504 -> hidden 16 + ReLU -> sigmoid fall probability
threshold 0.75
3회 연속 기준 충족
3프레임마다 평가
```

여기서 `temporal probability`는 최종 경보 그 자체가 아니다. pose가 시간적으로
낙상과 닮았는지를 나타내는 한 증거다.

### 3.4 기하·시간 상태기계

상태는 다음 순서로 움직인다.

```text
normal -> suspected -> fallen -> recovering -> normal
```

사용하는 관측값은 골반 하강 속도와 거리, 몸통의 수직 대비 각도, 사람 박스의
가로/세로 비율, temporal probability다. 단일 프레임이나 단일 값만으로 최종
낙상을 만들지 않는 것이 핵심이다.

## 4. 우리가 수정한 부분

Upstream을 그대로 실행한 것이 아니다. 고정 commit 위에
`strict_confirmation.patch`를 항상 다시 적용한다.

### 수정 1: Hailo 골반 Y 좌표 정규화

Upstream Hailo adapter는 `hip_y`를 640 픽셀 좌표로 상태기계에 넘겼다. 시간 모델과
상태기계는 0~1 정규화 좌표를 기대하므로 정상적인 0.5가 약 320으로 들어가는
domain 오류가 있었다. 이를 `hip_y / 640`으로 수정했다.

### 수정 2: temporal 양성 하나만으로 Fallen 금지

Upstream에는 normal 상태에서 temporal MLP만 양성이어도 즉시 fallen으로 가는
분기가 있었다. 손만 움직여도 `낙상 후` 확률이 높게 나왔던 현상과 결합하면
오탐을 만들 수 있어 제거했다. temporal 값은 motion과 자세 후보를 보강할 뿐이다.

### 수정 3: 충격과 최종 자세가 다른 프레임에 나타나는 경우

실제 영상에서는 골반이 빠르게 내려가는 프레임과 몸이 완전히 수평이 되는
프레임이 일치하지 않았다. 다음 조건을 1.5초 candidate window로 연결했다.

```text
강한 하강: speed >= 0.50/s and normalized drop >= 0.04
최종 자세: torso >= 65 degrees and bbox width/height >= 1.50
```

### 수정 4: 카메라 방향으로 넘어지는 foreshortening

앞뒤 깊이 방향으로 쓰러지면 2D box가 충분히 넓어지지 않는다. candidate가 이미
arm된 상태에서 다음 자세가 0.80초 유지되면 확인하는 보조 경로를 추가했다.

```text
torso >= 75 degrees
bbox width/height >= 0.90
continuous >= 0.80 seconds
```

이 보조 경로도 먼저 motion candidate가 있어야 하므로 가만히 누워 있는 사람은
낙상을 새로 만들 수 없다.

### 수정 5: Pi4 MQTT 계약 adapter

EdgeFallKit 내부 상태명을 그대로 새 토픽으로 만들지 않았다. 기존 Pi4 코드와
스피커를 수정하지 않도록 다음 계약으로 번역한다.

| EdgeFall | MQTT `event_type` | Pi4 동작 |
|---|---|---|
| suspected 진입 | `fall_suspected` | 위험 상태 표시 |
| 새 fall event | `fall_confirmed` | 경보·TTS 활성화 |
| 정상 복귀 | `fall_cleared` | 경보 해제 |

Payload에는 `backend=hailo_edgefall`, track ID, EdgeFall event ID, temporal
probability, 골반 하강, 몸통 각도와 box 비율을 함께 넣는다. MQTT는 QoS 1이며
native event ID를 기억해 같은 경보를 여러 번 발행하지 않는다.

## 5. 이전 방식이 실패한 원인

### YOLO11 NCNN + Rule

- 320 입력 CPU pose가 약 10 FPS였고 Hailo 비교와 함께 실행하면 CPU를 크게 썼다.
- 가장 큰 사람 하나의 순간 몸통 각도와 box 비율에 의존했다.
- 의자에 앉기, 바닥에 앉기, 몸 숙이기와 눕기를 카메라 구도에 따라 혼동했다.
- 상태 표시, 실제 Rule 경보, GRU 분류가 서로 달라 사용자가 결과를 해석하기
  어려웠다.

### 자체 B76 3-seed GRU

연구 자체가 무의미한 것은 아니다. actor/scenario leakage를 막고 세 seed를 평균한
것은 올바른 연구 절차였다. 그러나 운영 domain이 달랐다.

- 학습 pose: Mac에서 YOLO11n-Pose, 960 입력, 10 FPS
- 초기 Pi 배포 pose: YOLO11 NCNN, 320 입력, confidence와 가시성이 다름
- 학습 영상: 짧고 정돈된 AI Hub 연기 영상
- 현장 영상: 가림, 여러 사람, 바닥·침대, 렌즈 왜곡, 프레임 이탈
- 손·상체 동작만으로 `fallen` class score가 커지는 사례가 있었다.
- class score와 이벤트 상태를 한 화면에 같이 보여 “낙상 후”가 경보처럼 보였다.

pose frontend와 sampling domain이 바뀌면 같은 20프레임 GRU를 그대로 쓸 수 없다.
Hailo pose로 전환하면서 GRU를 다시 붙이는 것은 또 하나의 domain mismatch가 되므로
운영에서 제거했다.

### 중복 파이프라인

문제는 Hailo 성능보다 표시·중복 처리였다. 공식 Hailo metadata-only는 약 31.75
FPS였지만 Python에서 NCNN, Hailo, GRU, MJPEG 오버레이를 동시에 켜면 전체가
느려졌다. 이번 구조는 Hailo 추론 결과를 재사용하고 JPEG는 시청자가 있을 때만
만드는 원칙으로 돌아갔다.

## 6. 전면은 잘 되고 측면·후면은 왜 놓쳤는가

최근 로그에서 측·후면 낙상 때 person box는 남아도 hip/shoulder keypoint confidence가
떨어져 EdgeFall track이 `valid=false`가 됐다. 사람 박스가 화면 상·좌·하단에
동시에 닿고 track ID가 여러 번 바뀐 사례도 있었다. 이 상태에서는 threshold를
낮춰도 존재하지 않는 다리·골반 좌표를 복원할 수 없다.

따라서 다음 우선순위는 모델 재학습이 아니라 구도다.

- 머리부터 발끝, 착지 매트까지 항상 포함
- 화면 가장자리 10~15% 여백
- 카메라 높이 약 1.7~2.0m
- 아래 방향 20~30도
- 낙상 진행 방향에 대해 정면 고정 대신 30~45도 대각선

구도 변경 뒤 전면·측면·후면 각 5회와 빠른 앉기·숙이기·천천히 눕기를 다시
기록한다. 측후면 keypoint 가시성이 확보된 뒤에도 미탐이면 그때 profile과 모델을
조정한다.

## 7. Camera Module 3 얼굴 인식 개선

기존 얼굴 박스가 늦었던 직접 원인은 `analysis_fps: 0.5`였다. 카메라는 15 FPS여도
얼굴 결과는 2초마다 한 번 갱신됐다. 이를 5 FPS로 올리고, 최신 검출을 68% 반영하는
EMA box smoothing을 적용했다. 오래된 프레임 queue는 만들지 않는다.

수동으로 정면·왼쪽·오른쪽 버튼을 세 번 누르는 절차도 제거했다. 한 번 `자동
다각도 등록`을 누르면 약 10초 동안 다음을 수행한다.

1. 정면을 본다.
2. 고개를 한쪽으로 천천히 돌린다.
3. 반대쪽으로 돌린다.
4. YuNet 눈·코 landmark로 yaw를 추정한다.
5. 초점, 단일 얼굴, 과도한 측면 여부를 검사한다.
6. 정면·양쪽에서 각각 최소 3개 SFace embedding을 평균한다.
7. 얼굴 사진은 버리고 세 방향 embedding만 `data/faces.json`에 저장한다.

이것은 정부 앱의 실제 3D 얼굴 스캔과 동일하지 않다. depth sensor를 쓰는 3D
재구성이나 spoof/liveness 보증이 아니라, 화면 안내를 따르는 연속 multi-view
template 등록이다. 졸업작품의 각도 변화 인식률을 높이는 현실적인 단계다.

등록은 관리 키 없이 가능하고, 목록 조회와 삭제만 관리 키 및 30일 HttpOnly
세션으로 보호한다. 이미 등록된 사람은 같은 이름으로 자동 등록하면 세 방향
template가 교체된다.

## 8. 현재 한계와 발표에서 지켜야 할 표현

- 전면 연기 낙상은 반복 감지됐지만 측면·후면은 구도 변경 후 재검증이 필요하다.
- 사전학습 모델과 로컬 정책은 의료기기 정확도 검증을 통과한 것이 아니다.
- 현재 결과를 “모든 낙상을 정확히 감지한다”고 발표하면 안 된다.
- 정확한 표현은 “Hailo 가속 pose와 사전학습 시간 분류, 현장 오탐 억제 정책을
  결합한 POC이며 방향별 현장 검증을 진행 중”이다.

발표용 한 문장:

> Raspberry Pi 5의 Hailo-8에서 YOLOv8s-Pose로 사람 관절을 실시간 추출하고,
> 약 3.1초의 자세 변화를 학습한 EdgeFall 시간 분류기와 낙상 상태기계를 결합해
> 확정 이벤트만 Raspberry Pi 4의 MQTT 경보 시스템으로 전달했습니다.

## 9. 다음 검증 순서

1. 변경한 Dahua 구도에서 전·측·후면 각 5회 안전 연기
2. 빠른 앉기, 숙이기, 천천히 눕기 각 10회 오탐 확인
3. `fall_confirmed`와 `fall_cleared`가 Pi4 MQTT/스피커에 한 번씩 도달하는지 확인
4. 대시보드를 닫은 상태에서도 Hailo 분석과 MQTT가 계속되는지 확인
5. Camera Module 3 자동 다각도 등록 후 정면·좌우 인식 시험
6. Pi5 2시간 soak test에서 CPU, RSS, 온도, RTSP buffer age 기록

운영 상태 확인:

```bash
curl -s http://127.0.0.1:8080/api/status
journalctl -u smarthome-vision.service -f
```

EdgeFall 재현 빌드:

```bash
./scripts/setup_edgefall_shadow.sh --accept-upstream-license
```

스크립트의 역사적 이름과 무관하게 생성 결과는 현재 운영 runtime에서 사용한다.
