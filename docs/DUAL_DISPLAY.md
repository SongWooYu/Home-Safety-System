# Raspberry Pi 5 듀얼 HDMI 전시 화면

> **2026-10-15 전환 안내:** 이 문서의 HDMI-A-2 Chromium 자동 실행 방식은 현재 `disabled/inactive`이며 최종 전시안이 아니다. HDMI-A-1 관리 UI와 HDMI-A-2 네이티브 Wayland/OpenGL 화면으로 전환하는 최신 결정은 [네이티브 전시 표시 결정](NATIVE_EXHIBITION_DISPLAY_2026-10-15.md)을 따른다.


기준일: 2026-09-17

## 목적

- `HDMI-A-1`: 일반 Raspberry Pi OS 데스크톱
- `HDMI-A-2`: Pi5 로컬 `http://127.0.0.1:8080` 3카메라 AI 화면

시연 화면은 네트워크, Pi4, WebRTC를 거치지 않고 Pi5 내부 MJPEG를 사용한다.
따라서 카메라 박스·자세·낙상 상태를 가장 낮은 지연으로 보여준다. MQTT·DB·최종
경보 상태의 기준 서버는 계속 Pi4다.

## 웹 화면을 사용하는 이유

웹이 필수인 것은 아니다. OpenCV, GStreamer 또는 Qt로 네이티브 전체화면을 만들
수도 있다. 현재는 카메라 타일, AI 상태, 이벤트, 얼굴 등록 UI가 이미 한 화면에
있고 마우스 입력과 자동 복구도 구현되어 있으므로 로컬 Chromium이 가장 단순하다.
주소는 `127.0.0.1`이므로 영상이 공유기나 Pi4를 왕복하지 않는다.

## 연결

두 화면을 모두 1920×1080@60Hz로 사용한다.

```text
Pi5 HDMI-A-1 (왼쪽, 0,0)       -> OS 관리 모니터
Pi5 HDMI-A-2 (오른쪽, 1920,0)  -> 전시 모니터
```

`HDMI-A-2`는 연결 대수와 관계없이 항상 전시용이다. `HDMI-A-2` 한 대만 연결해도
로컬 대시보드를 전체화면으로 실행한다. 두 대가 연결되면 `HDMI-A-1`에는 일반
데스크톱을 남기고 `HDMI-A-2`에만 전시 창을 배치한다.

## 설치

데스크톱 사용자 `pi`로 실행한다. `sudo`를 붙이지 않는다.

```bash
cd /home/pi/Home-Safety-System
./scripts/setup_dual_display.sh
```

설치 내용:

- `~/.config/kanshi/config`: 듀얼/단일 HDMI 자동 배치
- `~/.config/labwc/rc.xml`: `HomeSafetyDemo` 창을 HDMI-A-2로 이동 후 전체화면
- `~/.config/systemd/user/home-safety-demo-display.service`: 사용자 로그인 자동 시작
- 별도 Chromium 프로필: `~/.config/chromium-home-safety-demo`
- USB 마우스: 전체화면 대시보드의 얼굴 등록·등록자 관리 조작

기존 kanshi/labwc 설정이 있으면 타임스탬프가 붙은 백업을 먼저 만든다.

## 운영 명령

```bash
systemctl --user status home-safety-demo-display.service
systemctl --user restart home-safety-demo-display.service
systemctl --user stop home-safety-demo-display.service
journalctl --user -u home-safety-demo-display.service -n 100 --no-pager
```

재부팅 뒤 `pi` 사용자의 labwc 데스크톱이 자동 로그인되고 `HDMI-A-2`가 확인되면
로컬 비전 서비스가 준비될 때까지 기다렸다가 시연 창을 연다. Chromium이 종료되면
사용자 서비스가 5초 뒤 다시 실행한다.

## 점검

```bash
XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-0 wlr-randr
curl -s http://127.0.0.1:8080/health
```

기대 결과:

- HDMI-A-2만 연결: position 0,0, 시연 창 전체화면
- 두 화면 연결: HDMI-A-1 position 0,0, HDMI-A-2 position 1920,0
- 두 출력: 1920×1080@60Hz
- HDMI-A-1: 패널과 일반 데스크톱 사용 가능

첫 번째 모니터가 1920×1080을 지원하지 않으면
`config/display/kanshi.config`의 해당 mode와 HDMI-A-2 position을 실제 해상도에
맞게 바꾼 뒤 설치 스크립트를 다시 실행한다.
