# TC-CAM-001 Camera Module 3 인식 테스트

## 목적
Raspberry Pi 5에서 Camera Module 3가 정상 인식되는지 확인한다.

## 테스트 환경
- Board: Raspberry Pi 5 Model B
- Camera: Camera Module 3
- Sensor: IMX708
- OS: Debian GNU/Linux 13 trixie

## 테스트 명령어
```bash
rpicam-hello --list-cameras
