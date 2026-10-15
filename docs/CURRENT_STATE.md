# 현재 프로젝트 상태

기준일: 2026-10-15

## 2026-10-15 핵심 변경

- AI HAT+ Hailo-8 장착과 펌웨어 4.23.0 인식을 확인했다.
- Hailo pose는 하드웨어 기준 30.80 FPS, metadata-only 파이프라인 31.75 FPS였다.
- Pi4 관제 영상은 clean WebRTC, Pi5 `:8080`은 요청 중에만 overlay를 생성한다.
- Dahua는 `dahuaclean` 원본 H.264 pass-through로 재인코딩을 제거했다.
- 시청 종료 뒤 JPEG 렌더링과 FFmpeg publisher가 자동 정리된다.
- 현재 운영 AI는 아직 NCNN이며 Hailo pose의 tracker/GRU 연결이 다음 단계다.
- rule은 지금 삭제하지 않고 GRU active 검증 뒤 fallback을 거쳐 제거한다.
- ABKO APC720 운영 경로를 제거하고 Camera Module 3가 얼굴 등록·인식을 담당한다.
- 오버레이 좌표는 원본 해상도에서 640×360 표시 좌표로 명시 변환한다.


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
| Raspberry Pi 5 | 192.168.1.20 (wlan0) | 2종 카메라 수집과 AI 추론 |
| Raspberry Pi 4 | 192.168.1.10 | MQTT, PostgreSQL, 자동화, 사용자 화면 |
| Dahua IP Camera | 192.168.1.64 | 공유기에 연결된 RTSP 카메라 |

Pi5의 `eth0`는 현재 내려가 있고 Dahua는 Pi5에 직결하지 않는다. 이 구성으로
직결 LAN과 공유기 LAN의 경로 충돌을 피한다.

## Pi5 운영 상태

- OS: Raspberry Pi OS/Debian Trixie, aarch64
- 커널: `6.12.75+rpt-rpi-2712`
- 로케일: `C.UTF-8`; 이전 `en_US.UTF-8` 경고는 현재 발생 조건이 제거됨
- 서비스: `smarthome-vision.service`가 enabled/active
- Hailo: AI HAT+ Hailo-8 장착, 공식 pose/metadata-only 기준선 검증 완료
- WebRTC: MediaMTX가 enabled/active; Dahua는 원본 H.264, Cam3만 on-demand FFmpeg
- 전시 출력: 기존 HDMI Chromium 자동 실행은 disabled/inactive; 네이티브 Wayland/OpenGL 표시 경로를 다음 단계로 구현
- 개발 MJPEG: 640×360, 15 FPS, JPEG 품질 70; 전시 WebRTC: H.264 640×360, 15 FPS, 카메라당 1,000 kbit/s
- 현재 카메라: Camera Module 3와 Dahua RTSP, 2/2 온라인
- 사람/자세: Dahua의 YOLO11n-pose NCNN 320 단일 추론에서 bbox와 keypoint 생성
- 시간 낙상: B76 3-seed NumPy GRU ensemble을 20프레임/10 FPS Quiet shadow로 실행
- rule 낙상: fallback을 유지하며 현재 MQTT `active`; 최근 장면의 반복 상태 전이가 검증 위험
- 얼굴: OpenCV YuNet + SFace, 등록은 코드 불필요; 목록 조회·삭제는 관리 키 필요
- MQTT: `192.168.1.10:1883`로 이벤트와 상태 전송
- 얼굴 원본 사진은 저장하지 않으며 특징 벡터 파일도 Git에서 제외

2026-10-08의 ABKO 약 7.5 FPS 결과는 퇴역 전 역사적 기준이다. 2026-10-15 전환 후
Camera Module 3와 Dahua는 각각 약 14.9 FPS로 수집되고 MQTT가 연결됐다. Dahua pose는 고유한
새 프레임만 사용해 약 9.75~9.77 FPS를 유지한다. 640 pose는 전체 서비스에서
7.88 FPS, 960 pose는 단독 약 5.35 FPS라 Hailo 전 운영 모델은 320으로 확정했다.

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
개발/전시 진단 대시보드다. 이 화면에 접속한 동안에만 overlay JPEG를 생성하며,
화면을 닫으면 렌더링 분기는 중지된다. 브라우저 절전·탭 복귀 후 검은
화면을 줄이기 위해 visibility, focus, pageshow, online 이벤트와 60초 watchdog으로
MJPEG 연결을 새로 만든다. 상태·이벤트 조회 주기는 3초다.

Pi4의 `:8081`은 전체 안전 상태, 최근 사건, 경보 확인·취소를 제공하는 통합 관제
화면이다. 영상 iframe은 Pi4를 거치지 않고 Pi5 `:8889`의 MediaMTX와 WebRTC로
직접 연결하며 overlay를 표시하지 않는다. Cam3는 H.264 640×360/15 FPS,
Dahua는 `dahuaclean`의 1920×1080 원본 H.264를 사용한다. 절전·탭 복귀 뒤 iframe을
새로 연결한다.

## 완료된 것

- Picamera2와 RTSP 입력을 동일한 BGR 프레임/탐지 결과/이벤트 형식으로 통합
- Dahua 메인 스트림(`subtype=0`) 사용
- 사람 외 객체의 시각화와 상태 출력을 숨김
- 상태 변화 기반 사람·낙상 MQTT 이벤트와 retain 카메라 상태 발행
- Pi5 자동 시작과 2카메라 수집 확인
- Pi5 개발 화면 MJPEG 640×360/15 FPS 경량화와 60초 자동 재연결
- 코드 없는 현장 얼굴 등록, 관리 키로 보호한 목록·삭제, 이름 비공개 상태 출력
- 정면·좌측·우측 다각도 얼굴 템플릿
- Pi4 MQTT/PostgreSQL/수집/자동화/최종 화면 Compose 구성과 설치 도구
- Pi5 MediaMTX/WebRTC, Dahua 원본 H.264 pass-through, Cam3 on-demand publisher
- Pi5 overlay와 Pi4 clean 영상 분리, 미시청 시 JPEG/FFmpeg 자동 중지
- Hailo-8 pose 하드웨어·metadata-only 성능 기준선 확보
- Pi4 MJPEG Python 프록시 제거, 브라우저-Pi5 직접 영상 경로 구현
- 동일 RTSP 프레임의 temporal buffer 중복 삽입 방지와 실효 FPS/지연 계측
- B76 3-seed NumPy GRU shadow, 사람별 motion tracker, confirm/release/cooldown 구현
- 비영상 JSONL shadow 관찰 로그와 품질 진단·요약 도구
- Pi5→Pi4 비경보 MQTT/DB/API 왕복과 동일 event_id 중복 방지 실측 성공

## 협업자 커밋 확인

Pi4에서 푸시한 `32e0857 Add collaborator smarthome reference`는
`reference/collaborator-smarthome/` 아래 참고 코드 7개만 추가한다. 현재 실행되는
`pi4/` 스택을 덮어쓰지 않는다. 센서 collector·automation 아이디어는 나중에
선별 통합할 수 있지만, 컨테이너 내부 `localhost` 사용과 별도 웹 구현은 현재
Compose 구조에 그대로 합치지 않는다.

## 남은 핵심 작업

1. Hailo pose metadata를 기존 tracker/B76 GRU 입력 계약에 연결
2. 안전한 현장 ADL 30분과 방향별 연기 낙상으로 Quiet GRU와 rule을 비교
3. GRU active → rule fallback → rule 제거 순서로 실제 경보 경로 전환
4. Pi4와 Pi5 동시 재부팅 후 3분 이내 자동 복구 확인
5. 스피커/부저의 실제 GPIO 또는 USB 오디오 출력을 Pi4 경보 토픽에 연결
6. 두 WebRTC 영상과 AI를 2시간 유지하는 전시 soak test
7. MQTT 익명 접속을 인증 방식으로 전환하고 방화벽 범위를 전시장 LAN으로 제한

낙상은 현재 의료적으로 검증된 판정이 아니라 졸업작품 시연용 위험 징후 MVP다.

## 통합 기록과 재설계 기준

지금까지의 작업 이력, 실제 설정값, 성능 문제와 해결 내역은
[구현 및 설정 통합 기록](IMPLEMENTATION_HISTORY.md)에 모았다. AI Hub 데이터,
Mac mini M4 학습, Hailo-8 추론, Pi5/Pi4 역할 재분배를 포함한 다음 설계 기준은
[자원 제약 기반 시스템 전면 재검토](ARCHITECTURE_REVIEW.md)를 따른다.
2026-10-08 실측, GRU 위험, Pi4 왕복 결과와 Hailo 전 완료 기준은
[Hailo 장착 전 비전·통합 상태](PRE_HAILO_STATUS_2026-10-08.md)에 정리했다.
장착 후 실측과 전환 순서는
[Hailo-8 런타임 기준선과 전환 계획](HAILO_RUNTIME_BASELINE_2026-10-15.md)을 따른다.
Canvas와 네이티브 표시의 차이, 듀얼 HDMI 자원 판단과 구현 게이트는
[네이티브 전시 표시 결정](NATIVE_EXHIBITION_DISPLAY_2026-10-15.md)에 기록했다.
