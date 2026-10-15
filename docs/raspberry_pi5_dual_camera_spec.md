# Raspberry Pi 5 듀얼 카메라 사용 검증 사양서

> **Historical hardware note (2026-10-15):** ABKO APC720 has been retired from the active system. Camera Module 3 now performs face enrollment and recognition; ABKO/V4L2 details below are retained only as experiment history.


## 1. 결론

Raspberry Pi 5 + Raspberry Pi OS 환경에서 Raspberry Pi Camera Module 3와 ABKO APC720 USB 웹캠을 모두 정상 인식했다.

ABKO APC720은 uvcvideo 드라이버로 인식되며, 실제 영상 캡처 장치는 /dev/video8이고 /dev/video9는 Metadata Capture 장치이므로 사용하지 않는다. 운영 시에는 /dev/v4l/by-id/usb-SunplusIT_Inc_ABKO_APC720_HD_WEBCAM_N2020120301-video-index0 경로를 사용한다.

USB 웹캠은 MJPG 1280x720 30fps 입력을 지원한다. YUYV 1280x720은 10fps로 제한되므로 720p30 사용 시 반드시 -input_format mjpeg를 지정해야 한다.

ffmpeg에서 -preset ultrafast -tune zerolatency -pix_fmt yuv420p 조건을 적용한 결과, 1280x720 30fps H.264 인코딩이 fps=30, speed=1x로 처리되어 실시간 가능성이 확인되었다.

Camera Module 3는 rpicam-vid 기준 1280x720 30fps H.264 출력이 정상 동작했다.

vcgencmd get_throttled 결과는 throttled=0x0으로, 테스트 시점 기준 저전압 또는 스로틀 이력은 없었다.

Raspberry Pi 5 + Raspberry Pi OS 환경에서 다음 두 카메라 장치는 모두 정상 인식 및 단독 캡처가 확인되었다.

- Raspberry Pi Camera Module 3 / IMX708
- ABKO APC720 HD USB Webcam

다만 현 단계에서 확정 가능한 범위는 “장치 인식 및 단독 캡처 정상”까지이며, “두 카메라 동시 실시간 송출 성능”은 추가 검증이 필요하다.

## 2. 시스템 환경

| 항목 | 내용 |
|---|---|
| 보드 | Raspberry Pi 5 |
| OS | Raspberry Pi OS / Debian trixie 계열 |
| 카메라 1 | Raspberry Pi Camera Module 3, IMX708 |
| 카메라 2 | ABKO APC720 HD WEBCAM |
| USB 웹캠 드라이버 | uvcvideo |
| 주요 도구 | v4l2-ctl, ffmpeg, rpicam-vid, rpicam-hello |

## 3. 장치 매핑

| 장치 | 디바이스 | 판단 |
|---|---|---|
| Camera Module 3 / IMX708 | rpicam / libcamera 경로 | 정상 |
| ABKO APC720 영상 캡처 | /dev/video8 | 사용 대상 |
| ABKO APC720 메타데이터 | /dev/video9 | 영상 입력용 아님 |
| ABKO APC720 고정 경로 | /dev/v4l/by-id/usb-SunplusIT_Inc_ABKO_APC720_HD_WEBCAM_N2020120301-video-index0 | 운영 권장 |

## 4. USB 웹캠 지원 포맷

ABKO APC720은 다음 포맷을 지원한다.

| 포맷 | 해상도 | 프레임 | 판단 |
|---|---:|---:|---|
| MJPG | 1280x720 | 30fps | 권장 |
| YUYV | 1280x720 | 10fps | 비권장 |
| MJPG | 640x480 | 30fps | 가능 |
| YUYV | 640x480 | 30fps | 가능 |

운영 시 720p 30fps를 사용하려면 반드시 다음 입력 포맷을 지정해야 한다.

```bash
-input_format mjpeg
```

포맷을 지정하지 않으면 ffmpeg가 기본적으로 YUYV를 선택할 수 있으며, 이 경우 1280x720에서 10fps로 하향된다.

## 5. 검증된 명령

### 5.1 USB 웹캠 720p30 MJPEG 입력 테스트

```bash
ffmpeg -y \
  -f v4l2 \
  -input_format mjpeg \
  -framerate 30 \
  -video_size 1280x720 \
  -i /dev/v4l/by-id/usb-SunplusIT_Inc_ABKO_APC720_HD_WEBCAM_N2020120301-video-index0 \
  -t 10 \
  usbcam_mjpg_720p30.mp4
```

확인 결과:

- 입력 스트림: MJPEG
- 입력 해상도: 1280x720
- 입력 프레임: 30fps
- 출력 코덱: H.264 / libx264
- 최종 생성 프레임: 약 297 frames / 10초
- 출력 처리 속도: 약 0.8x
- 실측 인코딩 처리 fps: 약 24fps

판단:

- USB 웹캠 입력 자체는 720p30으로 정상.
- ffmpeg + libx264 소프트웨어 재인코딩은 720p30 실시간 처리에 약간 부족.
- 실시간 송출 목적이면 재인코딩 부하를 줄이거나, MJPEG를 그대로 송출하거나, 해상도/프레임/프리셋을 낮추는 것이 필요.

### 5.2 Camera Module 3 720p30 녹화 테스트

```bash
rpicam-vid -t 10000 \
  --width 1280 \
  --height 720 \
  --framerate 30 \
  --codec h264 \
  -o cam3_test.h264
```

확인 결과:

- 출력: H.264
- 해상도: 1280x720
- 프레임: 30fps
- 동작 상태: 정상

## 6. 현재 부하 상태

top 출력 기준:

| 항목 | 값 |
|---|---:|
| CPU idle | 약 99.5% |
| 사용 메모리 | 약 1.3GB / 8GB |
| Swap 사용 | 0MB |
| Zombie process | 0 |

판단:

- 시스템 기본 상태는 매우 여유 있음.
- 다만 해당 top 출력은 카메라 인코딩/송출 작업이 실제로 실행 중인 순간의 부하로 보기 어렵다.
- 따라서 동시 송출 부하 확정 자료로는 부족하다.

## 7. 운영 권장안

### 7.1 안정 우선 구조

| 카메라 | 입력 | 처리 | 권장 |
|---|---|---|---|
| Camera Module 3 | rpicam / libcamera | 1280x720 30fps | 별도 프로세스 |
| ABKO APC720 | V4L2 MJPEG | 1280x720 30fps | by-id 경로 사용 |

### 7.2 USB 웹캠 권장 입력 경로

```bash
/dev/v4l/by-id/usb-SunplusIT_Inc_ABKO_APC720_HD_WEBCAM_N2020120301-video-index0
```

`/dev/video8`도 현재는 동작하지만, 재부팅이나 장치 추가 시 번호가 바뀔 수 있으므로 운영 코드에는 by-id 경로를 사용한다.

### 7.3 피해야 할 경로

```bash
/dev/video9
```

해당 장치는 Metadata Capture 전용이므로 영상 입력 장치로 사용하지 않는다.

## 8. 실시간 송출 시 주의사항

### 8.1 USB 웹캠

720p30 MJPEG 입력은 가능하지만, 이를 H.264로 재인코딩할 경우 현재 테스트에서는 약 0.8x 속도로 나타났다. 실시간성 확보를 위해 다음 중 하나를 선택해야 한다.

1. MJPEG를 그대로 송출
2. 640x480 또는 640x360으로 낮춤
3. 프레임을 15fps 또는 20fps로 낮춤
4. libx264 preset을 ultrafast로 변경
5. bitrate와 GOP를 제한
6. 두 카메라 동시 사용 시 각각 별도 프로세스로 분리

### 8.2 Camera Module 3

Camera Module 3는 rpicam-vid 기준 720p30 출력이 정상으로 확인되었다. 다만 USB 웹캠과 동시에 송출할 경우 전체 CPU 부하, 저장장치 I/O, 네트워크 대역폭 검증이 필요하다.

## 9. 추가 검증 필요 항목

최종 양산/운영 사양으로 확정하려면 다음 항목을 추가 확인해야 한다.

| 항목 | 확인 명령/방법 | 목적 |
|---|---|---|
| 동시 구동 부하 | 두 카메라 명령 동시 실행 후 top/htop | CPU 여유 확인 |
| 스로틀 여부 | vcgencmd get_throttled | 전원/발열 문제 확인 |
| 파일 생성 정상성 | ffprobe 출력 확인 | 코덱/프레임/시간 확인 |
| 장시간 안정성 | 30분 이상 연속 구동 | 메모리 누수/드롭 확인 |
| 네트워크 송출 | RTSP/WebRTC/HLS 테스트 | 실제 서비스 구조 검증 |

## 10. 권장 추가 테스트 명령

### 10.1 전원/스로틀 확인

```bash
vcgencmd get_throttled
```

정상 기대값:

```text
throttled=0x0
```

### 10.2 USB 웹캠 파일 분석

```bash
ffprobe -hide_banner usbcam_mjpg_720p30.mp4
```

### 10.3 Camera Module 3 파일 분석

```bash
ffprobe -hide_banner cam3_test.h264
```

### 10.4 실시간 부담 완화 USB 웹캠 명령

```bash
ffmpeg -y \
  -f v4l2 \
  -input_format mjpeg \
  -framerate 30 \
  -video_size 1280x720 \
  -i /dev/v4l/by-id/usb-SunplusIT_Inc_ABKO_APC720_HD_WEBCAM_N2020120301-video-index0 \
  -t 10 \
  -c:v libx264 \
  -preset ultrafast \
  -tune zerolatency \
  -pix_fmt yuv420p \
  usbcam_720p30_ultrafast.mp4
```

## 11. 최종 판정

| 구분 | 판정 |
|---|---|
| 장치 인식 | 완료 |
| USB 웹캠 영상 노드 식별 | 완료 |
| USB 웹캠 720p30 입력 | 완료 |
| Camera Module 3 720p30 녹화 | 완료 |
| by-id 고정 경로 확인 | 완료 |
| USB 웹캠 H.264 실시간 인코딩 | 약간 부족, 추가 최적화 필요 |
| 두 카메라 동시 송출 성능 | 추가 검증 필요 |
| 현재 단계 활용 가능성 | 개발/검증용 사양서로 사용 가능 |

## 12. 요약

현재 장비 구성은 듀얼 카메라 시스템으로 사용할 수 있다. USB 웹캠은 `/dev/video8` 또는 by-id `video-index0`을 사용해야 하며, 720p30 사용 시 `MJPG` 입력 포맷 지정이 필수이다. Camera Module 3는 `rpicam-vid` 기준 720p30 동작이 정상이다.

단, USB 웹캠을 H.264로 소프트웨어 재인코딩하면 720p30 실시간 처리에는 약간 부족한 것으로 보인다. 실시간 동시 송출 시스템으로 확정하려면 MJPEG 패스스루, 해상도/프레임 조정, x264 ultrafast 적용, 장시간 동시 구동 테스트가 필요하다.
