# Pi5 AI 영상 WebRTC 전달

기준일: 2026-09-17

## 결정

Pi4가 Pi5의 MJPEG 세 개를 Python/Gunicorn으로 중계하던 경로를 제거했다.
Pi5에서 AI 오버레이까지 끝낸 영상을 H.264로 인코딩하고 MediaMTX가 WebRTC로
전시 브라우저에 직접 보낸다.

```text
카메라 3종 -> Pi5 캡처/AI/오버레이 -> JPEG 최신 프레임
            -> FFmpeg libx264 -> 로컬 RTSP -> MediaMTX
브라우저 <------------------------- WebRTC/ICE ---------------- Pi5
    |-- HTML·상태·경보 API ------------------------------------ Pi4
```

이는 브라우저와 Pi5 MediaMTX 사이의 WebRTC peer 연결이다. 브라우저끼리 연결하는
형태는 아니며, 지연이 0이 되는 것도 아니다. 같은 LAN에서 UDP ICE가 직접
성립하면 MJPEG 프록시보다 지연과 대역폭이 크게 낮아지는 것이 목표다.

## 부하의 의미

- Pi4 백엔드, Docker 네트워크, Gunicorn은 영상 바이트를 처리하지 않는다.
- 브라우저가 PC에서 실행되면 Pi4는 영상 경로에서 완전히 빠진다.
- 브라우저가 Pi4에 연결된 모니터에서 실행되면 Pi4 브라우저는 H.264 수신과
  디코딩을 계속 담당하지만 Python 중계 부하는 사라진다.
- Pi5는 하드웨어 H.264 인코더가 없어서 `libx264` 소프트웨어 인코딩을 담당한다.

2026-09-17 세 스트림 실측:

| 항목 | 값 |
|---|---|
| 영상 | H.264 Constrained Baseline, 640×360, 15 FPS |
| 목표 비트레이트 | 카메라당 1,000 kbit/s, 합계 약 3.0 Mbit/s |
| FFmpeg(세 영상을 볼 때) | 640×360 MJPEG 입력 최적화 후 카메라당 약 7% CPU, 약 60MB RSS |
| MediaMTX | 약 0.5% CPU, 약 46MB RSS |
| 시청자 없음 | FFmpeg 0개; MediaMTX만 상주 |

CPU 값은 Linux 전체 CPU 표기이며 장면 복잡도에 따라 달라진다. Pi5 MJPEG도
640×360, 15 FPS, 품질 70으로 제한한다. 최적화 전 세 MJPEG 합계 약 7.3MB/s가
약 1.4MB/s로 줄어 로컬 대시보드와 WebRTC publisher의 경쟁을 완화했다.

## Pi5 설치

저장소 루트에서 실행한다.

```bash
sudo ./scripts/setup_webrtc.sh
```

스크립트는 arm64용 MediaMTX 1.21.0 공식 릴리스와 체크섬을 내려받아 검증하고,
`smarthome-mediamtx.service` 하나를 설치·활성화한다. 각 카메라 FFmpeg는
MediaMTX `runOnDemand`가 첫 시청 때 시작하고 마지막 시청 종료 10초 뒤 정리한다.


MediaMTX RTSP 입력은 `127.0.0.1:8554`에만 바인딩한다. LAN에는 WebRTC HTTP와
ICE만 노출한다.

## Pi4 반영

Pi4에서 협업 중인 로컬 변경을 먼저 커밋한 뒤 다음을 실행한다.

```bash
cd /home/pi/Home-Safety-System
git pull --ff-only
sudo ./pi4/scripts/install.sh
```

기존 `pi4/.env`는 덮어쓰지 않고 누락된 다음 키만 추가된다.

```dotenv
VISION_API_URL=http://192.168.1.20:8080
WEBRTC_BASE_URL=http://192.168.1.20:8889
WEBRTC_CAMERAS=cam3,webcam,dahua
```

과거 `VISION_BASE_URL`, `VISION_CAMERAS`, `VISION_STREAM_FPS`가 남아 있어도
실행에는 사용되지 않는다. 검증 후 사람이 제거해도 된다.

## 네트워크 포트

| 발신 -> 수신 | 프로토콜/포트 | 용도 |
|---|---|---|
| 브라우저 -> Pi4 | TCP 8081 | 최종 화면과 상태 API |
| Pi4 -> Pi5 | TCP 8080 | 작은 health JSON |
| 브라우저 -> Pi5 | TCP 8889 | WebRTC 플레이어/WHEP signaling |
| 브라우저 <-> Pi5 | UDP 8189 | 우선 ICE 미디어 경로 |
| 브라우저 <-> Pi5 | TCP 8189 | UDP 차단 시 대체 ICE 경로 |
| FFmpeg -> MediaMTX | TCP 8554 loopback | Pi5 내부 RTSP 게시 |

공유기 포트포워딩은 하지 않는다. 전시장 사설 LAN에서만 사용한다.

## 설정 조정

인코딩 기본값은 `/etc/default/smarthome-webrtc`에 있다.

```dotenv
WEBRTC_FPS=15
WEBRTC_WIDTH=640
WEBRTC_HEIGHT=360
WEBRTC_BITRATE_KBPS=1000
```

수정 후:

```bash
sudo systemctl restart smarthome-mediamtx.service
```

현재 1차 시험값은 15 FPS/1,000 kbit/s다. 더 부드럽게 보이게 하려고 FPS·해상도를 동시에
올리면 Pi5 CPU와 대역폭이 함께 증가한다. AI 분석 주기가 영상 FPS보다 느리면
영상 FPS만 높여도 새 탐지 결과가 더 자주 생기는 것은 아니다.

## 검증

```bash
systemctl is-active smarthome-mediamtx.service

for camera_id in cam3 webcam dahua; do
  ffprobe -v error -rtsp_transport tcp -select_streams v:0 \
    -show_entries stream=codec_name,profile,width,height,r_frame_rate \
    -of default=noprint_wrappers=1 \
    "rtsp://127.0.0.1:8554/$camera_id"
done

curl -L -I http://192.168.1.20:8889/cam3
```

브라우저에서 `http://192.168.1.10:8081`을 열고 개발자 도구 Network에서 영상
요청이 Pi4가 아니라 `192.168.1.20:8889`로 가는지 확인한다. 절전·탭 복귀 뒤에는
iframe을 새로 연결하도록 구현되어 있다.

## 장애 확인

영상 세 개가 모두 안 나오면:

```bash
journalctl -u smarthome-mediamtx.service -n 100 --no-pager
ss -lntup | grep -E ':8889|:8189|:8554'
```

- 플레이어 페이지도 안 열림: TCP 8889 또는 MediaMTX 상태 확인
- 페이지는 열리나 영상 없음: publisher와 로컬 RTSP 확인
- 일부 네트워크에서만 실패: UDP 8189 방화벽 확인, TCP 8189 대체 연결 확인
- Pi5가 느려짐: 640×360/8 FPS 유지, 비트레이트를 먼저 낮추고 CPU 온도 확인
- 검은 화면이 탭 복귀 후 지속: Pi4 화면 새로고침 후 브라우저 콘솔과 MediaMTX
  WebRTC 세션 로그 확인

## 보안과 후속 작업

현재 `webrtcAllowOrigins: ["*"]`와 암호화 없는 HTTP는 폐쇄형 전시장 LAN용 MVP다.
인터넷이나 학교 공용망에 직접 노출하지 않는다. 외부 접속이 필요해질 때는 HTTPS,
인증, 제한된 CORS, 방화벽과 TURN/STUN 설계를 별도 적용한다.
