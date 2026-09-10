# 현재 프로젝트 상태

기준일: 2026-09-10

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
- 카메라: Camera Module 3, ABKO APC720, Dahua RTSP 모두 온라인
- 객체 검출: YOLO11n NCNN, 화면과 이벤트에는 `person`만 사용
- 자세/낙상: YOLO11n-pose NCNN과 보수적인 시간 기반 상태 추적
- 얼굴: OpenCV YuNet + SFace, 등록·삭제 API는 관리 키 필요
- MQTT: `192.168.1.10:1883`로 이벤트와 상태 전송
- 얼굴 원본 사진은 저장하지 않으며 특징 벡터 파일도 Git에서 제외

실측 상태는 시점과 장면에 따라 달라지지만 세 입력은 약 14~30 FPS로 캡처된다.
AI 분석 FPS는 캡처 FPS보다 낮게 제한하여 Pi5 CPU 부하를 제어한다.

## 디렉터리 역할

```text
/home/pi/Home-Safety-System
├── config/                 Pi5 카메라·추론·MQTT 설정
├── src/smarthome_vision/   Pi5 수집, 추론, 이벤트, 개발 대시보드
├── models/                 Git에 포함된 YOLO11 NCNN 모델
├── runtime/                내려받은 얼굴 모델; Git 제외
├── data/                   얼굴 특징 벡터 등 운영 데이터; Git 제외
├── scripts/                Pi5 모델 설치 도구
├── systemd/                Pi5 자동 시작 서비스
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

Pi4의 `:8081`은 Pi5에서 오버레이가 끝난 세 MJPEG 영상을 재인코딩 없이
중계하고, 전체 안전 상태, 최근 사건, 경보 확인·취소를 함께 제공하는 사용자용
화면이다. 영상은 기본 8 FPS로 요청하여 Pi5 CPU와 무선 LAN 사용량을 제한한다.

## 완료된 것

- 세 입력 인터페이스를 동일한 BGR 프레임/탐지 결과/이벤트 형식으로 통합
- Dahua 메인 스트림(`subtype=0`) 사용
- 사람 외 객체의 시각화와 상태 출력을 숨김
- 상태 변화 기반 사람·낙상 MQTT 이벤트와 retain 카메라 상태 발행
- Pi5 자동 시작과 장시간 3카메라 표시 확인
- Pi5 개발 화면 스트림 자동 재연결
- 관리 키로 보호한 얼굴 등록·삭제, 이름 비공개 상태 출력
- 정면·좌측·우측 다각도 얼굴 템플릿
- Pi4 MQTT/PostgreSQL/수집/자동화/최종 화면 Compose 구성과 설치 도구

## 남은 핵심 작업

1. Pi4에서 저장소를 clone하고 기존 `/opt/smarthome`을 안전하게 마이그레이션
2. Pi5→Pi4 MQTT 실제 왕복, DB 중복 방지, 경보 취소 통합 시험
3. Pi4와 Pi5 동시 재부팅 후 자동 복구 확인
4. 스피커/부저의 실제 GPIO 또는 USB 오디오 출력을 Pi4 경보 토픽에 연결
5. 전시장 동선으로 낙상 오탐·미탐 데이터를 수집하고 임계값을 마지막에 조정
6. MQTT 익명 접속을 인증 방식으로 전환하고 방화벽 범위를 전시장 LAN으로 제한

낙상은 현재 의료적으로 검증된 판정이 아니라 졸업작품 시연용 위험 징후 MVP다.
