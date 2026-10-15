# 네이티브 전시 표시 결정

기준일: 2026-10-15

## 결론

Canvas와 카메라/NPU의 하드웨어 OSD는 같은 구현이 아니다. 둘 다 영상과 AI
metadata를 마지막 표시 단계에서 합성한다는 원칙은 같지만, Canvas는 브라우저의
CSS 크기, `object-fit`, device pixel ratio와 탭 상태에 영향을 받는다. 전용 OSD는
고정된 영상 좌표와 하드웨어 compositor를 사용한다.

전시 화면은 Canvas를 사용하지 않는다. 목표 경로는 다음과 같다.

```text
Dahua H.264 -> 저지연 decode -> Hailo pose metadata ----+
                                                    native Wayland/OpenGL
원본 16:9 video -----------------------------------------+-> HDMI-A-2
```

모델이 정사각형 입력을 요구해도 카메라와 출력까지 정사각형일 필요는 없다.
640×640 추론에는 16:9 영상을 letterbox하고, 결과 좌표에서 padding을 제거한 뒤
원본 1920×1080 좌표로 복원하고, 마지막에 고정 1920×1080 viewport로 매핑한다.

## 현재 실측과 병목

| 항목 | 실측 | 판단 |
|---|---:|---|
| Hailo pose HW | 30.80 FPS | NPU 정상 |
| metadata-only | 31.75 FPS | 추론·후처리 정상 |
| 공식 `hailooverlay` 전체 앱 | 6~8 FPS | raw-frame overlay/convert/display 분기 병목 |
| Raspberry Pi OS 데스크톱 유휴 | 약 0.1% CPU, 201 MiB RSS | 현재 핵심 병목 아님 |

설치된 `hailooverlay`는 네이티브 GStreamer 요소지만 raw 프레임에 직접 그린다.
따라서 “브라우저가 아니다”와 “하드웨어 OSD처럼 빠르다”는 같은 뜻이 아니다.
`kmssink`, `waylandsink`, GStreamer GL 요소는 설치돼 있으나 HDMI 연결 상태에서
실제 zero-copy/DMABUF 여부와 FPS를 따로 검증해야 한다.

## 듀얼 HDMI 운영 결정

- `HDMI-A-1`: 관리·얼굴 등록 UI. 필요할 때만 Chromium 한 창을 연다.
- `HDMI-A-2`: Dahua Hailo 결과를 보여주는 네이티브 전체화면.
- 같은 1080p 영상을 두 브라우저에서 중복 재생하지 않는다.
- 기존 `home-safety-demo-display.service` Chromium 자동 실행은 disabled/inactive로 유지한다.

HDMI 출력 두 개를 연결하는 것 자체보다 두 Chromium의 영상 decode/composition과
Cam3 WebRTC용 `libx264`가 더 큰 비용이다. 데스크톱을 완전히 끄면 로컬 얼굴 등록
UI도 사라지므로 지금 `multi-user.target`로 바꾸지 않는다. 필요하면 최종 전시 전에
패널·파일 관리자를 제외한 최소 Wayland compositor/kiosk 세션으로 전환한다.

## 구현 게이트

1. Hailo metadata-only 결과를 기존 tracker/GRU 계약에 연결한다.
2. HDMI-A-2 연결 상태에서 clean video만 `waylandsink`와 `kmssink`로 각각 측정한다.
3. CPU raw-frame burn-in 없이 GL 선·박스·문자 레이어를 합성하는 고정 16:9 renderer를 만든다.
4. Dahua 15 FPS 이상, 표시 지연 300 ms 이하, Vision+MQTT 동시 구동을 합격 기준으로 둔다.
5. 실패하면 `hailooverlay`를 최종 경로로 채택하지 않고, 전시 영상 반복 재생은 예비 데모로만 사용한다.

현재 HDMI-A-1/A-2는 모두 disconnected라 실제 두 화면 부하는 아직 측정하지 않았다.
모니터 연결 뒤 측정 없이 GUI 비활성화나 듀얼 브라우저 구성을 확정하지 않는다.
