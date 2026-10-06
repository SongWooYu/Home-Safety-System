# AI 기반 스마트홈 · 카메라 낙상감지 프로젝트 인수인계 / 연구·개발 컨텍스트

> 작성 기준일: 2026-10-06  
> 목적: **새 ChatGPT 채팅에서 이 파일 하나를 업로드해도 지금까지의 연구·개발 맥락, 로컬 경로, 실험 결과, 설계 판단, 남은 작업을 최대한 그대로 이어가기 위한 인수인계 문서**
>
> 프로젝트 큰 주제: **AI 기반 스마트홈 및 낙상감지 시스템**  
> 현재 집중 영역: **Raspberry Pi 5 카메라 기반 낙상감지 모델 — YOLO11n-Pose + Temporal GRU**

---

# 0. 새 채팅에서 가장 먼저 읽을 핵심 요약

현재 낙상감지 방향은 **단일 프레임에서 `fallen/normal`을 YOLO 객체분류로 직접 맞히는 방식이 아니라**, 다음 구조로 정리되어 있다.

```text
RGB Camera
  ↓
Pretrained YOLO11n-Pose
  ↓
사람별 17개 COCO keypoint + bbox + confidence
  ↓
track_id별 시간축 skeleton sequence
  ↓
정규화 pose + confidence/mask + bbox/global motion + dynamics
  ↓
작은 GRU temporal classifier
  ↓
상태/낙상 score
  ↓
threshold + consecutive frames + hysteresis/release + cooldown
  ↓
MQTT risk/event
```

현재까지 가장 유력한 temporal model은 **GRU v2**이다.

- 입력: **20 frames ≈ 2초**
- 샘플링: **10 FPS**
- frame feature: **125 dimensions**
- GRU: hidden 128, 2 layers, dropout 0.2
- 3 classes:
  - `0 = normal`
  - `1 = falling`
  - `2 = fallen`
- Validation best:
  - **Macro-F1 = 0.83948**
  - best epoch = 3
- corrected event evaluation에서 현재 세 후보 중 **v2가 가장 좋은 실용 trade-off**를 보였다.

중요한 현재 결론:

1. **YOLO11n-Pose 960 / conf 0.10**은 Mac M4에서 AI Hub Validation 2,272개 전체에 대해 pose cache 생성 완료.
2. AI Hub 공식 Validation 2,272개를 내부적으로 actor-disjoint train/val/test로 나누어 **개발용 실험**을 했다.
3. 그러나 이 공식 Validation을 학습/선택에 사용했으므로 **최종 논문 성능용 untouched validation이라고 부르면 안 된다.**
4. 특히 내부 test는 v1 평가에서 이미 열어봤고 그 결과를 보고 v2를 설계했으므로, **현재 내부 test 역시 최종 독립 test가 아니다.**
5. 최종 연구 성능을 정식으로 제시하려면 **AI Hub Training 원천데이터를 확보하여 train용으로 사용하고 공식 Validation을 다시 untouched evaluation set으로 남기는 것이 권장된다.**
6. 현재 `FA/hour`는 10초짜리 staged clip에서 환산한 값이라 **제품의 실제 시간당 오경보 사양으로 해석하면 안 된다.**
7. 제품 수준 오경보 평가는 긴 ADL(non-fall) 연속 영상이 반드시 추가로 필요하다.
8. 실제 Raspberry Pi 5 배포는 아직 **960 pose 추론 속도와 전체 파이프라인**을 실제 장치에서 검증하지 않았다. Mac M4 결과를 Pi 성능으로 간주하면 안 된다.

현재 corrected validation event 비교에서:

```text
TARGET95 = 낙상 종료 +1초 이내 recall >= 95%를 만족하는 설정 중 오경보 쪽을 우선
LOW_FA   = non-fall 10초 clip 중 false alarm 발생 비율 <= 10%인 설정 중 recall 우선
```

### Strict / TARGET95

| 모델 | Threshold | Consecutive | Recall +1s | Recall +2s | Median latency | FA/hour* | Nonfall clip FA |
|---|---:|---:|---:|---:|---:|---:|---:|
| v1 | 0.900 | 4 | 95.22% | 97.43% | 0.6006s | 130.24 | 17.05% |
| **v2** | **0.550** | **9** | **95.22%** | **97.43%** | 1.0000s | **103.21** | **13.64%** |
| binary | 0.300 | 10 | 95.22% | 97.79% | 1.1000s | 167.10 | 21.59% |

이 operating point에서는 **v2가 v1보다 동일한 +1s recall을 유지하면서 FA/hour와 nonfall clip FA를 낮췄다.**

### Strict / LOW_FA

| 모델 | Threshold | Consecutive | Recall +1s | Recall +2s | Median latency | FA/hour* | Nonfall clip FA |
|---|---:|---:|---:|---:|---:|---:|---:|
| v1 | 0.970 | 9 | 87.13% | 91.18% | 1.2000s | 51.61 | 9.09% |
| **v2** | **0.950** | **4** | **91.54%** | **93.38%** | **0.6006s** | 76.18 | 9.09% |
| binary | 0.995 | 1 | 85.66% | 90.81% | 0.6006s | 56.52 | **7.95%** |

`nonfall clip FA <= 10%`라는 같은 제한 아래에서는 **v2가 가장 높은 +1s recall(91.54%)**을 보였다.

> \* `FA/hour`는 현재 짧은 AI Hub staged clip의 negative exposure를 시간당으로 환산한 값이다. 실제 가정 환경 장시간 오경보율과 동일하지 않다.

**따라서 현재 리딩 후보는 GRU v2이며, Binary GRU는 window-level AP는 높았지만 event-level trade-off에서는 v2보다 우위가 확인되지 않았다.**

---

# 1. 원래 프로젝트 목적

기존 스마트홈은 사용자가 앱이나 스위치로 직접 명령하거나 예약하는 형태가 많다. 이 프로젝트는 이를 다음 단계로 확장하는 것이 전체 목표이다.

```text
환경 센서 / 사용자 행동 / 카메라
        ↓
상황 인식 및 패턴 분석
        ↓
AI 판단
        ↓
IoT 자동 제어 + 안전 이벤트
        ↓
MQTT / DB / Web Dashboard / 알림
```

핵심 가치:

- 단순 원격 제어가 아니라 **상황을 이해하고 먼저 동작하는 스마트홈**
- 사용자 생활 패턴 기반 자동화
- 센서 기반 환경 인식
- Raspberry Pi 5 카메라 기반 낙상감지
- MQTT를 통한 모듈 간 연결
- 웹 대시보드 및 DB 기록
- 낙상 여부를 의료적으로 진단하는 것이 아니라 **확인이 필요한 위험 상태를 감지·통보하는 보조 시스템**

기존 프로젝트 문서에서는 Raspberry Pi 5 Vision Node가 카메라 프레임을 받아 사람 감지 → 자세 추정 → 상태 분류 → 위험 이벤트를 생성하고, 서버 측에서 MQTT/DB/Web과 연동하는 구조로 설계되어 있다.

---

# 2. 낙상감지에서 우리가 처음 해결하려고 한 문제

초기에는 다음과 같은 일반적인 접근을 검토했다.

```text
Camera frame
  ↓
YOLO object detector
  ↓
fallen / normal
```

그러나 이 방식에는 몇 가지 문제가 있다.

- 단일 프레임은 **시간적 변화**를 직접 표현하지 못한다.
- 침대나 소파에 정상적으로 누워 있는 상태와 낙상 후 누운 상태가 비슷할 수 있다.
- 사람의 위치/배경/카메라 각도에 데이터셋 편향이 생기기 쉽다.
- 실제 낙상은 `서 있음 → 중심 하강 → 자세 회전 → 바닥에 누움`과 같은 **동적 과정**이다.
- 스마트홈에서 원하는 것은 단순 `lying` 검출이 아니라 **fall event**이다.

그래서 최종적으로는 **Pose + Temporal model** 구조를 중심으로 실험하기로 했다.

---

# 3. 이론적 설계 근거

## 3.1 Pose estimation을 사용하는 이유

YOLO11n-Pose는 사람의 bounding box와 COCO 형식의 17개 인체 keypoint를 추정한다.

대표 keypoint:

```text
nose
left/right eye
left/right ear
left/right shoulder
left/right elbow
left/right wrist
left/right hip
left/right knee
left/right ankle
```

낙상에서는 RGB 원본 픽셀 전체보다 다음 정보가 직접적인 행동 특징이 된다.

- 몸 중심의 수직 이동
- bbox 높이/너비 비 변화
- torso orientation
- shoulder/hip orientation
- 머리/어깨/골반/발의 상대 위치
- 각 관절의 이동 속도
- 관절 검출 confidence
- 가림으로 인한 missing keypoint pattern

따라서 RGB 이미지를 temporal model에 직접 넣는 것보다 skeleton 기반 입력은 모델을 작게 만들 수 있고, Raspberry Pi 계열에서 운영하기에도 유리하다.

---

## 3.2 단일 프레임이 아니라 sequence를 사용하는 이유

낙상은 상태(state)보다 사건(event)에 가깝다.

```text
Normal
 ↓
balance loss / body descent
 ↓
Falling
 ↓
impact / ground contact
 ↓
Fallen
```

따라서 연속 프레임의 변화를 모델링해야 한다.

우리의 기본 sequence는:

```text
10 FPS × 2 sec = 20 frames
```

이며 **causal window**만 사용한다.

```text
t-1.9s ---------------- t
        20 frames
                        ↑
                  현재 판정
```

미래 프레임을 사용하지 않는다. 실제 실시간 시스템과 동일한 조건을 유지하기 위한 것이다.

---

## 3.3 GRU를 선택한 이유

GRU(Gated Recurrent Unit)는 RNN 계열의 temporal model로, 짧은 시계열의 상태 변화를 적은 파라미터로 학습할 수 있다.

장점:

- LSTM보다 비교적 단순
- 20-frame skeleton sequence에는 충분한 표현력
- Raspberry Pi에서 사용할 수 있을 정도로 모델이 작음
- Pose → sequence 구조와 잘 맞음
- 선행 논문에서도 skeleton keypoint + engineered feature + GRU 구조가 사용됨

향후 TCN, 1D-CNN, ST-GCN, Transformer와 비교 가능하지만 **GRU를 baseline으로 먼저 정립**하는 전략을 사용했다.

---

## 3.4 confidence와 missing mask를 버리지 않은 이유

Pose detector가 일부 관절을 놓치는 것은 실제 환경에서도 발생한다.

예:

```text
무릎이 가림
발목이 프레임 밖
옆모습으로 반대쪽 팔 검출 약화
바닥에 누워 관절 중첩
```

낮은 confidence의 좌표를 억지로 실제 좌표처럼 사용하면 모델에 잘못된 정보를 넣게 된다.

따라서 joint마다 다음 정보를 같이 입력한다.

```text
x
y
confidence
mask
```

confidence가 낮으면:

```text
x/y = 0
mask = 0
confidence = 실제 값
```

으로 처리하여 모델이 **관절 위치가 0이라는 의미가 아니라 관측 신뢰도가 낮다는 사실**을 알 수 있게 했다.

---

# 4. 참고한 주요 논문 / 자료

## 4.1 강윤규, 숭실대학교 박사학위논문, 2021

**제목**

- 사람자세 추정을 이용한 딥러닝기반 낙상 탐지시스템
- *Deep Learning Based Fall Detection System Using Human Pose Estimation*
- 강윤규
- 숭실대학교 대학원 IT정책경영학과
- 2021년 6월

핵심 내용:

- 저가 2D RGB 카메라에서 PoseNet으로 skeleton keypoint 추출
- 머리·어깨 주요점의 위치 변화/가속도 등을 활용
- 낙상 후 자세 특징 활용
- 신체 주요점 이동 속도 활용
- bounding box width/height ratio 변화 활용
- 추출한 skeleton/engineered feature를 GRU에 입력
- raw skeleton만 사용하는 것보다 특징을 구성한 temporal approach가 낙상 판별에 효과적이라는 방향

우리 프로젝트에 준 영향:

```text
Pose detector
  ↓
skeleton / bbox
  ↓
시간 변화 특징
  ↓
GRU
```

라는 핵심 구조의 직접적인 연구 근거가 되었다.

---

## 4.2 김주연 · 최대수, 2025

**논문**

> A Study on the Performance of YOLOv8 Object Detection and Fall Detection Based on Pose Estimation from a Convergence Security Perspective  
> 융합보안 관점에서의 YOLOv8 객체 탐지와 Pose Estimation 기반 낙상 감지 성능 연구

- 김주연, 최대수
- 융합보안논문지, Vol.25 No.3, pp.147-152
- 2025
- DOI: `10.33778/kcsa.2025.25.3.147`
- https://doi.org/10.33778/kcsa.2025.25.3.147

핵심:

- YOLOv8 object detection과 YOLOv8-Pose 기반 낙상 분석 비교
- 객체탐지 모델은 높은 정량 성능을 냈음
- Pose 방식은 자세 변화 분석에 유용하지만 keypoint 인식 오류 등의 문제가 존재
- Pose 정보를 GCN/Transformer 등 temporal/spatial model과 결합할 발전 가능성을 제시

우리 프로젝트에서는 이 자료를 다음 관점에서 참고했다.

- object detector 기반 fallen/normal이 구현은 단순할 수 있음
- 하지만 자세와 시간 변화 정보를 직접 다루려면 Pose 기반 방식이 더 확장성이 큼
- 단순 rule-only pose가 아니라 temporal model을 붙이는 방향이 필요

---

## 4.3 AI Hub 데이터셋 71641

**데이터셋**

> 낙상사고 위험동작 영상-센서 쌍 데이터

AI Hub dataset key:

```text
71641
```

다운로드 구조 확인 당시:

```text
Training
 ├─ 원천데이터
 │   ├─ TS.z01 100 GB
 │   ├─ TS.z02 100 GB
 │   ├─ TS.z03 100 GB
 │   ├─ TS.z04 100 GB
 │   └─ TS.zip 36 GB
 └─ 라벨링데이터
     └─ TL.zip 126 MB

Validation
 ├─ 원천데이터
 │   └─ VS.zip 55 GB
 └─ 라벨링데이터
     └─ VL.zip 16 MB
```

### 확인한 데이터 특성

전체 자료 기준:

- 영상 약 **22,672개**
- **8개 카메라 방향**
- 약 10초 영상
- 4K 계열 원본
- 약 60 FPS
- 영상 + 센서 쌍 구조
- 낙상/비낙상 시나리오
- 낙상 방향:
  - 전면낙상
  - 후면낙상
  - 측면낙상
  - 비낙상

Validation 실제 추출 결과:

```text
videos = 2,272
physical scenarios = 284
views per scenario = 8
2,272 = 284 × 8
actors = 24
```

Validation scenario class:

```text
전면낙상 97
후면낙상 72
비낙상   71
측면낙상 44
합계    284
```

파일명 예:

```text
00001_H_A_SY_C1
00001_H_A_SY_C2
...
00001_H_A_SY_C8
```

동일 base scenario의 `C1~C8`은 동일 물리 사건을 서로 다른 카메라에서 본 것이다.

**따라서 C1~C8을 train/test로 찢으면 데이터 누수가 발생한다.**

### 중요한 라벨 해석

Video JSON에는 대략 다음 정보가 있다.

```text
metadata
scene_info
actor_info
fall_start_frame
fall_end_frame
scene_path
```

중요:

> AI Hub의 “동영상 keypoint”라는 표현은 **COCO 신체 관절 keypoint가 아니라 낙상 이벤트의 temporal start/end point**를 의미한다.

즉 실제 17개 인체 관절 좌표가 제공되는 것이 아니다.

그래서 우리는 MP4에 **YOLO11n-Pose를 직접 실행하여 skeleton cache를 생성**했다.

공식 가이드의 reference pipeline에서도 영상에서 pose/body keypoint를 별도로 추출하여 classifier 입력으로 만드는 흐름이 포함되어 있다.

---

# 5. AI Hub Validation 원본 준비 과정

Validation 원천 ZIP을 외장 SSD에서 재구성/검증했다.

원본 영상 특성 샘플:

```text
codec        H.264
resolution   3840 × 2160
fps          60000/1001 ≈ 59.94 FPS
frames       약 600
duration     약 10.01 sec
```

Validation MP4:

```text
2,272 files
약 26.69 GB extracted
```

외장 디스크 raw 위치:

```text
/Volumes/AIData/aihub71641/raw/val
```

manifest:

```text
~/Projects/home-safety-ml/data/aihub71641/manifests/val_manifest.csv
```

---

# 6. 개발 머신

현재 ML 실험은 Raspberry Pi에서 직접 학습하지 않고 **Mac에서 offline 학습/분석 후 Pi에 배포**하는 방식이다.

## 6.1 Mac

```text
Architecture : arm64
Chip         : Apple M4
Memory       : 32 GB
```

PyTorch MPS 사용 확인 완료.

## 6.2 Python environment

workspace:

```text
~/Projects/home-safety-ml
```

virtual environment:

```text
~/Projects/home-safety-ml/.venv
```

확인된 주요 환경:

```text
Python             3.11.17
torch              2.14.1
torchvision        0.29.1
ultralytics        8.4.173
opencv-python      5.0.0.93
numpy              2.4.6
pandas             3.0.6
scikit-learn       1.9.1
```

FFmpeg/ffprobe:

```text
/opt/homebrew/bin/ffprobe
```

## 6.3 저장장치

AI 데이터는 외장 SSD:

```text
/Volumes/AIData
```

파일시스템은 APFS로 사용했다.

raw validation:

```text
/Volumes/AIData/aihub71641/raw/val
```

---

# 7. 로컬 프로젝트 폴더 구조

현재 핵심 ML workspace는 다음이다.

```text
~/Projects/home-safety-ml/
│
├─ .venv/
│
├─ models/
│  └─ yolo11n-pose.pt
│
├─ scripts/
│  ├─ 03_pose_smoke.py
│  ├─ 04_pose_grid_benchmark.py
│  ├─ 05_pose_roi_benchmark.py
│  ├─ 06_pose_representative_benchmark.py
│  ├─ 07_extract_pose_cache.py
│  ├─ 08_make_actor_split.py
│  ├─ 09_build_gru_dataset.py
│  ├─ 10_train_gru.py
│  ├─ 11_event_evaluation.py
│  ├─ 12_build_gru_dataset_v2.py
│  ├─ 13_train_gru_v2.py
│  ├─ 14_compare_event_val_v1_v2.py
│  ├─ 15_train_gru_binary_alert.py
│  └─ 16_compare_event_val_corrected.py
│
├─ data/
│  ├─ aihub71641/
│  │  └─ manifests/
│  │     └─ val_manifest.csv
│  │
│  ├─ pose_smoke/
│  │  └─ ... benchmark CSV
│  │
│  ├─ pose_cache/
│  │  └─ val_yolo11n_pose_960_10fps/
│  │     └─ <scenario_id>/
│  │        └─ <scene_id>.npz
│  │
│  ├─ splits/
│  │  ├─ actor_split.csv
│  │  └─ actor_assignments.csv
│  │
│  └─ gru_dataset/
│     ├─ v1_actor_disjoint_20f/
│     │  ├─ train.npz
│     │  ├─ val.npz
│     │  ├─ test.npz
│     │  ├─ train_meta.csv.gz
│     │  ├─ val_meta.csv.gz
│     │  ├─ test_meta.csv.gz
│     │  └─ dataset_info.json
│     │
│     └─ v2_actor_disjoint_20f_dynamic/
│        ├─ train.npz
│        ├─ val.npz
│        ├─ test.npz
│        ├─ train_meta.csv.gz
│        ├─ val_meta.csv.gz
│        ├─ test_meta.csv.gz
│        └─ dataset_info.json
│
└─ runs/
   ├─ gru_v1/
   │  ├─ best.pt
   │  ├─ history.csv
   │  ├─ metrics.json
   │  ├─ test_confusion_matrix.csv
   │  └─ test_predictions.csv.gz
   │
   ├─ gru_v2/
   │  ├─ best.pt
   │  ├─ history.csv
   │  ├─ metrics.json
   │  ├─ val_confusion_matrix.csv
   │  └─ val_predictions.csv.gz
   │
   ├─ gru_binary_v2/
   │  ├─ best.pt
   │  ├─ history.csv
   │  ├─ metrics.json
   │  └─ val_predictions.csv.gz
   │
   ├─ event_compare_v1_v2_val/
   │  └─ ...
   │
   └─ event_compare_corrected/
      ├─ grid_all.csv
      └─ summary.csv
```

또한 원래 전체 시스템 Git repository clone은 별도로:

```text
~/Projects/Home-Safety-System
```

에서 사용한 이력이 있다.

GitHub:

```text
SongWooYu/Home-Safety-System
```

**주의:** ML 실험 workspace `home-safety-ml`과 실제 시스템 repository `Home-Safety-System`을 혼동하지 않는다.

---

# 8. 각 script의 역할

| Script | 역할 | 현재 상태 |
|---|---|---|
| `03_pose_smoke.py` | 초기 YOLO Pose smoke test | 완료 |
| `04_pose_grid_benchmark.py` | imgsz/conf 조합 비교 | 완료 |
| `05_pose_roi_benchmark.py` | bbox 기반 static ROI 실험 | 완료, 운영방식으로는 미채택 |
| `06_pose_representative_benchmark.py` | 40 scenario × 8 camera 대표 benchmark | 완료 |
| `07_extract_pose_cache.py` | Validation 2,272개 전체 10FPS pose cache | 완료 |
| `08_make_actor_split.py` | actor-disjoint split | 완료 |
| `09_build_gru_dataset.py` | v1 76-feature 20-frame dataset | 완료 |
| `10_train_gru.py` | GRU v1 학습 | 완료 |
| `11_event_evaluation.py` | 최초 event evaluator | **구형 / 최종 수치에 사용하지 말 것** |
| `12_build_gru_dataset_v2.py` | 125-feature dynamic dataset | 완료 |
| `13_train_gru_v2.py` | GRU v2 학습 | 완료 |
| `14_compare_event_val_v1_v2.py` | v1/v2 event 비교 | **evaluator overlap 처리 불완전 → 16으로 대체** |
| `15_train_gru_binary_alert.py` | binary Normal vs Alert GRU | 완료 |
| `16_compare_event_val_corrected.py` | corrected interval-overlap event evaluation | **현재 기준 evaluator** |

새 채팅에서는 **11/14 결과보다 16의 결과를 우선**한다.

---

# 9. Pose detector 선정 과정

Pose 모델:

```text
Ultralytics YOLO11n-Pose
models/yolo11n-pose.pt
```

Pose 모델 자체를 AI Hub로 다시 학습시키지는 않았다.

**pretrained pose model을 그대로 사용하고 temporal classifier만 학습**하는 전략이다.

---

## 9.1 첫 smoke test

초기 full-frame:

```text
imgsz=320
conf=0.25
```

에서는 8개 카메라 방향에 따라 사람 검출이 크게 흔들렸다.

전체 detection은 약 31.6% 수준으로 너무 낮았다.

즉:

```text
4K frame
→ 320 resize
```

에서 사람이 작아지거나 자세가 누운 상태가 되면 pose detection 품질이 크게 저하된 것으로 판단했다.

---

## 9.2 Grid benchmark

한 scenario의 C1~C8에 대해 5 FPS sampling으로 비교.

대표 결과:

```text
imgsz=320 conf=0.10
detection ≈ 0.5975

imgsz=640 conf=0.10
detection ≈ 0.765

imgsz=960 conf=0.10
detection ≈ 0.965
fall detection ≈ 0.950
mean inference ≈ 12.8 ms (Mac M4 MPS)
```

그래서 offline extraction 후보는:

```text
imgsz = 960
conf = 0.10
```

이 되었다.

---

## 9.3 ROI 320 실험

AI Hub image bbox를 이용하여 사람 주변 static ROI를 만든 뒤:

```text
ROI → YOLO Pose 320
```

을 시험했다.

`conf=0.10`에서 detection 약 90.75%까지 개선되었다.

하지만 이 ROI는 해당 영상의 여러 시점 bbox를 합친 **사후적 union ROI**라 실제 실시간 시스템에서 미리 알 수 없는 영역이다.

따라서:

- 진단용 upper-bound 실험으로는 유용
- 실제 deployment pipeline으로는 사용 불가

라고 판단했다.

향후 실시간에서는 static oracle ROI가 아니라:

```text
full-frame detection / previous bbox
→ tracker
→ dynamic ROI
→ pose
```

형태가 필요하다.

---

# 10. 대표 Pose benchmark

전체 추출 전에 단일 scenario에 과적합된 판단을 피하기 위해 대표 subset을 만들었다.

구성:

```text
40 physical scenarios
× 8 cameras
= 320 videos
```

선정:

```text
전면낙상 10 scenarios
후면낙상 10
측면낙상 10
비낙상   10
```

그리고 **24 actors 전체가 포함되도록 구성**했다.

조건:

```text
YOLO11n-Pose
imgsz=960
conf=0.10
5 FPS benchmark
```

대표 결과:

```text
overall detection       ≈ 98.94%
fall-period detection   ≈ 99.08%
visible keypoint ratio  ≈ 88.76%
pose coverage           ≈ 87.82%
M4 mean inference       ≈ 12.96 ms
```

이 결과를 근거로 Validation 전체 pose cache를 생성했다.

---

# 11. Validation 전체 Pose Cache

스크립트:

```text
scripts/07_extract_pose_cache.py
```

조건:

```text
YOLO11n-Pose
imgsz        = 960
conf         = 0.10
sampling     = 10 FPS
device       = Apple MPS
```

처리:

```text
2,272 / 2,272 videos
failed = 0
valid cache = 2,272
elapsed = 76.5 min
```

전체 평균:

```text
mean person detection   = 0.992675 ≈ 99.27%
mean keypoint visibility= 0.879664 ≈ 87.97%
mean pose coverage      = 0.873341 ≈ 87.33%
mean inference          = 12.15 ms/sample
```

cache 위치:

```text
data/pose_cache/val_yolo11n_pose_960_10fps/
```

NPZ에는 대략 다음 데이터를 저장했다.

```text
scene_id
scenario_id
actor_id
fall_class
camera
is_fall

source_width
source_height
source_fps
source_frame_count

sample_step
target_sample_fps
actual_sample_fps

imgsz
detector_conf

fall_start_frame
fall_end_frame

frame_ids
timestamps

keypoints_xy
keypoints_conf

boxes_xyxy
box_conf

valid
phase
candidate_count
```

### phase 정의

```text
0 = non-fall clip
1 = pre-fall
2 = falling
3 = post-fall
```

이 phase는 AI Hub `fall_start_frame / fall_end_frame`을 기반으로 만든 **training/evaluation metadata**이며, 실제 운영 시 입력 feature로 직접 제공하는 것은 아니다.

---

# 12. Split 전략

가장 중요한 원칙:

```text
영상 랜덤 split 금지
```

이유:

- 같은 actor가 train/test에 동시에 들어갈 수 있음
- 동일 physical event의 C1~C8이 train/test에 섞일 수 있음
- 그렇게 되면 performance가 과대평가됨

따라서:

```text
actor-disjoint
+
scenario-group-preserving
```

split을 사용했다.

24 actors:

```text
A B C D E F G H I J K L M N O P Q R S T U V X Y
```

최종 split:

### Train

```text
17 actors
A C E F H I J K M N O P Q T U V Y

199 scenarios
1,592 videos
70.1%
```

### Validation

```text
3 actors
B G X

45 scenarios
360 videos
15.8%
```

### Internal Test

```text
4 actors
D L R S

40 scenarios
320 videos
14.1%
```

클래스 분포:

```text
TRAIN
비낙상     50
전면낙상   69
측면낙상   29
후면낙상   51

VAL
비낙상     11
전면낙상   15
측면낙상    8
후면낙상   11

TEST
비낙상     10
전면낙상   13
측면낙상    7
후면낙상   10
```

Actor leakage:

```text
NONE
```

Scenario leakage:

```text
NONE
```

---

# 13. 매우 중요한 평가 데이터 주의사항

현재 사용한 2,272개는 **AI Hub 공식 Validation set**이다.

우리는 이를:

```text
internal train
internal val
internal test
```

로 다시 나누어 모델 개발에 사용했다.

따라서 현재 숫자는:

> **AI Hub Validation을 기반으로 한 개발용 actor-disjoint 실험 결과**

라고 표현해야 한다.

다음 표현은 부적절하다.

```text
"AI Hub official validation에서 최종 독립 평가한 결과"
```

또한 v1에서 internal test를 이미 평가했고, 그 결과를 확인한 뒤 v2와 binary 모델을 설계했다.

따라서 현재 내부 `test` 역시 연구 방법론상 더 이상 완전히 untouched가 아니다.

### 향후 정식 평가 구조 권장

```text
AI Hub Training
  ↓
train / internal validation
  ↓
model development + threshold tuning

AI Hub official Validation
  ↓
FINAL evaluation only
```

이 구조를 만들기 전까지 현재 성능은 **prototype/development 성능**으로 기록한다.

---

# 14. GRU Dataset v1

스크립트:

```text
09_build_gru_dataset.py
```

sequence:

```text
20 frames
10 FPS
≈ 2 sec
stride = 1
```

feature:

```text
76 dimensions/frame
```

구성:

### Pose feature

```text
17 joints ×
(
  bbox-relative x,
  bbox-relative y,
  confidence,
  valid mask
)

17 × 4 = 68
```

### Global feature

```text
bbox center x
bbox center y
bbox width
bbox height
log(height / width)
bbox confidence
frame valid
visible keypoint ratio

= 8
```

총:

```text
68 + 8 = 76
```

label:

```text
phase 0/1 → Normal
phase 2   → Falling
phase 3   → Fallen
```

즉 pre-fall은 normal로 본다.

Dataset shape:

```text
Train (129000, 20, 76)
Val   (29216,  20, 76)
Test  (25928,  20, 76)
```

Train class:

```text
Normal   63,832  49.48%
Falling  12,472   9.67%
Fallen   52,696  40.85%
```

inverse-frequency class weight:

```text
normal  0.6736
falling 3.4477
fallen  0.8160
```

---

# 15. GRU v1

구조:

```text
76 features
 ↓
LayerNorm
 ↓
GRU
 hidden = 128
 layers = 2
 dropout = 0.2
 ↓
FC 64
 ↓
3 class
```

학습:

```text
AdamW
LR = 1e-3
weight_decay = 1e-4
batch = 512
early stopping
validation Macro-F1 기준 best checkpoint
```

best:

```text
epoch = 10
val Macro-F1 = 0.825109
```

v1에서 당시 internal test를 한 번 평가했다.

```text
Accuracy          0.898912
Balanced Accuracy 0.867070
Macro-F1          0.844515
```

class:

```text
Normal
precision 0.9323
recall    0.8991
F1        0.9154

Falling
precision 0.6054
recall    0.7750
F1        0.6798

Fallen
precision 0.9499
recall    0.9271
F1        0.9384
```

이 결과에서:

- normal/fallen은 잘 구분
- falling이 가장 어려움
- class weight 때문에 `falling` recall은 확보되지만 precision이 낮고 false positive가 많을 수 있음

이라는 문제를 발견했다.

---

# 16. GRU Dataset v2 — Dynamic feature 추가

v2 목적:

> Pose 좌표만 보고 GRU가 속도/기울기 변화를 스스로 배우게 하기보다, 낙상에 직접 관련된 물리적 변화를 명시적으로 제공한다.

v1 76 feature에 다음을 추가했다.

## 16.1 Joint velocity

```text
17 joints × (vx, vy)
= 34
```

모두 **causal backward difference**를 사용한다.

## 16.2 BBox dynamics

```text
bbox center vx
bbox center vy
bbox width velocity
bbox height velocity
bbox log-aspect velocity
bbox center-y acceleration

= 6
```

## 16.3 Pose geometry

```text
torso:
sin / cos / valid

shoulder axis:
sin / cos / valid

hip axis:
sin / cos / valid

= 9
```

총:

```text
76 + 34 + 6 + 9
= 125 features
```

dataset:

```text
Train (129000, 20, 125)
Val   (29216,  20, 125)
Test  (25928,  20, 125)
```

label 분포는 v1과 동일하다.

---

# 17. v2 class weight 변경

v1의 inverse-frequency:

```text
normal  0.6736
falling 3.4477
fallen  0.8160
```

은 `falling`을 너무 강하게 강조할 가능성이 있었다.

v2에서는 sqrt inverse:

```text
normal  0.8208
falling 1.8568
fallen  0.9033
```

을 사용했다.

주의:

> v1 → v2에서 feature와 class weight를 동시에 변경했다.

따라서 현재 실험만으로:

```text
"성능 개선은 dynamic feature 때문에 발생했다"
```

라고 단정하면 안 된다.

향후 ablation에서 분리해야 한다.

---

# 18. GRU v2 결과

구조 자체는 v1과 동일하게 유지했다.

```text
input = 125
hidden = 128
layers = 2
dropout = 0.2
```

best:

```text
epoch = 3
validation Macro-F1 = 0.839480
```

Validation:

```text
Accuracy          0.885439
Balanced Accuracy 0.844751
Macro-F1          0.839480
```

class:

```text
Normal
precision 0.8932
recall    0.9137
F1        0.9033

Falling
precision 0.6822
recall    0.7338
F1        0.7070

Fallen
precision 0.9304
recall    0.8868
F1        0.9081
```

v1 val Macro-F1:

```text
0.825109
```

v2:

```text
0.839480
```

즉 window-level Macro-F1은 개선됐다.

하지만 Epoch 3 이후 train F1은 계속 상승하면서 validation loss가 증가하여 **빠른 overfitting**이 확인됐다.

---

# 19. Binary Alert GRU

3-class의 목적:

```text
Normal / Falling / Fallen
```

과 실제 제품 경보 목적:

```text
Normal / Alert
```

이 다를 수 있으므로 Binary GRU도 시험했다.

target:

```text
0 normal  → 0
1 falling → 1
2 fallen  → 1
```

Train:

```text
normal = 63,832
alert  = 65,168
```

거의 50:50이므로 class weight 없음.

같은 v2 125-feature 사용.

best:

```text
epoch = 2
Val Average Precision = 0.968874
ROC-AUC = 0.965113
```

threshold 0.5:

```text
Accuracy          0.898480
Balanced Accuracy 0.898450
Precision         0.909379
Recall            0.884673
F1                0.896856
```

Binary는 score ranking 자체는 좋았지만, **corrected event-level operating point에서는 v2 3-class보다 우수한 trade-off를 만들지는 못했다.**

그래서 현재로서는 binary를 주력 모델로 채택하지 않는다.

---

# 20. Event-level 평가가 필요한 이유

window classifier accuracy만 보면 실제 시스템 성능을 알 수 없다.

실제 제품에서는 다음이 중요하다.

```text
낙상 사건을 한 번이라도 잡는가?
얼마나 빨리 잡는가?
정상생활에서 몇 번 잘못 울리는가?
중복 알림이 얼마나 생기는가?
```

그래서 다음을 평가한다.

- Event recall by fall end
- Event recall by fall end +1s
- Event recall by fall end +2s
- Median detection latency
- P95 latency
- false alarm count
- nonfall clip false alarm rate
- false alarms/hour
- pre-fall false alarm rate

---

# 21. Event state machine

기본 idea:

```text
score >= threshold
N consecutive frames
        ↓
Alarm ON
```

alarm 해제:

```text
score < threshold
release_frames consecutive
        ↓
Alarm OFF
```

향후 실제 운영에는 추가로:

```text
event hold
cooldown
duplicate suppression
track disappearance handling
```

이 필요하다.

---

# 22. Event evaluator에서 발견한 오류와 수정

초기 `11_event_evaluation.py`, `14_compare_event_val_v1_v2.py`에서는 한 문제가 있었다.

예를 들어:

```text
Alarm ───────────────
           Fall starts
```

낙상 직전에 alarm이 이미 ON인데 fall_start 뒤에 **새로운 onset이 없으면** miss로 볼 수 있었다.

실제 시스템 관점에서는 alarm이 낙상 시작 시점에도 계속 active라면 낙상을 감지한 상태이다.

그래서 `16_compare_event_val_corrected.py`에서:

```text
alarm interval
vs
event detection interval
```

의 **overlap**으로 detection을 판단하도록 수정했다.

따라서 event 성능은 **script 16 결과를 현재 기준으로 사용**한다.

11/14 결과는 개발 과정 기록용일 뿐 최종 비교값으로 쓰지 않는다.

---

# 23. Strict vs Early-tolerant 평가

## Strict

```text
fall_start 이전 = 정상
```

낙상 전 경보는 false alarm이다.

가장 보수적인 공식 지표로 사용한다.

## Early -0.5 sec

```text
fall_start - 0.5 sec
```

부터 alert를 조기검출로 허용한다.

이것은 AI Hub temporal annotation이 신체 접촉 중심으로 정의되어 있고 실제 동작의 균형 상실이 먼저 발생할 수 있다는 점을 고려한 **engineering auxiliary metric**이다.

주의:

> `early_0p5s` 결과를 ground-truth 공식 낙상 recall처럼 표현하지 않는다.

논문/보고서의 주 결과는 strict를 우선한다.

---

# 24. Corrected Validation Event 결과

현재 최신 결과는:

```text
runs/event_compare_corrected
```

에 저장되어 있다.

## 24.1 TARGET95 — Strict

목표:

```text
event recall @ fall_end+1s >= 95%
```

### v1

```text
threshold      0.900
consecutive    4

recall end     90.07%
recall +1s     95.22%
recall +2s     97.43%

median latency 0.6006 s
p95 latency    1.0001 s

FA/hour        130.24
nonfall FA     17.05%
prefall FA     11.76%
```

### v2

```text
threshold      0.550
consecutive    9

recall end     51.47%
recall +1s     95.22%
recall +2s     97.43%

median latency 1.0000 s
p95 latency    1.3000 s

FA/hour        103.21
nonfall FA     13.64%
prefall FA      9.93%
```

### Binary

```text
threshold      0.300
consecutive    10

recall end     36.40%
recall +1s     95.22%
recall +2s     97.79%

median latency 1.1000 s
p95 latency    1.4000 s

FA/hour        167.10
nonfall FA     21.59%
prefall FA     16.18%
```

### 해석

동일한 `+1s recall ≈ 95.22%`에서:

```text
v2 FA/hour < v1 FA/hour < binary FA/hour
v2 nonfall clip FA < v1 < binary
```

즉 **v2가 현재 세 모델 중 가장 나은 TARGET95 trade-off**이다.

다만 v2가 `consecutive=9`이기 때문에 fall end 시점 recall은 낮고 detection delay가 늘어난다.

따라서 이 operating point를 바로 제품값으로 고정하지 말고 Pareto trade-off를 더 봐야 한다.

---

## 24.2 LOW_FA — Strict

조건:

```text
nonfall clip false-alarm rate <= 10%
```

### v1

```text
threshold   0.970
consecutive 9

recall +1s  87.13%
recall +2s  91.18%

median      1.2000 s
nonfall FA   9.09%
FA/hour     51.61
```

### v2

```text
threshold   0.950
consecutive 4

recall +1s  91.54%
recall +2s  93.38%

median      0.6006 s
nonfall FA   9.09%
FA/hour     76.18
```

### Binary

```text
threshold   0.995
consecutive 1

recall +1s  85.66%
recall +2s  90.81%

median      0.6006 s
nonfall FA   7.95%
FA/hour     56.52
```

### 현재 판단

동일한 약 10% 이하 nonfall clip FA constraint에서 **v2가 가장 높은 recall**을 보인다.

따라서 현 단계 대표 후보:

```text
GRU v2
```

이다.

---

# 25. 왜 FA/hour를 아직 제품 성능으로 쓰면 안 되는가

AI Hub 영상은 대부분 약 10초짜리 staged clip이다.

예를 들어 비낙상 영상 10초 중 한 번만 잘못 울려도, 이를 단순히 시간당으로 환산하면:

```text
1 alarm / 10 sec
→ 360 alarms/hour
```

가 된다.

즉 현재:

```text
50 FA/hour
100 FA/hour
```

같은 숫자는 상대적 모델 비교에는 쓸 수 있지만:

> “우리 시스템은 실제 집에서 시간당 100번 오경보가 난다”

는 뜻은 아니다.

실제 제품 평가에는 다음과 같은 **연속 ADL negative 영상**이 필요하다.

- 걷기
- 천천히 앉기
- 빠르게 소파에 앉기
- 침대에 눕기
- 소파에 눕기
- 바닥 물건 줍기
- 허리 숙이기
- 쪼그려 앉기
- 신발 신기
- 스트레칭
- 바닥 청소
- 무릎 꿇기
- 카메라 밖으로 이동
- 부분 가림
- 다른 사람이 지나감
- 여러 사람
- 조명 ON/OFF
- 야간/역광

최소 수십 분, 가능하면 **몇 시간 규모**의 continuous negative evaluation이 필요하다.

---

# 26. Camera/view 문제

Pose benchmark와 event 결과에서 카메라 방향에 따른 차이가 있었다.

특히 과거 representative benchmark에서 C2가 keypoint quality가 상대적으로 낮았고, 초기 event test에서도 Camera 2가 약한 사례가 있었다.

향후 확인:

1. C2가 어느 높이/각도인지
2. 사람이 frame에서 얼마나 작은지
3. 누운 자세에서 관절 중첩이 심한지
4. 역광/occlusion 여부
5. bbox largest-person selection 실패 여부
6. camera-specific feature distribution

특정 view에만 성능이 나쁘다면 모델 자체 문제와 pose detector 문제를 분리해야 한다.

---

# 27. 현재 largest-person 선택의 의미

AI Hub offline extraction에서는 각 frame에서 여러 pose 후보가 있으면 **가장 큰 bbox 사람**을 대표 actor로 선택했다.

AI Hub 촬영 데이터는 주 피험자를 중심으로 구성되어 있으므로 offline cache에서는 합리적인 단순화였다.

하지만 실제 스마트홈에서는 여러 사람이 있을 수 있다.

실제 deployment에서는:

```text
YOLO Pose detections
 ↓
tracker
 ↓
track_id
 ↓
track별 20-frame skeleton buffer
 ↓
GRU
```

가 필요하다.

즉 **largest person 로직을 실제 운영 코드에 그대로 사용하면 안 된다.**

---

# 28. 얼굴 인식과 낙상 track은 별개 문제

개인 식별을 넣는 경우 권장 구조:

```text
person tracker
  ↓
track_id

face detector / embedding
  ↓
identity
  ↓
identity를 track_id에 bind
```

얼굴 인식은 매 frame 할 필요가 없다.

새 track 발생 시 burst로 몇 frame 수행하고 identity를 cache할 수 있다.

과거 검토:

```text
YuNet face detector
SFace embedding
front / left / right
등록 5장 중 >=3 valid 평균
threshold 약 0.45
```

다만 최종 프로젝트 범위에서 얼굴 식별을 반드시 포함할 필요는 없다. 개인정보 설계상 별도 기능으로 관리하는 편이 좋다.

---

# 29. Raspberry Pi 5 쪽 현재 맥락

프로젝트 Vision Node는 Raspberry Pi 5이다.

확인된 카메라 관련 자료:

```text
RPi Camera Module 3
ABKO APC720 USB webcam
```

Camera Module 3:

```text
1280×720 30fps H.264 recording 정상 확인
```

ABKO APC720:

```text
1280×720 30fps MJPEG input 가능
```

USB 카메라는 `/dev/videoN` 번호가 재부팅 때 바뀔 수 있으므로 운영 시:

```text
/dev/v4l/by-id/...
```

형태 사용이 권장된다.

---

# 30. 현재 deployment와 offline 연구 사이의 중요한 차이

현재 offline dataset extraction:

```text
YOLO11n-Pose
imgsz = 960
Mac M4 MPS
```

현재/기존 Pi deployment 쪽 코드는 과거 기준:

```text
NcnnPoseEstimator
imgsz ≈ 320
```

중심으로 구성된 이력이 있다.

즉 **domain gap**이 존재한다.

```text
training/evaluation skeleton:
960 full-frame pose

deployment skeleton:
320 NCNN pose
```

이 둘의 keypoint noise/missing ratio가 다르면 GRU 성능이 크게 변할 수 있다.

따라서 반드시 실제 Pi에서:

```text
320
640
960
```

또는 dynamic ROI 방식으로 pose quality/FPS를 다시 측정해야 한다.

**Mac M4의 12ms 추론을 Pi의 12ms로 간주하면 안 된다.**

---

# 31. Pi 배포에서 유력한 구조

두 후보가 있다.

## A. Full-frame 고해상도 pose

```text
Camera
 ↓
YOLO11n-Pose 640/960
 ↓
tracker
 ↓
GRU
```

장점:

- 단순
- offline 학습조건과 가까움

단점:

- Pi에서 FPS 확보 여부 미확인

## B. Full-frame detection + tracked ROI pose

```text
periodic full-frame person detection
 ↓
tracker / bbox
 ↓
dynamic ROI crop
 ↓
YOLO Pose 320 or 640
 ↓
GRU
```

장점:

- pose 입력에서 사람이 크게 보임
- 계산량 절감 가능

단점:

- tracker failure
- ROI drift
- detection/pose 두 단계
- pipeline 복잡도 증가

현재 static union ROI benchmark는 이 방향의 가능성을 보여준 진단 실험이지 실제 구현은 아니다.

---

# 32. 전체 스마트홈 통합 구조

기존 최종보고서 설계 맥락은 다음과 같다.

```text
ESP32 Sensor / IoT Node
  ├─ temperature
  ├─ light
  ├─ occupancy / PIR
  ├─ gas/smoke
  ├─ flame
  └─ actuator control
        ↓ MQTT

Server Node
  ├─ MQTT Broker
  ├─ Logic / AI Pattern
  ├─ Database
  └─ Web Dashboard

Vision Node - Raspberry Pi 5
  ├─ Camera capture
  ├─ Person/Pose
  ├─ Temporal classifier
  ├─ Risk engine
  └─ MQTT publish
```

위험 이벤트 메시지 예시 개념:

```text
risk/event

device_id
camera_id
timestamp
event_type
risk_level
state_before
state_after
duration_sec
snapshot_path
```

현재 낙상 ML 결과는 최종적으로 이 Vision Node/Risk Engine에 연결되어야 한다.

---

# 33. 당장 다음에 해야 할 일 — 우선순위

## P0. 현재 결과와 파일을 보존

다음은 삭제/덮어쓰기 금지.

```text
runs/gru_v1
runs/gru_v2
runs/gru_binary_v2
runs/event_compare_corrected

data/gru_dataset/v1_actor_disjoint_20f
data/gru_dataset/v2_actor_disjoint_20f_dynamic

data/pose_cache/val_yolo11n_pose_960_10fps
data/splits
```

가능하면 Git에는 script/config만 commit하고, 큰 NPZ/pose cache는 `.gitignore`로 제외한다.

---

## P1. Experiment manifest 작성

앞으로 실험이 늘어나면 어떤 모델이 어떤 feature/weight/split으로 만들어졌는지 헷갈리기 쉽다.

각 run에 최소:

```text
dataset version
split hash
feature version
sequence length
FPS
pose model
pose imgsz/conf
class weights
GRU architecture
random seed
best epoch
validation metric
event operating point
Git commit
```

을 JSON/YAML로 기록하는 것을 권장한다.

---

## P2. 현재 v2의 Pareto operating point 분석

script 16의 전체:

```text
runs/event_compare_corrected/grid_all.csv
```

에서 단순 TARGET95/LOW_FA 두 점만 보는 것이 아니라:

```text
recall +1s
vs
nonfall clip false alarm
vs
latency
```

Pareto curve를 그려야 한다.

목적:

- safety 우선 설정
- balanced 설정
- low false-alarm 설정

3개의 후보 operating point를 정한다.

예:

```text
Safety:
Recall +1s >= 95%

Balanced:
Recall +1s >= 93%
nonfall FA minimum

Quiet:
nonfall clip FA <= 5~10%
```

---

## P3. v1/v2 ablation

현재 v1과 v2는 feature와 class weighting이 동시에 달라졌다.

정확한 연구 결론을 위해 최소 다음 실험이 필요하다.

```text
A = 76 feature + inverse weight     [현재 v1]
B = 76 feature + sqrt weight
C = 125 feature + inverse weight
D = 125 feature + sqrt weight       [현재 v2]
```

이렇게 해야:

- dynamic feature 효과
- class weighting 효과

를 분리할 수 있다.

가능하면 같은 seed뿐 아니라 3개 정도 seed 평균도 기록한다.

---

## P4. Sequence length / FPS 실험

현재 고정:

```text
10 FPS
2 sec
20 frames
```

향후 비교:

```text
FPS:     5 / 10 / 15
Window:  1 / 2 / 3 sec
```

그러나 전 조합을 무작정 돌리기보다 먼저:

```text
5fps × 2sec
10fps × 2sec
10fps × 3sec
```

정도를 우선 비교하는 것이 효율적이다.

평가:

```text
event recall
latency
false alarm
compute cost
```

---

## P5. AI Hub Training 원천데이터 확보

정식 논문/최종평가를 위해 가장 중요하다.

압축 원천만 약:

```text
100GB × 4 + 36GB
≈ 436GB
```

이다.

전체 압축 해제/작업공간까지 생각하면 AI Hub 안내와 실제 4K 영상 규모상 **2TB급 여유 공간을 권장**한다.

목표 구조:

```text
AI Hub Training
 → pose extraction
 → training / internal validation

AI Hub official Validation
 → untouched final evaluation
```

현재 Validation pose cache는 pipeline 검증 및 prototype 연구에는 계속 유용하다.

---

## P6. Hard negative / continuous ADL 데이터 확보

현재 가장 부족한 데이터이다.

실제 집에서 별도 촬영 권장:

```text
30 min ~ 수 시간
```

가능하면 여러 사람/시간대/카메라각도.

시나리오:

- 정상 보행
- 의자 앉기/일어나기
- 침대 눕기/일어나기
- 소파 빠르게 눕기
- 바닥 물건 줍기
- 웅크리기
- 스트레칭
- 청소
- 신발 신기
- 카메라 가림
- 조명 변화
- 부분 frame out
- 2명 이상 등장

이 데이터로 실제:

```text
false alarms / hour
mean time between false alarms
```

를 산출한다.

---

## P7. Camera 2 / hard case 분석

필요 작업:

```text
false positive top N
false negative top N
C2 missed falls
```

를 실제 프레임/pose overlay 영상으로 확인한다.

원인을:

```text
pose failure
wrong person selection
occlusion
viewpoint
temporal classifier
label boundary
```

로 분류해야 한다.

---

## P8. 실제 Pi5 Pose benchmark

Mac 결과를 기준으로 모델을 확정하면 안 된다.

Pi에서 최소:

```text
YOLO11n-Pose NCNN
320
640
960
```

테스트:

```text
FPS
latency mean/p95
CPU
memory
temperature
keypoint coverage
fall segment detection
```

를 측정한다.

960이 10FPS 불가능하면:

```text
dynamic ROI
tracking
640
```

등을 시험한다.

---

## P9. GRU export

GRU는 pose detector에 비해 매우 작으므로 Pi 부담은 낮을 것으로 예상된다.

후보:

```text
PyTorch CPU
ONNX Runtime
TFLite (변환 가능성 검토)
```

우선 ONNX export 후:

```text
20 × 125 float input
→ 3 logits
```

로 단순화할 수 있다.

실제 pipeline에서는 normalization/feature generator까지 동일해야 한다.

---

## P10. Multi-person tracking

실제 시스템 필수.

필요 상태:

```text
track_id
bbox history
20-frame feature buffer
last_seen
identity(optional)
alarm state
cooldown state
```

한 사람의 pose가 다른 사람 sequence와 섞이지 않도록 해야 한다.

---

## P11. Event state machine 제품화

최종 event logic 예시:

```text
NORMAL
  ↓ score threshold + consecutive
SUSPECTED
  ↓ persistence / falling-fallen evidence
ALERT
  ↓ MQTT + snapshot
COOLDOWN
  ↓ release condition
NORMAL
```

추가 파라미터:

```text
alert threshold
consecutive frames
release threshold
release frames
minimum hold time
cooldown sec
track-lost grace period
```

Validation에서 정하고 final test에서 변경하지 않는다.

---

## P12. MQTT / DB / Dashboard 연결

모델이 실시간으로 내야 할 최소 payload:

```json
{
  "device_id": "...",
  "camera_id": "...",
  "track_id": 1,
  "timestamp": "...",
  "event_type": "fall_suspected",
  "risk_level": "warning",
  "alert_score": 0.97,
  "state": "falling",
  "duration_sec": 0.8
}
```

서버:

```text
MQTT subscribe
→ event DB
→ dashboard
→ notification
```

중복 알림 방지를 위해 `event_id` 또는 track 기반 event lifecycle이 필요하다.

---

# 34. 연구 결과를 보고서/졸업작품에 정리할 때 추천하는 실험 구조

최종 보고서에서는 단순히 “정확도 90%” 식으로 끝내지 않는다.

## Experiment 1 — Pose input condition

```text
320 vs 640 vs 960
conf 0.1 / 0.25
```

목적:

> 4K wide view에서 small-person pose detection에 input resolution이 미치는 영향

---

## Experiment 2 — Static ROI diagnostic

```text
full frame 320
vs
ROI 320
```

목적:

> 사람이 입력에서 크게 보이면 저해상도 pose inference도 개선됨을 확인

단, oracle ROI임을 명시.

---

## Experiment 3 — Temporal model

```text
v1: static pose feature
v2: pose + dynamics
```

평가:

```text
window Macro-F1
falling F1
event recall
latency
false alarm
```

---

## Experiment 4 — Objective

```text
3-class
vs
binary alert
```

현재 결과에서는 Binary가 최종 우위를 보이지 않았다는 점도 의미 있는 연구 결과이다.

---

## Experiment 5 — Operating point

```text
threshold
consecutive
release
```

을 바꾸며:

```text
Recall vs False Alarm vs Latency
```

trade-off를 제시한다.

---

## Experiment 6 — Real device

```text
Mac offline
vs
Raspberry Pi 5
```

여기서는 정확도뿐 아니라:

```text
FPS
CPU
memory
temperature
end-to-end latency
```

가 필요하다.

---

# 35. 최종 성능지표 권장

보고할 지표를 세 층으로 나눈다.

## Pose layer

```text
person detection rate
visible keypoint ratio
pose coverage
inference latency
```

## Window classifier

```text
precision
recall
F1
macro-F1
confusion matrix
PR-AUC
```

## Event/system layer — 가장 중요

```text
event recall
detection latency median / p95
false alarm per hour
nonfall clip false alarm rate
duplicate alerts/event
end-to-end alert latency
```

제품 목적에서는 **event layer가 최종 지표**다.

---

# 36. 현재 과학적/방법론적 제한

반드시 기억할 것.

### 1. 공식 Validation을 개발에 사용함

최종 unbiased performance로 주장 금지.

### 2. internal Test도 v1에서 열어봄

그 결과를 보고 v2를 만들었으므로 최종 독립 Test가 아님.

### 3. AI Hub staged data

실제 가정의 긴 ADL distribution과 다를 수 있음.

### 4. 8 cameras는 같은 event의 서로 다른 view

독립 sample 2,272개라고 생각하면 안 된다.

실제 independent physical event는 Validation에서 284개.

### 5. overlapping windows

129,000개의 train window가 129,000개의 독립 사건이라는 뜻이 아니다.

인접 window는 거의 같은 frame을 공유한다.

### 6. Pose source domain

offline pose 960과 실제 Pi pose resolution/backend가 다르면 temporal model 성능이 달라질 수 있다.

### 7. largest person

AI Hub에는 편리하지만 실제 multi-person 환경에는 사용할 수 없다.

### 8. early -0.5s metric

engineering auxiliary metric이다. strict와 분리해 보고한다.

---

# 37. 지금 절대 다시 결정하지 않아도 되는 것

현재까지 충분히 검증했으므로 새 채팅에서 이유 없이 되돌리지 않는다.

- Temporal model을 쓰는 방향
- Pose 기반 skeleton sequence를 주 입력으로 쓰는 방향
- C1~C8을 같은 split에 유지
- actor-disjoint split 필요성
- missing keypoint confidence/mask 유지
- causal window 사용
- event-level 평가 필요성
- Mac M4를 offline extraction/training용으로 사용
- Pi는 deployment benchmark 별도 수행
- static union ROI는 실제 배포 방식이 아님
- script 16이 현재 event evaluator 기준
- v2가 현재 validation trade-off 리딩 모델

새로운 실험 결과가 있을 때만 이 판단을 갱신한다.

---

# 38. 현재 추천 의사결정

현 시점:

```text
Temporal classifier:
GRU v2 유지

Input:
20 × 125

Pose cache research condition:
YOLO11n-Pose
960
conf 0.10
10 FPS

Event evaluation:
strict를 공식 기준
early_0p5s는 보조 지표

Current operating-point 후보:
1) safety-oriented TARGET95
2) low-FA-oriented v2 threshold 0.95 / consecutive 4
```

아직 production threshold를 최종 확정하지 않는다.

이유:

- 긴 negative 영상 없음
- 실제 Pi pose domain 미검증
- 공식 final test 없음

---

# 39. 향후 실행 순서 추천

다음 채팅에서 진행할 순서는 아래가 가장 합리적이다.

```text
1. script16 grid_all.csv 분석 / Pareto plot
2. v1/v2 ablation 실험
3. AI Hub Training raw 확보 계획 결정
4. continuous ADL negative 데이터 계획
5. Pi5 pose 320/640/960 benchmark
6. deployment input 조건 확정
7. train dataset 기반 temporal model 재학습
8. official validation final evaluation
9. GRU export
10. tracker + per-track buffer 구현
11. state machine / cooldown
12. MQTT risk/event 연동
13. dashboard / DB
14. 실제 집 연속 운전 테스트
15. 최종 논문/보고서 성능표 작성
```

시간이 부족하면 최소:

```text
Pareto 확인
→ Pi benchmark
→ tracker + GRU integration
→ 실제 nonfall/fall 소규모 연속 실험
→ MQTT integration
```

순으로 진행한다.

---

# 40. 새 채팅 시작용 프롬프트

새 채팅에서 이 MD를 업로드한 뒤 다음처럼 시작하면 된다.

```text
첨부한 MD는 지금까지 진행한
'AI 기반 스마트홈 및 Raspberry Pi 5 카메라 낙상감지'
연구·개발 인수인계 문서다.

이 문서의 경로, 실험 결과, 데이터 누수 방지 원칙,
현재 리딩 모델(GRU v2), evaluator 수정 이력,
향후 작업 순서를 프로젝트의 현재 상태로 간주해라.

이미 끝난 실험을 이유 없이 처음부터 다시 제안하지 말고,
문서의 '현재 추천 의사결정'과 '향후 실행 순서'를 기준으로
다음 작업을 이어가자.

특히:
- script 16 corrected event evaluator를 기준으로 할 것
- 공식 AI Hub Validation을 현재 개발에 사용했다는 limitation을 기억할 것
- Pi deployment domain과 Mac offline domain을 구분할 것
- C1~C8 / actor leakage를 절대 만들지 말 것
- window accuracy보다 event recall / false alarm / latency를 우선할 것

먼저 이 문서를 읽고
1) 현재 상태,
2) 확정된 사항,
3) 미확정 사항,
4) 바로 다음 3개 작업
만 요약해서 확인해줘.
```

---

# 41. 참고 파일 / 자료 목록

프로젝트에 존재하거나 대화에서 사용한 핵심 자료:

```text
AI기반_스마트홈_최종보고서 (2).pdf
AI기반_스마트홈_최종보고서 (2).docx
AI기반_스마트홈_발표PPT (1) (1).pptx
raspberry_pi5_dual_camera_spec.md
```

연구 자료:

```text
강윤규, 2021,
사람자세 추정을 이용한 딥러닝기반 낙상 탐지시스템,
숭실대학교 박사학위논문

김주연 · 최대수, 2025,
융합보안 관점에서의 YOLOv8 객체 탐지와
Pose Estimation 기반 낙상 감지 성능 연구,
융합보안논문지 25(3), 147-152
DOI 10.33778/kcsa.2025.25.3.147

AI Hub Dataset 71641
낙상사고 위험동작 영상-센서 쌍 데이터
```

---

# 42. 한 줄 결론

현재 연구는 단순 YOLO 낙상 객체검출에서 출발하여, **고해상도 pretrained pose extraction → actor-disjoint skeleton sequence → dynamic feature GRU → corrected event-level state-machine 평가**까지 진행되었고, 현 시점에서는 **GRU v2(125-feature)가 가장 유력한 temporal model**이다.

다음 핵심은 **더 복잡한 모델을 만드는 것보다, proper training/final validation 분리, 실제 Raspberry Pi pose domain 검증, 긴 non-fall 연속영상에서 false-alarm 검증, tracker/MQTT 통합**이다.
