# Home Safety System

Raspberry Pi 5의 Camera Module 3와 Dahua IP 카메라를 AI 비전 파이프라인으로 통합하고,
Raspberry Pi 4가 MQTT·이벤트 저장·경보·최종 화면을 담당하는 졸업작품입니다.

## 현재 구성

- Pi5 `192.168.1.20:8080`: Camera Module 3, Dahua RTSP의 개발용 분석 화면
- Pi4 `192.168.1.10:1883`: MQTT 중앙 브로커
- Pi4 `192.168.1.10:8081`: 최종 안전 상태와 경보 화면; 영상은 브라우저가 Pi5 WebRTC에 직접 연결
- 사람/낙상 입력: Dahua를 Hailo YOLOv8s-Pose로 15 FPS 목표 분석
- 낙상: EdgeFallKit 48-frame temporal MLP + 상태기계가 표준 MQTT 경보 발행
- 얼굴: Camera Module 3에서 YuNet + SFace, 한 번의 자동 다각도 등록, 특징 벡터만 저장

## 문서

- [구현 및 설정 통합 기록](docs/IMPLEMENTATION_HISTORY.md)
- [Hailo YOLOv8 + EdgeFall 운영 전환 보고서](docs/HAILO_EDGEFALL_PRODUCTION_2026-10-19.md)
- [자원 제약 기반 시스템 전면 재검토](docs/ARCHITECTURE_REVIEW.md)
- [현재 프로젝트와 진행 단계](docs/CURRENT_STATE.md)
- [Hailo 장착 전 비전·통합 상태와 완료 기준](docs/PRE_HAILO_STATUS_2026-10-08.md)
- [Pi5 카메라·AI·MQTT 상세](docs/PI5_VISION.md)
- [Pi5→브라우저 WebRTC 설치·성능·장애 대응](docs/WEBRTC_STREAMING.md)
- [Pi5 듀얼 HDMI 전시 화면](docs/DUAL_DISPLAY.md)
- [Canvas 없는 네이티브 전시 표시 결정](docs/NATIVE_EXHIBITION_DISPLAY_2026-10-15.md)
- [얼굴 등록·인식·개인정보](docs/FACE_RECOGNITION.md)
- [Pi4 clone 설치·기존 서버 마이그레이션](docs/PI4_SERVER.md)
- [Pi4 다음 작업 체크리스트](docs/PI4_NEXT_STEPS.md)
- [첨부된 과거 Pi4 문서와 현재 기준의 관계](docs/LEGACY_PI4_REFERENCE.md)
- [시스템 요구사항](docs/SRS.md)

## Pi5 운영

```bash
sudo systemctl status smarthome-vision.service
curl -s http://127.0.0.1:8080/health
journalctl -u smarthome-vision.service -f
```

Dahua URL, MQTT 자격 증명, 얼굴 목록·삭제용 관리 키는 Git에서 제외된 `.env`에 둡니다.
얼굴 모델 최초 설치는 `./scripts/setup_face_models.sh`로 수행합니다.
Hailo YOLOv8s-Pose와 EdgeFall 네이티브 runtime은 upstream 조건을 확인한 뒤 다음처럼
고정 checksum/commit으로 재현합니다.

```bash
./scripts/setup_edgefall_shadow.sh --accept-upstream-license
```

스크립트의 `shadow` 이름은 검증 당시의 역사적 이름이며 생성 결과는 현재 운영
경로에서 사용합니다.

## Pi4 새 설치

```bash
git clone https://github.com/SongWooYu/Home-Safety-System.git
cd Home-Safety-System
sudo ./pi4/scripts/install.sh
```

기존 `/opt/smarthome`이 있는 Pi4에서는 일반 설치가 자동 중단됩니다. DB 백업과
보존 절차를 포함한 다음 명령만 사용합니다.

```bash
sudo ./pi4/scripts/install.sh --migrate-legacy /opt/smarthome
```

자세한 안전 조건과 검증 절차는 먼저 [Pi4 서버 문서](docs/PI4_SERVER.md)를
읽어야 합니다.

## 주의

Pi5 `:8080`은 최종 서비스가 아니라 탐지 과정을 검증하는 개발 화면입니다.
현재 낙상 판단은 의료기기가 아니며 실제 응급 판단을 대신할 수 없습니다.
Mosquitto 익명 접속은 사설 전시장 LAN의 초기 통합용이므로 외부 공개 전에
반드시 인증과 방화벽을 적용해야 합니다.
