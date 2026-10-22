# Pi4 공개 영상 복구와 자동/수동 기기 제어

## 1. 영상 문제의 실제 원인

2026-10-22 같은 Chromium/LAN에서 비교했다.

- `https://vision.aihous.site`: WHEP 201, Dahua 1920×1080 WebRTC 재생.
- `https://www.aihous.site/fall-review`: WHEP 403, 영상 연결 전에 요청 거부.
- Cloudflare connector는 Pi5에서 실행되며 Pi4 `192.168.1.10:8000`으로 전달한다.
- 기존 Pi4 출처 검사기는 loopback만 `X-Forwarded-Proto`를 신뢰했다. Pi5에서
  전달된 HTTPS 요청을 내부 HTTP와 비교하면서 같은 사이트 요청도 거부했다.

해결: loopback 외에 **remote_addr=192.168.1.20 AND Host=www.aihous.site**인
경우만 전달된 http/https scheme을 신뢰한다. 다른 LAN 주소와 임의 Host,
`X-Forwarded-Host`, 다른 Origin은 허용하지 않는다. 이 수정은 모든 출처를
허용하는 CORS/CSRF 해제가 아니며 사용자 인증을 새로 제공하는 것도 아니다.

화면 제목은 `낙상 이벤트 확인`으로 변경했다. Tailscale 설치/연결을 요구하지 않는다.
기존 SSH용 Tailscale 서비스나 Cloudflare 계정 설정은 건드리지 않았다.

### 실제 재생 방식

1. 먼저 동일 출처 WHEP로 WebRTC를 연결한다. 미디어는 Pi5와 브라우저 사이에 흐른다.
2. ICE 실패, 연결 시간 초과 또는 디코드 정지 시 peer를 닫는다.
3. 브라우저가 **직접** `https://vision.aihous.site/stream/dahua?overlay=false`를
   열어 Cloudflare HTTPS 원본 MJPEG로 복귀한다. Pi4가 JPEG 영상을 중계하지 않는다.
4. 화면에 `WebRTC` / `HTTPS 원본 영상 · MJPEG`를 실제 방식대로 구분한다.
5. 페이지 숨김/닫기 때 두 재생 방식 모두 정리한다. 수동 재연결로 WebRTC를 다시 시도한다.

외부 인터넷에서 모든 경우에 순수 WebRTC가 되는 것은 아니다. Cloudflare의 HTTP
터널은 WebRTC의 별도 ICE 미디어 채널 자체를 TURN처럼 중계하지 않는다.
이번 구현은 기존 Pi5 화면과 같은 **WebRTC 우선 + HTTP 영상 복귀** 방식이다.
TURN/유료 서비스/새 포트포워딩은 추가하지 않았다. MJPEG 복귀는 대역폭 비용이 있고,
인터넷 지연이나 카메라/Pi5 장애까지 없애는 보장은 아니다.

공식 근거:
[Cloudflare published application protocols](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/routing-to-tunnel/protocols/),
[MediaMTX WebRTC 연결 경로](https://mediamtx.org/docs/features/webrtc-specific-features).

## 2. 제어 패널

Pi4 메인 대시보드의 차트 아래 `시연 · 기기 제어` 독립 패널을 추가한다.
첨부 HTML/코드는 기능 참고로만 사용하고 기존 협업자 센서 카드와 차트는 유지한다.

| 기기 | 수동 명령 |
|---|---|
| 거실 조명 / 에어컨 | ON / OFF |
| 거실 커튼 | OPEN / CLOSE |
| 화장실 조명 / 환풍기 | ON / OFF |
| 부엌 부저 | ON / OFF, 실제 가스 감지 중 OFF 불가 |

`home/{room}/{device}/set`에 기존 문자열을 발행한다. 기존 collector가 이를
`command_log`에 기록하므로 기존 카드에도 명령이 반영된다. 새로운 DB 스키마,
가짜 온도/습도/센서 데이터, 새로운 얼굴/낙상 모델은 추가하지 않았다.

- 자동 모드: 기존 센서 규칙과 조명 타이머가 동작한다. 수동 명령 API도 거부한다.
- 수동 모드: 생활기기의 센서 자동 명령과 타이머를 서버에서 차단한다. 센서 수집,
  차트, MQTT, DB, 낙상 탐지/스피커는 계속 동작한다.
- 가스 안전 예외: 실제 kitchen gas ON은 계속 경보를 발생시키며 OFF 전환도 처리한다.
  가스가 감지 중이면 수동 부저 OFF는 서버에서도 거부한다. 반복되는 평상시 gas OFF는
  수동 부저 시연을 바로 꺼버리지 않는다.
- 수동으로 보낸 값은 자동화 엔진 내부 상태에도 반영한다. 자동 복귀 뒤 예전
  light_on/aircon_on/curtain_open 등을 바탕으로 잘못 판단하지 않게 한다.
  수동 중에도 presence/door의 ON→OFF 같은 입력 상태는 관찰하며, 자동 출력만 막는다.
  자동으로 돌아갔을 때 이미 닫힌 문/사라진 재실 상태가 예전 값으로 남지 않게 한다.
- 버튼 성공은 MQTT QoS 1 전달 확인이지 실제 릴레이/모터 동작 완료 ACK가 아니다.
  UI에도 `마지막 명령`으로 표시한다.

## 3. 충돌 방지와 자원

`/run/smarthome-control`은 systemd가 pi 소유 0700으로 만드는 tmpfs 디렉터리다.
`state.lock`의 배타 flock을 웹 요청/자동화 MQTT callback/타이머가 공유한다.
모드 확인과 명령 발행이 같은 잠금 안에서 실행되므로 전환 중 서로 다른 명령을
같이 발행하지 않는다. 이전에 이미 브로커/기기에 전달된 명령을 소급 취소하지는 않는다.

- state.json: 모드, 모드 revision, 최대 7기기 마지막 명령, 가스 상태, 엔진 heartbeat.
- 32 KiB 상한, atomic replace, 잠금 대기 최대 3초. 센서 주기마다 SD에 쓰지 않는다.
- UI와 다른 사용자가 동시에 전환하면 revision 불일치 요청은 409로 거부한다.
- 엔진 연결/15초 heartbeat가 없으면 제어 비활성화. MQTT 전달 실패를 성공으로 표시하지 않는다.
- 모드는 브라우저 종료/웹 재시작/자동화 재시작에도 유지된다. Pi4 재부팅 후에는
  tmpfs가 새로 생성되므로 기본 자동 모드다. 잘못된 상태 파일은 fail-closed로 명령 보류.
- 웹 POST: 같은 출처, JSON, 최대 2 KiB, 250ms 클릭 간격, 허용 기기/값만 허용.
  공개 주소의 사용자 인증은 여전히 기존 Cloudflare 접근 정책에 달려 있다.

이 장치는 실제 기기 제어 요청이다. 버튼 확인을 위해 무조건 모든 기기를 켰다 끄지 않는다.
자동차단 회귀 테스트와 브라우저 버튼 테스트는 가짜 MQTT/HTTP로 실행한다.

## 4. 파일과 적용 범위

정식 추가 소스는 `pi4/integrations/`:

- `control_state.py`: 양쪽 프로세스의 공유 상태·잠금·허용 목록.
- `control_gate.py`: 협업자 자동화 callback/타이머/명령의 최소 가드.
- `device_control.py`, `device_control.js`: Flask API와 격리된 Shadow DOM 패널.
- `device-control-hooks.patch`: 기존 app/index/automation에 추가하는 최소 후크.
- `automation-control-runtime.conf`: systemd RuntimeDirectory drop-in.

Pi4 배포 위치:

- `/opt/smarthome/web/{device_control.py,device_control.js,control_state.py}`
- `/opt/smarthome/backend/{control_gate.py,control_state.py}`
- `/etc/systemd/system/automation.service.d/control-runtime.conf`
- 기존 app.py에 install 2줄, index.html에 script 1줄.
- automation.py의 센서 임계값/규칙 본문은 그대로 두고 명령·callback·타이머만 가드한다.

배포 전 원본과 Git reference 차이를 확인하고 `git apply --check`로 후크를 검증한다.
원본 3개와 이전 알림 모듈은 runtime의 고유 백업 디렉터리에 보존한다.
`automation.service`, `web.service`만 재시작한다. 8081/DB/collector/낙상 경보 서비스는
그대로 유지한다. 원본→reference 자동 동기화 후 Pi4 커밋·푸시, Pi5 pull 순서를 지킨다.

원복 시 백업한 automation/app/index와 이전 알림 파일을 복원하고 두 서비스만
재시작한다. 새 모듈 파일이 남아 있어도 후크가 없으면 로드되지 않는다. RuntimeDirectory
drop-in은 코드 원복 후 제거할 수 있으나 다른 서비스/데이터를 지우지 않는다.

## 5. 테스트

- `tests/test_device_control.py`: 서버 모드 강제, 센서/타이머 차단, 수동 상태 반영,
  가스 우선, 동시 요청 직렬화, 오래된 revision/heartbeat 거부, 크기/허용 목록,
  QoS ACK, 실제 협업자 규칙에 최소 패치를 적용한 모의 실행.
- `tests/test_fall_review.py`: 지정한 Pi5 connector만 전달 scheme 신뢰.
- `tests/browser_fall_review_check.py`: 실제 WebRTC, 강제 디코드 정지 시 공개 원본
  MJPEG, 50건 기록과 새 탭, 숨김/복귀. 브라우저용 사건만 주입하며 실제 낙상 발행 없음.
- `tests/browser_device_control_check.py`: 자동/수동 UI, 6기기 버튼, 가스 예외,
  엔진 오프라인, 작은 화면. 실제 제어 API 대신 시험 응답을 사용한다.

### 배포 검증 (2026-10-22 16:22 이후)

- 원본 백업: Pi4 `/home/pi/Home-Safety-System/runtime/device-control-backup.Xwnn1L`.
- 전체 Python 회귀 **120개 통과**. 실제 원본 규칙에 후크를 붙인 모의 실행 포함.
- 공개 `https://www.aihous.site/fall-review`에서 WHEP 201, 원격 후보
  `192.168.1.20:8189 UDP host`, WebRTC 재생 확인. 강제 정지 시 공개 원본
  HTTPS MJPEG 전환 및 새 탭/50건 목록 회귀 테스트 통과.
- `https://www.aihous.site`에서 제어 패널 브라우저 시험 통과(기기 명령 API는
  시험 응답으로 대체). 일반 브라우저의 실제 `/api/control-mode` GET/POST 200도 확인.
  사용자가 이미 수동 모드를 사용 중이어서 실제 검증 요청은 **현재 모드를 그대로
  다시 설정하는 멱등 요청**만 보내고 선택을 강제로 바꾸지 않았다.
- 별도 Python urllib의 공개 URL 요청은 Cloudflare 403을 받아 중단됐다.
  이것을 모드 전환 성공으로 계산하지 않는다. 일반 Chromium 요청은 200이며
  Cloudflare 보안 정책을 완화하지 않았다.
- 사용자 조작으로 생성된 manual 마지막 명령과 이후 auto 복귀 명령이 실제 상태
  API에 나타나는 것을 확인했다. 물리 릴레이/모터의 작동 여부를 직접 확인한 것은 아니다.
- web/automation/collector/audio/sync timer 모두 active. Pi5 두 카메라 online,
  MQTT 연결/거부 0, 확인 시 Hailo 13.04 FPS. 모델·15 FPS 입력 계약 미변경.
- `runtime/pi4-manual-controls-verified.png`에 실제 패널 화면을 보관했다(Git 제외).
