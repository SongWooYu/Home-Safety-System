# 구현 및 설정 통합 기록

기준일: 2026-09-17

이 문서는 프로젝트가 여러 작업 공간과 실험 환경으로 흩어졌던 시점부터 현재의
단일 저장소, 3종 카메라 파이프라인, 얼굴 등록, 낙상 MVP, Pi4 서버, WebRTC와
전시 화면까지 실제로 구현된 내용을 한 곳에 기록한다. 앞으로 현재 상태를
확인할 때는 이 문서와 `config/cameras.yaml`을 우선 기준으로 사용한다.

## 1. 프로젝트 목적과 현재 단계

졸업작품의 목표는 입력 방식이 다른 카메라를 동일한 AI 결과와 사건 형식으로
통합하고, 낙상 위험을 감지해 화면·MQTT·DB·알림으로 이어지는 전체 흐름을
시연하는 것이다.

현재 단계는 **3종 입력 통합과 CPU 기반 기능 MVP가 끝났고, 실제 Pi4 통합 시험과
학습형 낙상 모델 교체를 앞둔 상태**다. 지금 낙상 판정은 시간 기반 자세 규칙이며
학습된 낙상 전용 모델이나 의료적으로 검증된 판정이 아니다.

## 2. 단일 기준 저장소

| 항목 | 현재 값 |
|---|---|
| 프로젝트 경로 | `/home/pi/Home-Safety-System` |
| Git 브랜치 | `main` |
| 원격 저장소 | `https://github.com/SongWooYu/Home-Safety-System.git` |
| Pi5 개발 화면 | `http://192.168.1.20:8080` |
| Pi4 서비스 화면 예정 | `http://192.168.1.10:8081` |

과거 중복 작업 공간 `/home/pi/songwoo`, `/workspace/Home-Safety-System`,
`/workspace/docker_exam`, `/home/pi/.pyenv`는 정리했다. 프로젝트와 데이터를
32 GB USB 메모리로 옮기는 계획은 취소했다.

Pi5에는 프로젝트 전용 `.venv` 하나만 둔다. Picamera2와 Raspberry Pi OS 패키지를
사용하기 위해 `--system-site-packages` 방식이며 Git에는 포함하지 않는다. Pi4는
호스트 venv를 추가하지 않고 Docker 이미지 안에서 Python 의존성을 관리한다.

## 3. 하드웨어와 네트워크

```text
                         ipTIME A604SE
                         192.168.1.1
                         /     |      \
             유선 RTSP /      | Wi-Fi \ Wi-Fi
                       /       |        \
        Dahua 192.168.1.64   Pi5 .20    Pi4 .10
                              비전 노드   제어 서버
```

| 장치 | 연결 | 주소 | 역할 |
|---|---|---:|---|
| Dahua IP Camera | 공유기 유선 LAN | 192.168.1.64 | RTSP 메인 스트림 |
| Raspberry Pi 5 8 GB | 공유기 Wi-Fi | 192.168.1.20 | 수집, AI 추론, 오버레이, 영상 제공 |
| Raspberry Pi 4 4 GB | 공유기 Wi-Fi | 192.168.1.10 | MQTT, PostgreSQL, 자동화, 서비스 웹 |
| 관리 PC/전시 브라우저 | 같은 LAN | DHCP | 화면 접속 |

Pi5 `eth0`는 사용하지 않고 Dahua를 Pi5에 직결하지 않는다. 과거의 직결 LAN과
공유기 LAN 충돌을 피하기 위한 결정이다. 공유기 포트포워딩은 하지 않는다.

## 4. Pi5 실제 환경

- Raspberry Pi OS/Debian Trixie, aarch64
- 커널 `6.12.75+rpt-rpi-2712`
- 4코어 Cortex-A76, 최대 2.4 GHz
- 메모리 약 8 GB
- 루트 저장 장치 약 58 GB, 2026-09-17 점검 당시 약 42 GB 여유
- 로케일 `C.UTF-8`; 잘못 지정된 `en_US.UTF-8` 로그인 경고 해결
- `smarthome-vision.service`: enabled/active
- `smarthome-mediamtx.service`: enabled/active
- `home-safety-demo-display.service`: 현재 중지 상태

2026-09-17 점검 당시 세 카메라와 MQTT는 모두 온라인이었고 얼굴 등록자는 4명이었다.
실측 캡처 속도는 장면에 따라 Camera Module 3 약 29 FPS, 웹캠 약 14~15 FPS,
Dahua 약 25 FPS였다. AI 분석은 이보다 낮은 별도 주기로 실행한다.

## 5. 저장소 구조

```text
Home-Safety-System/
├── config/                 Pi5 카메라, AI, MQTT, MediaMTX 설정
├── config/display/         듀얼 HDMI 배치와 전시 서비스 템플릿
├── src/smarthome_vision/   수집, 추론, 이벤트, 개발 대시보드
├── models/                 현재 YOLO NCNN 모델
├── runtime/                내려받은 얼굴 모델과 런타임 파일(Git 제외)
├── data/                   얼굴 특징 벡터 등 운영 데이터(Git 제외)
├── scripts/                모델, WebRTC, HDMI 설치·실행 도구
├── systemd/                Pi5 비전 서비스
├── pi4/                    Pi4 Docker Compose 서버 스택
├── tests/                  Pi5 단위 테스트
├── docs/                   설계·설정·운영 문서
├── legacy/                 과거 프로토타입 참고 자료
└── reference/              협업자 참고 구현
```

## 6. 카메라 입력과 통합 경로

| ID | 장치 | 수집 방식 | 현재 입력 설정 | 목적 |
|---|---|---|---|---|
| `cam3` | Camera Module 3 | Picamera2/libcamera | 960×540, 30 FPS | 낙상 시연, 개발 화면 |
| `webcam` | ABKO APC720 | V4L2/OpenCV, MJPG 요청 | 1280×720, 30 FPS 요청 | 얼굴 등록, 근거리 확인 |
| `dahua` | Dahua | RTSP/OpenCV/FFmpeg, TCP | 메인 스트림 `subtype=0` | 낙상 시연, 전시장 광각 |

Camera Module 3 자체는 MJPEG 웹캠이 아니다. Picamera2가 센서 프레임을 배열로
전달한다. 세 입력은 수집 방식은 다르지만 이후에는 모두 OpenCV BGR 프레임으로
정규화된다.

```text
카메라 캡처
  -> 최신 BGR 프레임
  -> 제한된 주기의 객체/pose/face 추론
  -> 사람·등록 여부·낙상 상태 추적
  -> MQTT 상태/사건 발행
  -> 오버레이
  -> 개발용 MJPEG 또는 전시용 H.264/WebRTC
```

AI 처리는 JPEG/H.264/WebRTC로 변환하기 전에 한다. 따라서 전송 형식이 바뀌어도
세 카메라의 분석 계약은 동일하다.

## 7. 현재 AI 설정

### 7.1 사람 객체 검출

- 모델: `models/yolo11n_ncnn_model`
- 입력: 320
- confidence: 0.35
- NMS IoU: 0.45
- NCNN CPU 스레드: 4
- 화면과 사건에는 `person`만 남김

모델 내부는 COCO의 다른 클래스도 계산한다. 사람만 출력하도록 필터링한 것은
화면을 단순화한 것이며 모델 자체의 연산량은 줄이지 않는다.

### 7.2 낙상 MVP

- 모델: `models/yolo11n-pose_ncnn_model`
- pose 분석: 최대 1.5 FPS
- 입력: 320, CPU 스레드 2
- 몸통 각도, 사람 박스 비율, 직전 상태, 지속 시간을 조합한 규칙
- 사건: `fall_suspected`, `fall_confirmed`, `fall_cleared`

앉은 사람을 낙상으로 과도하게 판정하던 공격적인 규칙은 되돌렸다. 현재도 카메라
방향, 가림, 세로 방향 낙상에서 미탐이 생길 수 있다. 이는 학습형 시간 모델로
교체하기 전의 시연용 기준선이다.

### 7.3 얼굴 등록과 인식

- 검출: OpenCV YuNet
- 정렬·특징 벡터: OpenCV SFace
- 분석 주기: 약 0.5 FPS
- 기본 cosine 유사도 임계값: 0.45
- 저장: `data/faces.json`; 원본 얼굴 사진은 저장하지 않음
- 등록: 정면, 좌측, 우측 각도별 템플릿
- 등록 동작에는 코드가 필요하지 않음
- 목록 조회와 삭제에만 `FACE_ADMIN_TOKEN` 필요

등록 API는 전시장 LAN 안에서만 사용해야 한다. 특징 벡터도 생체정보이므로 Git,
공개 백업, 일반 로그에 포함하지 않는다.

## 8. 개발 화면과 영상 전송

### 8.1 Pi5 `:8080`

Pi5의 `:8080`은 최종 서비스가 아니라 다음을 확인하는 개발·등록 대시보드다.

- 세 카메라 입력 상태와 FPS
- 사람 박스, pose, 낙상 상태
- 어떤 사건이 발생했는지
- 얼굴 정면·좌측·우측 등록

현재 MJPEG 출력만 640×360, 15 FPS, JPEG 품질 70으로 낮췄다. 원본 캡처와 AI,
얼굴 등록용 프레임은 이 축소 영향을 받지 않는다. 브라우저 절전이나 화면 복귀 후
검은 화면을 줄이기 위해 visibility/focus/pageshow/online 이벤트와 60초 watchdog로
영상 연결을 재생성한다.

### 8.2 WebRTC

Pi4가 MJPEG 바이트를 중계하던 초기 구현은 느리고 끊겼다. 현재는 Pi5에서
오버레이 MJPEG를 FFmpeg `libx264`로 H.264 640×360, 15 FPS, 카메라당 약
1,000 kbit/s로 바꾸고 MediaMTX가 브라우저에 WebRTC로 직접 전달한다.

```text
Pi4 :8081 -> HTML, 상태 API, 경보
브라우저 <-> Pi5 :8889/:8189 -> WebRTC 영상
```

카메라 publisher는 시청 중에만 실행하고 마지막 시청 종료 10초 뒤 닫는다.
Pi4 백엔드는 영상 바이트를 처리하지 않는다.

### 8.3 성능 문제와 조치

원본 크기 MJPEG 세 개를 동시에 보내던 때에는 합계 약 7.3 MB/s와 높은 Python CPU,
큰 송신 대기열이 생겼다. 출력 전용 프레임을 640×360/15 FPS/품질 70으로 줄인 뒤
합계 약 1.4 MB/s로 감소했고, FFmpeg도 카메라당 약 7% CPU 수준으로 내려갔다.
이는 실측 당시 값이며 장면과 접속자 수에 따라 변한다.

로컬 HDMI Chromium, 원격 MJPEG, 세 WebRTC 스트림을 동시에 켜면 같은 프레임 생성과
소프트웨어 인코딩 자원을 경쟁한다. 그래서 HDMI 전시 서비스는 현재 꺼 두었고,
시연 때만 한 화면 경로를 선택하는 운영 원칙이 필요하다.

## 9. HDMI 전시 화면

- `HDMI-A-1`: 일반 Raspberry Pi OS 화면
- `HDMI-A-2`: 연결된 경우 전시용 전체화면
- 한 대만 `HDMI-A-2`에 연결해도 전시 화면으로 사용
- USB 마우스로 얼굴 등록과 관리 UI 사용 가능

웹 UI는 필수가 아니지만 이미 등록·상태·복구 로직이 있어 로컬 Chromium을 사용했다.
현재는 영상 부하 점검을 위해 사용자 서비스를 중지했다. 전시 전에는 WebRTC 기반
로컬 화면 또는 저부하 네이티브 화면과 비교한 뒤 하나만 활성화한다.

## 10. MQTT와 Pi4 서버

Pi5는 영상이 아니라 JSON 사건과 최신 상태만 Pi4로 보낸다.

| 토픽 | 의미 |
|---|---|
| `home/vision/events` | 사람/낙상 상태 변화, QoS 1, 비 retain |
| `home/vision/status/<camera>` | 5초 주기 최신 카메라 상태, retain |
| `home/safety/fall/state` | Pi4 자동화가 계산한 전체 안전 상태 |
| `home/safety/fall/alarm` | 스피커·부저용 활성 상태 |
| `home/safety/fall/command` | UI/버튼의 경보 취소 명령 |

Pi4 `pi4/compose.yml`은 다음 다섯 서비스를 정의한다.

| 서비스 | 역할 |
|---|---|
| Mosquitto 2 | MQTT 브로커, 외부 1883 |
| PostgreSQL 16 | 사건·상태·안전 상태 저장 |
| collector | `home/#` 구독, 정규화와 중복 방지 |
| automation | 낙상 사건을 경보 상태로 전환 |
| web | Gunicorn/Flask 최종 UI, 외부 8081 |

DB는 `event_id`를 기준으로 중복 사건을 막고, 5초 상태는 계속 누적하지 않고
카메라별 최신 행을 upsert한다. 실제 스피커/부저 드라이버는 아직 구현되지 않았다.

## 11. 주요 개발 이력

| 커밋 | 구현 내용 |
|---|---|
| `2d995d5` | 대시보드와 브라우저 영상 자동 재연결 |
| `d1eaa64` | CPU 낙상 MVP와 MQTT heartbeat |
| `ac1f58e` | 방향성 낙상 규칙과 화면 비율 개선 |
| `6df8656` | 관리 보호 얼굴 등록, 사람 중심 출력 |
| `dcc14ae` | clone 가능한 Pi4 스택, 다각도 얼굴 등록 |
| `023ec78` | Pi5에서 브라우저로 직접 WebRTC |
| `bc29d7d` | WebRTC 15 FPS 조정 |
| `abd540d`, `d0831cc` | 듀얼 HDMI와 HDMI-A-2 전시 화면 |
| `a8c5f37` | MJPEG 부하 절감과 정지 화면 복구 |

협업자 참고 커밋 `32e0857`은 `reference/collaborator-smarthome/`에만 자료를
추가했으며 현재 `pi4/` 실행 스택을 덮어쓰지 않는다.

## 12. 설치와 운영 기준

Pi5 확인:

```bash
cd /home/pi/Home-Safety-System
sudo systemctl status smarthome-vision.service
systemctl status smarthome-mediamtx.service
curl -s http://127.0.0.1:8080/health
journalctl -u smarthome-vision.service -f
```

Pi4 신규 설치:

```bash
git clone https://github.com/SongWooYu/Home-Safety-System.git
cd Home-Safety-System
sudo ./pi4/scripts/install.sh
```

운영 비밀은 `.env`에 두고 Git에 올리지 않는다. Dahua 비밀번호를 포함한 RTSP URL,
MQTT 자격 증명, PostgreSQL 비밀번호, 얼굴 관리 키가 대상이다.

## 13. 완료·미완료 구분

완료:

- 세 입력을 BGR 프레임, 탐지 결과, MQTT 계약으로 통합
- Dahua 메인 스트림 사용
- 사람만 표시
- 상태 변화 사건과 주기 상태 발행
- 얼굴 다각도 등록, 특징 벡터 저장, 보호된 삭제
- Pi4 Compose 서버와 clone 설치 스크립트
- Pi5 MediaMTX/WebRTC 직접 영상 경로
- 개발 MJPEG 부하 완화와 브라우저 복구

미완료:

- Pi4 실제 장치에서 최신 스택 전체 재설치·왕복 검증
- 학습형 낙상 모델과 전시장 데이터 검증
- 실제 부저/스피커 동작
- 등록자와 사람 추적 ID의 장시간 결합
- MQTT 인증, 방화벽, CORS/HTTPS 등 전시망 보안 강화
- Pi4/Pi5 동시 재부팅 및 2시간 이상 통합 부하 시험

## 14. 관련 문서

- [자원 제약 기반 재설계](ARCHITECTURE_REVIEW.md)
- [현재 프로젝트 상태](CURRENT_STATE.md)
- [Pi5 비전 노드](PI5_VISION.md)
- [Pi4 중앙 서버](PI4_SERVER.md)
- [WebRTC 영상 전달](WEBRTC_STREAMING.md)
- [얼굴 등록과 인식](FACE_RECOGNITION.md)
- [듀얼 HDMI](DUAL_DISPLAY.md)
