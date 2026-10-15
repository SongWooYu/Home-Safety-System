# Hailo-8 런타임 기준선과 전환 계획

기준일: 2026-10-15

## 결론

AI HAT+의 Hailo-8은 정상 인식되고 pose HEF도 하드웨어에서 약 31 FPS로 실행된다.
현재 운영 서비스는 아직 NCNN CPU pose를 사용한다. 다음 구현은 Hailo callback에서
사람 bbox와 17개 keypoint만 꺼내 기존 tracker/B76 GRU에 넣는 것이다.

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

## 영상 경로 기준선

```text
Pi4 관제 브라우저
  Dahua -> MediaMTX RTSP source-on-demand -> WebRTC             (원본 H.264)
  Cam3 -> Pi5 clean JPEG on-demand -> FFmpeg H.264 -> WebRTC

Pi5 개발/전시 브라우저
  카메라 -> AI metadata -> 요청 중에만 overlay JPEG -> :8080

AI 경로
  Dahua clean frame -> Hailo pose -> tracker -> B76 GRU -> MQTT metadata
```

Dahua clean 경로는 1920×1080 H.264 High Profile, 입력 표기 25 FPS/평균 15 FPS이며
추가 FFmpeg 프로세스 없이 동작한다. Cam3는 현재 원본 H.264 출력을 공유할
수 없으므로 clean JPEG를 저지연 H.264로 변환하는 과도기 경로다.

시청자가 없으면 Pi5는 JPEG 복사·오버레이·인코딩을 하지 않는다. MediaMTX publisher도
마지막 시청 종료 10초 뒤 정리된다. AI와 MQTT는 화면 연결 여부와 무관하게 계속
동작한다.

## Hailo 적용 순서

1. Dahua의 로컬 clean RTSP 경로를 Hailo pose 입력으로 사용한다.
2. Hailo detection/landmark 결과를 기존 `estimate(frame)` 결과 계약으로 변환한다.
3. bbox/keypoint 좌표, confidence, track ID를 단위 영상으로 NCNN과 비교한다.
4. B76 3-seed GRU를 `shadow`로 유지한 채 ADL·연기 낙상 로그를 수집한다.
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
