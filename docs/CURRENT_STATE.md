# 현재 프로젝트 상태

기준일: 2026-09-17

## 단일 기준 작업 공간

현재 유효한 프로젝트는 다음 하나입니다.

- 로컬 경로: `/home/pi/Home-Safety-System`
- Git 브랜치: `main`
- 원격 저장소: `https://github.com/SongWooYu/Home-Safety-System.git`
- Pi5 개발 대시보드: `http://192.168.1.20:8080`
- Pi4 최종 서비스 예정 화면: `http://192.168.1.10:8081`

과거 중복 작업 공간 `/home/pi/songwoo`, `/workspace/Home-Safety-System`,
`/workspace/docker_exam`, `/home/pi/.pyenv`는 현재 존재하지 않는다. USB 메모리로
프로젝트나 데이터를 옮기는 계획은 취소했다.

## 장치와 네트워크 역할

| 장치 | 주소 | 역할 |
|---|---:|---|
| 공유기 | 192.168.1.1 | 전시장 사설 LAN |
| Raspberry Pi 5 | 192.168.1.20 (wlan0) | 3종 카메라 수집과 AI 추론 |
| Raspberry Pi 4 | 192.168.1.10 | MQTT, PostgreSQL, 자동화, 사용자 화면 |
| Dahua IP Camera | 192.168.1.64 | 공유기에 연결된 RTSP 카메라 |

Pi5의 `eth0`는 현재 내려가 있고 Dahua는 Pi5에 직결하지 않는다. 이 구성으로
직결 LAN과 공유기 LAN의 경로 충돌을 피한다.

## Pi5 운영 상태

- OS: Raspberry Pi OS/Debian Trixie, aarch64
- 커널: `6.12.75+rpt-rpi-2712`
- 로케일: `C.UTF-8`; 이전 `en_US.UTF-8` 경고는 현재 발생 조건이 제거됨
- 서비스: `smarthome-vision.service`가 enabled/active
- WebRTC: MediaMTX가 enabled/active, 카메라별 FFmpeg는 시청 중에만 on-demand 실행
- 전시 출력: HDMI-A-2 연결 시 Pi5 로컬 3카메라 화면을 즉시 전체화면으로 실행; HDMI-A-1은 연결 시 OS 데스크톱
- 전시 영상: H.264 640×360, 15 FPS, 카메라당 1,000 kbit/s
- 현재 카메라: Camera Module 3, ABKO 웹캠, Dahua RTSP 모두 온라인
- 객체 검출: YOLO11n NCNN, 화면과 이벤트에는 `person`만 사용
- 자세/낙상: YOLO11n-pose NCNN과 보수적인 시간 기반 상태 추적
- 얼굴: OpenCV YuNet + SFace, 등록은 코드 불필요; 목록 조회·삭제는 관리 키 필요
- MQTT: `192.168.1.10:1883`로 이벤트와 상태 전송
- 얼굴 원본 사진은 저장하지 않으며 특징 벡터 파일도 Git에서 제외

세 장치 입력은 약 12~25 FPS로 캡처된다. 2026-09-17 점검 시에는
세 카메라 모두 온라인이고 MQTT도 연결된 상태였다.
AI 분석 FPS는 캡처 FPS보다 낮게 제한하여 Pi5 CPU 부하를 제어한다.

## 디렉터리 역할

```text
/home/pi/Home-Safety-System
├── config/                 Pi5 카메라·추론·MQTT·MediaMTX 설정
├── config/display/         듀얼 HDMI 배치와 사용자 시연 서비스 설정
├── src/smarthome_vision/   Pi5 수집, 추론, 이벤트, 개발 대시보드
├── models/                 Git에 포함된 YOLO11 NCNN 모델
├── runtime/                내려받은 얼굴 모델; Git 제외
├── data/                   얼굴 특징 벡터 등 운영 데이터; Git 제외
├── scripts/                Pi5 모델 및 WebRTC 설치 도구
├── systemd/                Pi5 자동 시작 서비스
├── config/systemd/         MediaMTX 자동 시작 서비스
├── pi4/                    Pi4 clone-and-run Compose 스택
├── docs/                   설계, 운영, 진행 상태 문서
├── tests/                  Pi5 단위 테스트
└── legacy/                 비교·참고용 과거 프로토타입
```

`.venv`는 Pi5용 단일 환경이다. Picamera2 등 Raspberry Pi OS 패키지를 재사용하기
위해 `--system-site-packages`로 만들어졌고 Git에 포함하지 않는다. Pi4는 venv를
만들지 않고 Docker 이미지 안에서 Python 의존성을 고정한다.

## 개발 화면과 최종 화면의 구분

Pi5의 `:8080`은 카메라 입력, 탐지 박스, FPS, 낙상 규칙, 얼굴 등록을 확인하는
개발용 대시보드다. 최종 전시 서비스가 아니다. 브라우저 절전·탭 복귀 후 검은
화면을 줄이기 위해 visibility, focus, pageshow, online 이벤트와 주기 검사로
MJPEG 연결을 새로 만든다.

Pi4의 `:8081`은 전체 안전 상태, 최근 사건, 경보 확인·취소를 제공하는 사용자용
화면이다. 영상 iframe은 Pi4를 거치지 않고 Pi5 `:8889`의 MediaMTX와 WebRTC로
직접 연결한다. 기본 영상은 H.264 640×360, 15 FPS, 1,000 kbit/s이며 절전·탭 복귀
뒤 iframe을 새로 연결한다.

## 완료된 것

- 세 입력 인터페이스를 동일한 BGR 프레임/탐지 결과/이벤트 형식으로 통합
- Dahua 메인 스트림(`subtype=0`) 사용
- 사람 외 객체의 시각화와 상태 출력을 숨김
- 상태 변화 기반 사람·낙상 MQTT 이벤트와 retain 카메라 상태 발행
- Pi5 자동 시작과 장시간 3카메라 표시 확인
- Pi5 개발 화면 스트림 자동 재연결
- 코드 없는 현장 얼굴 등록, 관리 키로 보호한 목록·삭제, 이름 비공개 상태 출력
- 정면·좌측·우측 다각도 얼굴 템플릿
- Pi4 MQTT/PostgreSQL/수집/자동화/최종 화면 Compose 구성과 설치 도구
- Pi5 MediaMTX/WebRTC와 3개 H.264 publisher 설치·자동 시작
- Pi4 MJPEG Python 프록시 제거, 브라우저-Pi5 직접 영상 경로 구현

## 협업자 커밋 확인

Pi4에서 푸시한 `32e0857 Add collaborator smarthome reference`는
`reference/collaborator-smarthome/` 아래 참고 코드 7개만 추가한다. 현재 실행되는
`pi4/` 스택을 덮어쓰지 않는다. 센서 collector·automation 아이디어는 나중에
선별 통합할 수 있지만, 컨테이너 내부 `localhost` 사용과 별도 웹 구현은 현재
Compose 구조에 그대로 합치지 않는다.

## 남은 핵심 작업

1. Pi4에서 최신 커밋을 pull하고 `sudo ./pi4/scripts/install.sh`로 WebRTC 화면 반영
2. Pi5→Pi4 MQTT 실제 왕복, DB 중복 방지, 경보 취소 통합 시험
3. Pi4와 Pi5 동시 재부팅 후 자동 복구 확인
4. 스피커/부저의 실제 GPIO 또는 USB 오디오 출력을 Pi4 경보 토픽에 연결
5. 전시장 동선으로 낙상 오탐·미탐 데이터를 수집하고 임계값을 마지막에 조정
6. MQTT 익명 접속을 인증 방식으로 전환하고 방화벽 범위를 전시장 LAN으로 제한

낙상은 현재 의료적으로 검증된 판정이 아니라 졸업작품 시연용 위험 징후 MVP다.
