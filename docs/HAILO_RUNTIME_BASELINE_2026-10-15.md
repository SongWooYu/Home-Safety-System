# Hailo-8 런타임 기준선과 전환 계획

> **역사 문서:** 이 계획의 Shadow 검증은 완료됐고 2026-10-19 운영 경로로
> 승격됐다. 현재 기준은
> [Hailo YOLOv8 + EdgeFall 운영 전환 보고서](HAILO_EDGEFALL_PRODUCTION_2026-10-19.md)다.

기준일: 2026-10-15

## 결론

AI HAT+의 Hailo-8은 정상 인식되고 pose HEF도 하드웨어에서 약 31 FPS로 실행된다.
Hailo callback에서 사람 bbox와 17개 keypoint를 꺼내 기존 estimator 계약으로
변환하는 어댑터와 설정 backend 선택 지점까지 구현했다. 현재 운영 설정은 출력
domain 검증을 위해 계속 `backend: ncnn`이다. 대신 Pi5 `:8080`을 보고 있을 때만
같은 Dahua 프레임을 Hailo에도 넣는 Shadow 비교를 실행하며, Hailo 결과는 MQTT
경보와 Rule/GRU 입력에 사용하지 않는다.

영상 전달과 AI는 분리한다. Pi4 통합 관제 화면에는 clean WebRTC를 보내고, Pi5 개발
화면을 실제로 열었을 때만 bbox·관절·진단 오버레이를 만든다. Hailo는 pose 추론을
가속하지만 RTSP 디코딩, JPEG/H.264 인코딩, 브라우저 렌더링을 가속하지 않는다.

## 장치와 모델

| 항목 | 값 |
|---|---|
| 장치 | Raspberry Pi AI HAT+ / Hailo-8 |
| 펌웨어 | 4.23.0 |
| 모델 | `/usr/local/hailo/resources/models/hailo8/yolov8m_pose.hef` |
| 크기 | 31,609,032 bytes |
| SHA-256 | `54f22e23ee5e161e3b5d8507add82035122f72fa6357b453eb8773c63c0eb4b7` |
| 출력 계약 | person bbox + 17 keypoints + confidence + track ID |

## 2026-10-15 실측

| 시험 | 결과 | 해석 |
|---|---:|---|
| `hailortcli benchmark`, batch 1, hw-only | 30.80 FPS | Hailo-8 자체 정상 |
| `hailortcli benchmark`, streaming | 30.80 FPS | HW latency 약 26.97 ms |
| 공식 pose 전체 앱, 기존 Vision 동시 실행 | 약 6.2 FPS | 화면·overlay 파이프라인 병목 |
| 공식 pose 전체 앱, Vision 중지 | 약 8.0 FPS | NCNN 경쟁만 제거해도 한계 존재 |
| display를 `fakesink`, metadata callback만 유지 | 31.75 FPS | 추론이 아니라 표시 분기가 주 병목 |

마지막 시험은 336 frame / 10.582초다. 따라서 운영 런타임에 공식 demo 화면 전체를
삽입하지 않는다. GStreamer/Hailo callback에서 metadata만 받아 기존 Python 상태
머신에 전달한다.

### Dahua 라이브 프레임 어댑터 실측

기존 GStreamer 최신 프레임 우선 RTSP source에서 나온 960×540 BGR 프레임을
`appsrc -> letterbox -> Hailo YOLOv8m Pose -> metadata callback -> fakesink`로
전달하는 프로젝트 내부 어댑터를 추가했다. 기존 NCNN 운영 서비스와 동시에 실행한
15초 결과는 다음과 같다.

| 항목 | 결과 |
|---|---:|
| 처리 프레임 | 217 |
| 실효 FPS | 14.44 FPS |
| Hailo pipeline 평균 | 37.52 ms |
| Hailo pipeline p95 | 46.21 ms |
| RTSP buffer age 평균 / p95 | 224.83 / 289.21 ms |
| 사람 검출 프레임 비율 | 98.16% |
| 평균 사람 수 | 1.07명 |
| bbox 면적 비율 평균 | 0.192 |

성능과 지연은 10 FPS 시간 계약을 만족하지만, 현재 장면에서 Hailo keypoint
confidence 평균은 0.1480, 중앙값은 0.0935였다. 기존 B76 runtime의 가시 관절
기준인 confidence 0.25를 적용하면 평균 가시 관절 비율이 0.2556에 불과했다.
같은 시점 NCNN 운영 상태의 track별 가시 관절 비율은 약 0.88이었다.

이는 단순 좌표 변환 문제가 아니라 다음 두 domain 차이를 포함한다.

- GRU 학습 pose: YOLO11n-Pose, `imgsz=960`, confidence 0.10
- Hailo runtime pose: YOLOv8m-Pose HEF, 640×640, 설치된 postprocess 검출 floor 0.60

따라서 Hailo 출력은 아직 GRU active 경보 입력으로 승격하지 않는다. 우선
서기·걷기·앉기·숙이기·방향별 연기 낙상에서 bbox/keypoint coverage를 수집하고,
Hailo confidence 보정 또는 Hailo 출력으로 재추출한 데이터 기반 GRU 재학습 여부를
결정한다. 기존 rule active와 NCNN runtime은 이 검증 동안 유지한다.

### Pi5 대시보드 동일 프레임 Shadow 비교

`config/cameras.yaml`의 `fall_detection.hailo_shadow`를 활성화했다. Dahua의 NCNN
분석이 끝난 직후 동일한 BGR 프레임을 Hailo adapter에 넣는다. 비교 분기는 Pi5
overlay 시청자가 있을 때만 실행하며 시청 종료 후 자동으로 `paused`가 된다.

2026-10-15 실제 `:8080` overlay 연결 중 계측값:

| 항목 | NCNN 운영 | Hailo Shadow |
|---|---:|---:|
| 동일 프레임 | 기준 | `true` |
| 실효 FPS | 9.38 | 9.44 |
| 평균 추론 지연 | 31.61 ms | 36.64 ms |
| p95 추론 지연 | 42.61 ms | 42.49 ms |
| 검출 사람 수 | 2명 | 1명 |
| confidence 0.25 이상 관절 비율 | 26.47% | 17.65% |
| RTSP source buffer age | 154.8 ms | 같은 입력 프레임 |

두 backend의 사람 수와 관절 비율 차이가 바로 현재 domain 검증 대상이다. 성능은
10 FPS 계약에 근접하지만 Hailo 출력으로 기존 GRU를 즉시 구동해서는 안 된다.
개발 화면에서는 NCNN을 초록 bbox/청록 관절, Hailo를 자홍 bbox/주황 관절로 그린다.
이는 OpenCV가 영상 픽셀에 직접 그리는 server-side overlay이며 브라우저 canvas가
아니다. Pi4 clean WebRTC에는 어느 overlay도 포함하지 않는다.

재현 명령:

```bash
PYTHONPATH=src .venv/bin/python scripts/benchmark_pose_hailo.py \
  --duration 15 --warmup 3
```

## 영상 경로 기준선

```text
Pi4 관제 브라우저
  Dahua -> MediaMTX RTSP source-on-demand -> WebRTC             (원본 H.264)
  Cam3 -> Pi5 clean JPEG on-demand -> FFmpeg H.264 -> WebRTC

Pi5 개발/전시 브라우저
  카메라 -> AI metadata -> 요청 중에만 overlay JPEG -> :8080

AI 경로
  Dahua BGR -> NCNN pose -> Rule(active) + B76 GRU(shadow) -> MQTT metadata

비교 경로(Pi5 :8080 시청 중에만)
  같은 Dahua BGR -> Hailo pose -> 화면/계측만, 경보 미전송
```

Dahua clean 경로는 1920×1080 H.264 High Profile, 입력 표기 25 FPS/평균 15 FPS이며
추가 FFmpeg 프로세스 없이 동작한다. Cam3는 현재 원본 H.264 출력을 공유할
수 없으므로 clean JPEG를 저지연 H.264로 변환하는 과도기 경로다.

시청자가 없으면 Pi5는 JPEG 복사·오버레이·인코딩을 하지 않는다. MediaMTX publisher도
마지막 시청 종료 10초 뒤 정리된다. AI와 MQTT는 화면 연결 여부와 무관하게 계속
동작한다.

## Hailo 적용 순서

1. 완료: Dahua의 최신 BGR 프레임을 Hailo pose 입력으로 사용한다.
2. 완료: Hailo detection/landmark를 기존 `estimate(frame)` 계약으로 변환한다.
3. 진행 중: 동일 프레임 bbox/keypoint, confidence, 사람 수를 NCNN과 화면 비교한다.
4. 다음: B76 3-seed GRU를 `shadow`로 유지한 채 ADL·연기 낙상 로그를 수집한다.
5. 실제 오탐·미탐·지연 기준을 통과하면 GRU를 `active`로 승격한다.
6. rule은 `fallback`으로 한 전시 rehearsal 동안 유지한다.
7. GRU active 및 경보 취소까지 안정화된 뒤 rule active 경로를 제거한다.
8. Dahua가 안정화된 뒤에만 Camera Module 3를 두 번째 pose 입력으로 추가한다.

## rule/GRU 결정

장기 목표는 **GRU 단일 active 판정**이다. 하지만 현재 설정은 rule `active`, GRU
`shadow`이므로 지금 rule 코드를 삭제하면 아직 검증되지 않은 GRU에 경보 안전성을
바로 의존하게 된다. 따라서 다음 세 상태를 명시적으로 거친다.

```text
현재:       rule active   + GRU shadow
전환 시험:  GRU active    + rule fallback/비교 로그
목표:       GRU active    + rule 미실행(코드는 한 릴리스 보존 후 제거)
```

rule과 GRU가 다르게 표시되는 것은 버그가 아니라 현재 shadow 비교 설계의 결과다.
Pi4로 보내는 실제 경보의 단일 진실 공급원은 active detector 하나만 되도록 전환 시
정리한다.

## 완료 판정

- Hailo metadata-only pose가 Dahua에서 실효 10 FPS 이상
- Pi5 CPU가 현재 NCNN 운영값보다 유의미하게 감소
- 30분 ADL에서 중대한 오경보 없음
- 방향별 연기 낙상에서 목표 recall과 경보 지연 기록
- Pi4 MQTT/DB/스피커 경보와 취소 왕복 성공
- Pi4 clean WebRTC와 Pi5 overlay 화면을 동시에 열어도 2시간 안정

낙상 판정은 졸업작품 시연용 위험 징후 탐지이며 의료기기 판정이 아니다.
