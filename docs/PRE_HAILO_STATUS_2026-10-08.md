# Hailo 장착 전 비전·통합 상태

기준일: 2026-10-08  
기준 저장소: `/home/pi/Home-Safety-System`  
비전 런타임 커밋: `73ed162`

## 1. 결론

Hailo가 없는 Raspberry Pi 5 CPU에서도 현재 구성은 다음 범위까지 동작한다.

- 세 카메라 동시 수집과 개발 대시보드 표시
- Dahua 1920×1080 메인 스트림의 YOLO11n-pose NCNN 320 추론 약 9.7 FPS
- 사람별 20프레임/10 FPS B76 GRU ensemble shadow 추론
- ABKO 웹캠의 얼굴 등록·인식
- Pi5 MQTT → Pi4 collector → PostgreSQL → Pi4 웹 API 왕복
- 브라우저가 Pi4를 영상 프록시로 사용하지 않고 Pi5 MediaMTX WebRTC에 직접 연결

그러나 **낙상 모델을 실제 경보 판단기로 승격할 단계는 아니다.** 기존 rule 경로는
MQTT active 상태지만 전시장 장면에서 상태가 자주 흔들렸고, GRU도 Balanced
프로필의 짧은 관찰에서 shadow 확정이 반복됐다. 현재 GRU는 Quiet 프로필로 비교
관찰 중이며 MQTT를 발행하지 않는다.

## 2. 현재 전체 구조와 담당 경계

```text
Dahua RTSP / Camera Module 3 / ABKO V4L2
                    │
                    ▼
        Raspberry Pi 5 (data plane)
        - 카메라 수집과 BGR 통일
        - pose / face / fall 추론
        - overlay와 개발 대시보드 :8080
        - MQTT 상태·사건 발행
        - MediaMTX WebRTC :8889/:8189
                    │
            MQTT JSON │ 영상은 직접 경로
                    ▼
        Raspberry Pi 4 (control plane)
        - Mosquitto :1883
        - PostgreSQL
        - collector / automation
        - 최종 웹·경보 취소 :8081
                    ▲
                    │
        브라우저 ────┴── Pi5 WebRTC 직접 수신
```

비전 담당 범위는 Pi5에서 `pose → tracking → temporal classifier → state/event`를
안정화하고 MQTT 계약을 지키는 데까지다. DB 보존, 최종 경보 상태, 스피커/부저,
사용자 웹은 Pi4 영역이지만 비전 event가 그 구조에 정상적으로 들어가는지 통합
시험까지 수행한다.

## 3. 카메라별 확정 역할

| 카메라 | 수집 방식 | 현재 역할 | 낙상 GRU |
|---|---|---|---:|
| Camera Module 3 | Picamera2, 960×540, 15 FPS | 보조 시점·감시 | 끔 |
| ABKO APC720 | V4L2 MJPG, 1280×720, 15 FPS | 얼굴 등록·인식 | 끔 |
| Dahua 192.168.1.64 | RTSP/TCP 메인 스트림, 실제 1920×1080 약 15 FPS 수집 | 주 낙상 카메라 | 켬 |

세 입력은 장치 단계의 형식이 다르지만 분석 시점에는 OpenCV BGR 배열로 통일된다.
AI 처리는 MJPEG/H.264/WebRTC 변환 전에 수행한다. Camera Module 3 동의를 Dahua
낙상 경보의 필수 조건으로 사용하지 않는다.

## 4. 현재 낙상 처리 경로

```text
Dahua의 새 캡처 프레임
  → YOLO11n-pose NCNN 320
  → person bbox + COCO 17 keypoints
  → motion-prediction 기반 사람별 track
  → B76 feature 20개 (10 FPS, 약 2초)
  → B_76_sqrt 3-seed NumPy GRU ensemble
  → normal / falling / fallen 평균 확률
  → shadow 상태 머신
```

동일한 정지 프레임이 여러 번 temporal buffer에 들어가지 않도록 capture frame
sequence를 검사한다. 입력이 멈추면 중복 프레임을 넣는 대신 기다린다. API에는
다음 진단값을 제공한다.

- capture frame sequence와 capture FPS
- pose 목표/실효 FPS
- pose 평균/p95 지연
- 캡처부터 pose 입력까지의 frame age
- 처리한 고유 프레임, 건너뛴 source 프레임, 방지한 중복 프레임 수
- track별 확률·buffer·miss·age·cooldown
- 관절 가시율, 유효 프레임 비율, bbox 면적과 화면 가장자리 접촉

## 5. 모델과 운영 프로필

### Pose

현재 CPU 운영 모델:

```text
models/yolo11n-pose_ncnn_model
input size 320
confidence 0.10
threads 4
target 10 FPS
```

640/960 모델은 Hailo 후보로 보존하지만 CPU 운영에는 사용하지 않는다.

### Temporal GRU

```text
models/fall_gru/b76_sqrt_ensemble/numpy
20 frames × 76 features
sample rate 10 FPS
three seeds, mean probability
```

현재 프로필:

```text
mode        shadow
profile     Quiet development profile
threshold   0.89
consecutive 4
release     3 frames
cooldown    5 seconds
```

GRU transition은 Pi5 로컬 이벤트와 JSONL에만 남고 Pi4 MQTT 경보로 발행하지 않는다.

기존 `RuleFallDetector`는 fallback으로 유지하며 현재 `rule.mode: active`다. 설정은
`active`와 `shadow`를 지원하고 API/대시보드가 현재 모드를 표시한다. 실제 최근
장면에서 rule event가 빈번했으므로, 이를 `shadow`로 바꾸는 것은 안전 기능을
일시 차단하는 결정이다. 사용자 승인 없이 자동 변경하지 않는다.

## 6. Pi5 실측 결과

### 동일 프레임 NCNN 단독 벤치마크

| 모델 | confidence | 평균 | p95 | 이론 최대 처리량 | 판단 |
|---|---:|---:|---:|---:|---|
| 320 | 0.10 | 18.1 ms | 18.8 ms | 55.2 FPS | CPU 운영 가능 |
| 640 | 0.03 | 78.7 ms | 82.9 ms | 12.7 FPS | 전체 서비스에서는 부족 |
| 960 | 0.03 | 186.8 ms | 191.9 ms | 5.35 FPS | CPU 운영 불가 |

640/960 export는 기존 320 export와 score calibration이 다르다. `0.10`에서는 같은
장면의 사람이 거의 모두 탈락했고 `0.03`에서 검출이 회복됐다. 모델 해상도만 바꿀
때 confidence를 그대로 복사하면 안 된다.

### 3카메라 전체 서비스

640 시험:

```text
Dahua capture        8.3 FPS
pose effective       7.88 FPS
pose mean / p95      95.36 / 108.81 ms
duplicate prevented  39
```

20프레임을 약 2초에 넣어야 하는 GRU 계약을 만족하지 못해 320으로 복구했다.

320 복구 후 대표 측정:

```text
Dahua capture        약 14.8~15.0 FPS
pose effective       약 9.75~9.77 FPS
pose mean / p95      약 29.6~30.5 / 38.6~44.9 ms
process RSS          약 452 MiB
process CPU          약 139% (멀티코어 합산)
temperature          55.4 °C
throttled            0x0
root filesystem      58 GiB 중 14 GiB 사용, 42 GiB 여유
```

현재 병목은 열 throttling이 아니라 고해상도 pose CPU 연산이다.

벤치마크 재실행:

```bash
cd /home/pi/Home-Safety-System
sudo systemctl stop smarthome-vision.service
PYTHONPATH=src .venv/bin/python scripts/benchmark_pose_ncnn.py \
  --frames 20 --warmup 3 --json
sudo systemctl start smarthome-vision.service
```

중간 실패 시에도 서비스를 반드시 다시 시작한다.

## 7. Shadow 관찰과 현재 위험

원본 영상과 얼굴을 저장하지 않고 다음 파일에 1초 주기 메타데이터만 기록한다.

```text
runtime/fall-shadow-observations-quiet.jsonl
runtime/fall-shadow-observations-quiet.jsonl.1
```

파일당 최대 20 MiB이며 한 세대만 순환 보관한다. `runtime/`은 Git 제외다.

Balanced 프로필(`0.92`, 연속 1프레임)의 약 6분 초기 관찰:

```text
records                    358
unique tracks              16
ready track observations   388
quality eligible ratio     28.87%
max alert score            0.9996
shadow confirmed           13
shadow cleared             6
frame-edge-clipped flags   309
```

13개 확정 중 8개는 낮은 관절 가시율/누락/화면 가장자리 잘림 플래그가 있었고,
5개는 품질 플래그가 없었다. 실제 정답 라벨이 없는 관찰이므로 13개를 모두 오탐이라고
단정할 수는 없지만, active 승격이 불가능하다는 근거로는 충분하다. Quiet 프로필은
별도 로그에서 새로 비교한다.

Quiet 적용 직후 약 253초의 초기 관찰에서는 247개 record, 하나의 지속 track,
최대 alert score 0.3586, shadow transition 0회였다. 짧고 실제 낙상 동작이 없었던
구간이므로 성능 결론이 아니라 설정·로깅 정상 여부 확인으로만 사용한다.

요약 명령:

```bash
cd /home/pi/Home-Safety-System
.venv/bin/python scripts/summarize_shadow_log.py --json

# 과거 Balanced 로그를 따로 확인할 때
.venv/bin/python scripts/summarize_shadow_log.py \
  runtime/fall-shadow-observations.jsonl --json
```

품질 플래그는 현재 진단 전용이다. 이를 바로 hard gate로 사용하면 화면 가장자리에서
실제로 넘어지는 사람을 놓칠 수 있으므로, 라벨이 붙은 자체 시험 뒤 결정한다.

## 8. Pi4 통합 실측

2026-10-08 확인 결과:

- `http://192.168.1.10:8081/health`: 정상
- `/api/vision/health`: Pi5 연결, 카메라 3대 online, WebRTC true
- Pi5 MQTT 연결: true
- 비경보 `integration_probe`: Pi4 DB와 overview API 왕복 성공
- 같은 event_id 2회 QoS1 발행: DB 저장 1행, 중복 방지 성공
- Pi4가 수신한 retain status에 pose FPS·지연·track 품질 필드까지 포함
- `cam3`, `webcam`, `dahua` on-demand 경로 모두 H.264 640×360/15 FPS 실측
- 각 검사 종료 약 10초 후 FFmpeg publisher 자동 종료 확인

Pi4 SSH는 현재 `publickey,password` 인증 실패라 Pi5에서 원격 셸을 실행할 수 없다.
CLI Git 인증을 추가하지 않겠다는 운영 원칙과 별개로, 재부팅/컨테이너 로그/DB 직접
검사는 Pi4 로컬 터미널 또는 협업자의 VS Code 세션에서 수행해야 한다.

Pi5 WebRTC는 `smarthome-mediamtx.service`가 enabled/active이며, 시청자가 있을 때만
카메라별 FFmpeg publisher를 `runOnDemand`로 실행한다. 존재하지 않는
`mediamtx.service`나 상시 publisher unit을 상태 기준으로 사용하지 않는다.

## 9. 테스트 상태

Pi5에서 다음 명령으로 24개 테스트가 통과했다.

```bash
cd /home/pi/Home-Safety-System
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

검증 범위:

- 얼굴 등록 API 권한 분리와 다각도 template
- rule detector 기본 상태 전이
- 발목이 보이는 바닥 앉음의 무릎 각도/엉덩이-무릎 높이 판정
- Pi4 MQTT 스피커 경보 payload 처리
- Pi4 WebRTC 화면/health 계약
- B76 feature shape와 global feature
- tracker motion prediction
- GRU shadow 확정/해제/cooldown
- 품질 지표가 아직 경보를 차단하지 않는 조건
- JSONL rate limit과 rotation

PyTorch는 Pi5 운영 venv에 설치하지 않는다. NumPy GRU artifact 무결성과 Mac의
PyTorch parity 결과를 사용하며, Pi5에는 배포에 필요한 런타임만 둔다.

## 10. Hailo 전 남은 검증

### 비전 담당

1. 전시장 Dahua 구도에서 최소 30분 일상동작(걷기, 앉기, 숙이기, 바닥 물건 줍기)을
   수행하고 Quiet 로그의 shadow 확정 수를 기록한다.
2. 안전 매트와 보조 인원을 두고 전방/측방/후방 연기 낙상을 각 5회 수행한다.
3. 연기 시작/바닥 도달 UTC 시각과 track ID만 기록해 JSONL과 대조한다.
4. event recall, 바닥 도달 후 지연, ADL 오탐, track 분절을 계산한다.
5. Quiet 프로필이 부족하면 임의 threshold 조정보다 실제 전시장 hard-negative를
   Mac 학습 데이터에 추가한다.
6. rule과 GRU 중 어느 경로를 전시 active로 사용할지 결과표로 결정한다.

### 전체 시스템 담당과 함께 할 일

1. Pi4 화면에서 현재/시험 경보를 관리 키로 취소하는 흐름 확인
2. ~~`home/safety/fall/alarm`을 실제 스피커/부저 출력에 연결~~
   - Pi4 3.5 mm 출력의 `smarthome-audio-alarm.service`로 구현·실기 시험 완료
   - `active=true`에서 반복 재생, 화면 취소/해제의 `active=false`에서 즉시 정지
3. Pi4 로컬에서 Compose 상태·로그와 DB 중복 SQL 확인
4. Pi4/Pi5 동시 재부팅 후 3분 이내 자동 복구 시험
5. 세 WebRTC 영상 + Pi4 UI + Pi5 AI를 2시간 유지하며 재시작·메모리 증가 확인
6. 전시장 LAN 확정 후 MQTT 익명 접속을 계정 방식으로 전환

재부팅과 실제 경보/스피커 시험은 서비스 중단·소음·안전 영향이 있으므로 현장
사용자 승인 아래 수행한다.

## 11. Hailo가 도착하면 유지할 인터페이스

Hailo 적용 때 바꿀 것은 `NcnnPoseEstimator` 구현과 pose artifact다. 다음 계약은
유지한다.

```python
[
  {
    "confidence": float,
    "box": [x1, y1, x2, y2],
    "keypoints": [[x, y, confidence], ... 17개]
  }
]
```

따라서 tracker, B76 feature, NumPy GRU, rule fallback, MQTT schema, Pi4 DB/web는
그대로 둔다. Hailo 전환 순서는 다음과 같다.

1. HailoRT와 장치 상태 확인
2. 공식 지원 pose 모델 한 스트림 벤치마크
3. 현재 NCNN과 bbox/keypoint 좌표·confidence calibration 비교
4. Dahua 한 대 shadow A/B
5. 10 FPS 이상·동일 이벤트 계약 확인
6. 필요할 때 Camera Module 3 보조 pose를 추가

Hailo-8은 추론 가속기이며 모델 학습기는 아니다. 학습·재학습·평가는 Mac mini M4
또는 호환되는 별도 학습 환경에서 수행한다.

## 12. 완료 판정

Hailo 전 소프트웨어 기반은 구현됐다. 다만 비전 기능의 **전시 경보 완료** 판정은
아래 세 항목이 남아 있다.

- 라벨이 있는 현장 ADL/낙상 반복 시험
- rule 또는 GRU active 경로의 명시적 선택
- Pi4 경보 취소·스피커·동시 재부팅·2시간 soak test

현재 상태는 `CPU 실시간 shadow 통합 완료, 낙상 경보 임계값 검증 중`으로 표현한다.


## 13. 2026-10-08 현장 준비 보완

- Dahua RTSP에는 FFmpeg `nobuffer`, `low_delay`, `max_delay=0`을 적용했다.
- Dahua 메인스트림은 1920×1080, H.264 High, 15 FPS, CBR 4096 kbps를 유지하고
  GOP를 30에서 15로 줄여 키프레임 간격을 2초에서 1초로 줄였다.
- 대시보드의 카메라 `상태`는 낙상 상태가 아니라 연결 상태였으므로 `연결`로
  이름을 바꿨다. `지연`도 종단 지연이 아니라 Pi5 최신 프레임 age이므로 명확히
  표시한다.
- Rule은 가장 큰 사람 1명, GRU는 사람별 track 중 alert score가 가장 높은 track을
  표시하므로 서로 다른 사람을 가리킬 수 있다.
- GRU의 `falling`/`fallen` 클래스는 곧바로 경보가 아니다. 임계값 연속 충족 여부를
  별도 Shadow 배지로 표시하며 GRU 결과는 아직 MQTT로 전송하지 않는다.
- Shadow JSONL 스키마 1.1은 같은 시점의 Rule 결과와 GRU track을 함께 기록한다.
- 현장 정의·카메라 위치·TP/FP/FN/지연 기록법은
  `docs/FIELD_FALL_VALIDATION.md`를 기준으로 한다.
