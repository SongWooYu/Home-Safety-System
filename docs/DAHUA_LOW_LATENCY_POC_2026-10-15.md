# Dahua 저지연 비전 POC

기준일: 2026-10-15

## 결론

Pi5 `:8080`에서 약 10초까지 누적되던 Dahua 지연의 주원인은 Hailo나 Pose 모델
자체가 아니라 OpenCV/FFmpeg RTSP 수신 큐였다. Camera Module 3가 같은 화면에서
계속 실시간이었던 점, Dahua 표시 FPS만 약 8.5~18.4 FPS 사이에서 급변한 점이
이를 뒷받침한다. 오래된 프레임을 순서대로 처리하다가 한꺼번에 따라잡으면서
사용자에게는 늦게 재생된 뒤 장면을 건너뛰는 것처럼 보였다.

Dahua 입력을 최신 프레임 우선 GStreamer 파이프라인으로 바꾼 뒤 3~6명이 있는
장면에서 90초간 버퍼 age가 약 0.39~0.50초 범위에 머물렀다. 10초 방향으로
증가하지 않았고 입력 오류도 없었다.

## 장애 증거

첨부 화면 녹화는 18.3초, 1736×604, 약 30.5 FPS였다. 녹화 프레임을 2초 간격으로
확인했을 때 다음 패턴이 반복됐다.

- Camera Module 3: 약 14.8~15.4 FPS로 일정
- Dahua: 약 8.5, 9.9, 18.4, 15.8 FPS처럼 급락과 추격이 반복
- Dahua 장면 사람 수: 약 4~6명
- 증상: 동작이 늦게 보이다가 중간 장면을 건너뜀

기존 `last_frame_age`와 `pose_input_age_ms`는 Pi가 프레임을 디코딩한 시점부터
측정했다. 따라서 카메라에서 이미 10초 늦어진 프레임을 방금 읽으면 `0.1s`로
표시되는 측정 사각지대가 있었다.

## 원인

1. OpenCV `VideoCapture`의 `CAP_PROP_BUFFERSIZE=1`은 FFmpeg RTSP 내부 큐에 대해
   항상 강제되지 않는다.
2. RTSP 읽기와 resize/overlay/JPEG 인코딩이 같은 캡처 스레드에 있어 화면 처리
   순간 부하가 RTSP drain을 늦출 수 있었다.
3. B76 3-seed GRU를 사람별로 순차 실행해 다인원 장면에서 비용이 거의 선형으로
   증가했다.
4. 브라우저가 정상이어도 60초마다 MJPEG 연결을 강제로 다시 열어 순간 끊김을
   만들 수 있었다.
5. 기존 Dahua 표시값 640×360/JPEG 70은 원본 1920×1080 메인스트림에 비해
   시각적 열화가 컸다.

## 적용한 POC 경로

```text
Dahua main RTSP 1920×1080 H.264 / 평균 15 FPS
  -> GStreamer rtspsrc TCP, latency=100ms, drop-on-latency
  -> H.264 software decode
  -> leaky queue max-size-buffers=1
  -> 960×540 BGR
  -> appsink max-buffers=1, drop=true, sync=false
  -> 최신 BGR frame 공유
     ├─ YOLO11n-pose NCNN 320 / 목표 10 FPS
     ├─ 사람별 B76 feature -> 다인원 batch GRU shadow
     └─ 요청 중에만 960×540 / 10 FPS / JPEG 80 overlay
```

핵심 정책은 처리량이 순간적으로 부족할 때 과거 영상을 끝까지 재생하지 않고,
중간 프레임을 버려 현재 시점으로 복귀하는 것이다. 실시간 안전 POC에서는 모든
프레임 보존보다 최신 상태 유지가 중요하다.

## 코드 변경

- `src/smarthome_vision/sources/rtsp.py`
  - GStreamer 최신 프레임 우선 backend 추가
  - H.264/H.265 선택, 내부 decode 크기, latency 설정 지원
  - GStreamer PTS 기반 `buffer_age_ms` 제공
  - 필요할 때 사용할 OpenCV fallback 유지
- `src/smarthome_vision/gru_numpy.py`
  - 여러 사람의 20×76 sequence를 한 번에 처리하는 batch GRU 추가
- `src/smarthome_vision/temporal_fall.py`
  - 준비된 사람 track을 한 번의 ensemble batch로 처리
- `src/smarthome_vision/pipeline.py`
  - 카메라별 표시 해상도/FPS/JPEG 품질 지원
  - RTSP backend, buffer age, 시청자 수를 상태 API에 추가
  - Dahua OSD 시계를 가리지 않도록 상단 overlay 폭 제한
- `src/smarthome_vision/templates/index.html`
  - `입력 버퍼 age` 표시
  - 정상 스트림의 60초 강제 재연결 제거
  - 탭 복귀, 페이지 복귀, 네트워크 복구, 실제 오류 때만 재연결

낙상 rule/GRU 임계값, MQTT active/shadow 정책, 얼굴 데이터는 변경하지 않았다.

## 실측 결과

### 단독 입력 시험

| 항목 | 결과 |
|---|---:|
| backend | GStreamer |
| 내부 프레임 | 960×540 BGR |
| 60프레임 수집 | 13.72 FPS |
| 평균 입력 버퍼 age | 279.5 ms |
| 최대 입력 버퍼 age | 426.9 ms |

### 3~6명 운영 장면 90초

| 항목 | 결과 |
|---|---:|
| Dahua 캡처 | 대부분 14.4~15.4 FPS |
| 일시 최저값 | 11.0 FPS, 다음 표본에서 14.8 FPS 회복 |
| Pose 실효값 | 9.11~9.53 FPS |
| Pose 추론 평균 | 약 27.7~32.0 ms |
| GStreamer 버퍼 age | 391.6~499.9 ms, 증가 추세 없음 |
| Vision 프로세스 CPU | 약 152~166% |
| RTSP/서비스 오류 | 0건 |

### 다인원 GRU

동일한 임의 sequence 6명, 3-seed ensemble을 Pi5에서 반복 측정했다.

| 방식 | 6명 처리 시간 |
|---|---:|
| 사람별 순차 | 114.77 ms |
| batch | 67.90 ms |
| 개선 | 약 1.69배 |

### 표시 화질과 대역폭

동일 시점의 Dahua overlay JPEG 표본은 기존 640×360/JPEG70에서 35,597 bytes,
변경 후 960×540/JPEG80에서 76,902 bytes였다. 10 FPS 기준 표본 대역폭은 약
6.2 Mbit/s이며 로컬 전시장 LAN 범위다. 화질을 높이는 대신 FPS를 15에서 10으로
낮춰 브라우저 송신 큐 누적을 억제했다.

전체 단위 테스트는 39개 모두 통과했다.

## 현장 확인 절차

1. `http://192.168.1.20:8080`을 한 번 새로고침한다.
2. Dahua 앞에서 손을 빠르게 좌우로 흔들며 육안 지연과 건너뛰기를 확인한다.
3. Dahua 카드의 `입력 버퍼 age`가 대체로 300~600ms 안에서 움직이고 계속
   증가하지 않는지 본다.
4. 5명 이상이 동시에 들어온 상태로 5분 이상 유지한다.
5. 다음 명령으로 Pose와 입력 age를 함께 확인한다.

```bash
curl -s http://127.0.0.1:8080/api/status
journalctl -u smarthome-vision.service -f
```

합격 기준은 캡처 13 FPS 이상, Pose 9 FPS 이상, 버퍼 age 1초 미만 유지,
RTSP 재연결 반복 없음이다. 일시적인 Wi-Fi 손실 뒤에는 중간 프레임을 건너뛰어
1초 안팎으로 최신 화면에 복귀해야 한다.

## 알려진 한계와 다음 단계

- `source_buffer_age_ms`는 Pi5 GStreamer 파이프라인 내부 PTS 지연이다. 카메라
  센서 노출부터 브라우저 표시까지의 완전한 종단 지연은 아니다.
- Dahua OSD 시계가 Pi5보다 약 1시간 느리므로 NTP/시간대 설정을 맞춰야 OSD로
  절대 종단 지연을 측정할 수 있다. 이 고정 시계 차이는 영상 지연과 별개다.
- Pi5 `:8080`은 여전히 개발용 MJPEG다. Wi-Fi 품질이 낮은 클라이언트에서는
  브라우저 자체 송신 대기열이 생길 수 있다.
- Pi4 통합 화면은 Dahua 원본 H.264 WebRTC를 사용하므로 이 MJPEG 품질 설정과
  별개다.
- 다음 성능 단계는 Hailo metadata-only pose를 기존 tracker/B76 입력 계약에
  연결해 NCNN CPU 부하를 제거하는 것이다. 공식 Hailo 전체 overlay 앱을 그대로
  넣지 않는다.

