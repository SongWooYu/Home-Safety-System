# Pi4 연동 시험 · 이벤트 캡처 · WebRTC 우선 재생

2026-10-22, Pi5 `/home/pi/Home-Safety-System`, Pi4 동일 저장소.

## 적용 범위

- Pi5: `http://192.168.1.20:8080` 개발·시연 화면.
- Pi4: `http://192.168.1.10:8000` 협업자 화면의 **독립 낙상 알림 모듈만** 확장.
- Pi4 8081은 계속 닫혀 있다. 중복 DB/실패 수집기도 다시 실행하지 않았다.
- 협업자 `/opt/smarthome`의 센서·차트·DB 기능과 자동 동기화 timer를 유지한다.
- Hailo YOLOv8s-Pose + EdgeFall v6 모델, 입력 단위, 15 FPS 시간 계약, 임계값은 그대로다.
- 앞선 탭·얼굴 등록 품질 검사·테마·Tailscale 변경도 이번 Git 동기화에 포함했다.

## 사용 방법

1. Pi5 화면을 새로고침하고 실시간 모니터 탭으로 간다.
2. 스피커 음성 시험 아래 `낙상 단계별 MQTT 시험`을 사용한다.
3. `1 · 의심 보내기` → `2 · 확정 / 경보` → `3 · 시험 해제`.
   각 버튼은 단독 시험도 허용한다. 확정 버튼은 실제 스피커 경보를 활성화한다.
4. 아래 `Pi4 수신` 문구에서 수신된 단계와 전체 경보 상태를 확인한다.
5. Pi4 8000 화면에 `[시험] 낙상 감지` 알림이 뜨면 `발생 당시 캡처 확인`을 누른다.
6. 영상의 관절/얼굴 박스가 필요하면 `영상 재생 → 오버레이 확인 · MJPEG`를 선택한다.

시험은 AI가 낙상을 인식했다고 속여 표시하지 않는다. 실제 모델 상단 판정은 그대로고,
감지 기록에는 `[시험]` 접두사가 붙는다. Pi4 팝업 닫기는 알림만 숨기며 경보를 취소하지 않는다.
시험 경보는 해제 버튼 또는 **Pi4에서 실행하는 30초 타이머**로 해제한다.
Pi5 연결이 끊기거나 브라우저를 닫아도 Pi4 자동화가 실행 중이면 타이머는 동작한다.

## MQTT 계약과 안전한 시험 구분

기존 `home/vision/events`, QoS 1, retain=false를 그대로 사용한다.

| 버튼 | event_type | Pi4 시험 카메라 상태 | 소리/팝업 |
|---|---|---|---|
| 의심 | fall_suspected | suspected | 없음, 수신 상태에 표시 |
| 확정 | fall_confirmed | confirmed | 경보/TTS 및 독립 알림 |
| 시험 해제 | fall_cleared | normal | 시험 경보 해제 |

시험 payload는 `camera_id=manual-test`, `details.test=true`,
`details.backend=manual_demo`, `details.source_camera_id=dahua`로 구분한다.
실제 감지는 계속 `camera_id=dahua`, `backend=hailo_edgefall`이다.
시험 해제·만료는 Dahua 등 다른 카메라의 confirmed 상태를 지우지 않는다.
다른 실제 경보가 있으면 전체 상태는 alarm을 유지한다.

Pi5의 POST `/api/fall-test`는 같은 출처 JSON 요청만 받고 0.75초 간격으로 제한한다.
관리 키는 요구하지 않는다. 이는 CSRF 완화이지 사용자 인증을 대체하는 보안 장치는 아니다.
외부 공개 범위/접근 제어는 기존 정책을 따른다.

브로커 전달 확인과 Pi4 처리 확인은 구분한다.

- 버튼 응답: QoS 1 publish ACK, 최대 2초 대기.
- 실제 수신: Pi5가 `home/safety/fall/state`를 구독해 단계·event_id·수신 시각을 표시.
- 상태의 retained 값은 과거 마지막 상태일 수 있어 `(마지막 수신)`과 시각을 함께 표시.
- 오래된 시험 메시지가 재연결 후 울리지 않도록 Pi4는 timestamp가 10초 초과인
  manual-test 메시지와 retained 이벤트/명령을 무시한다.
- MQTT 발행 대기열 256, 최근 이벤트 100이라는 기존 한도는 유지한다.

## 캡처: MQTT는 메타데이터, HTTP는 사진 한 장

MQTT도 바이너리 payload 전송이 가능하다. 이 구현은 큰 JPEG를 모든 구독자에게
뿌리지 않고 이벤트 식별자·캡처 메타데이터만 MQTT로 전달한다.

1. 실제/시험 `fall_confirmed` 생성 시 Dahua의 **최신 분석 프레임과 해당 관절 결과**를
   함께 사용해 박스·관절 JPEG로 한 번 인코딩한다. 최대 너비 960px, 품질 75다.
   실제 감지는 판정에 사용한 프레임, 시험 버튼은 최근 분석 프레임을 사용한다.
2. 카메라 화면을 열지 않아도 캡처한다. 2초 이상 오래된 프레임은 저장하지 않는다.
3. `details.snapshot.id`는 해당 이벤트의 무작위 32자리 ID다. 크기, 프레임 age,
   `kind=analyzed_frame_pose_overlay`, frame_seq, pose_frame_matched, 박스·관절 개수,
   유효기간도 기록한다. MQTT에 이미지 본문은 없다.
4. Pi4 알림 클릭 → Pi4 동일 출처 HTTP → Pi5 이미지 API → JPEG 한 장 반환.
5. 브라우저에서 Pi5 내부 주소에 직접 접근할 필요가 없고, Pi4 HTTPS 페이지에서도
   혼합 콘텐츠 문제가 없다. Pi4가 실시간 영상을 중계하는 방식은 아니다.

API:

```text
Pi5 GET /api/events/<event_id>/snapshot.jpg
Pi4 GET /api/fall-notices/<event_id>/snapshot.jpg
```

Pi4는 자신이 수신한 이벤트 ID만 허용한다. 고정 Pi5 주소의 고정 경로만 요청하며
MQTT에 담긴 임의 URL을 열지 않는다. 리디렉션 금지, 3초 제한, JPEG 검사,
512 KB 상한, no-store를 적용한다.

### 저장 범위와 한계

- Pi5 메모리 최대 50장, 장당 512 KB 이하(상한 약 25.6 MB), 1시간 후 조회 불가.
  만료 정리는 저장/조회 시 실행된다. 재시작 시 모두 사라진다.
- SD에 영상이나 얼굴 사진을 상시 저장하지 않는다. Git에도 캡처는 올리지 않는다.
- 캡처 실패가 실제 경보 발행을 막지 않는다. 캡처가 없으면 Pi4 버튼도 없다.
- 낙상 **시작 순간**을 찾는 전후 동영상 증거는 아니다. 후속 수정부터 실제 확정은
  해당 판정에 사용한 분석 프레임에 그 프레임의 박스·관절을 표시한다.
  2초 이내 분석 결과가 없으면 새 원본 한 장에 `POSE UNAVAILABLE`을 표시한다.
  오래된 관절을 최신 영상에 얹거나 없는 관절을 만들어 그리지 않는다.
- Pi4 알림 큐는 메모리 최근 50건, 팝업 신규 표시는 최근 수신 30초 내 확정만이다.
  과거 전체 사건 목록/DB 영구 보존은 이번 범위에 없다.
- Pi5 최근 감지 기록에서도 캡처를 열 수 있다.
- 이 기능은 예전 `영상 저장 없음` 진단 문구와 구분된다. 진단 JSONL에는 여전히
  영상이 없으며, **이벤트 캡처만 위 조건으로 임시 보관**한다.

## WebRTC 경로와 복귀

```text
Dahua H.264 → MediaMTX dahuaclean → 브라우저 WebRTC
Cam3 최신 clean MJPEG → 필요 시 FFmpeg H.264 → MediaMTX cam3 → 브라우저

브라우저 ↔ Pi5 Flask /api/webrtc/<camera>/whep ↔ localhost:8889
  위 HTTP 경로는 SDP/세션 생성·삭제만 전달. 영상은 ICE 연결로 흐름.

실패/정지 → 기존 /stream/<camera> MJPEG (오버레이 포함)
```

- Dahua는 기존 H.264를 재인코딩하지 않는다. 검증 시 1920×1080 수신.
- Cam3는 기존 on-demand FFmpeg 경로를 재사용한다. 검증 시 640×360 수신.
  하드웨어 인코딩/zero-copy로 바뀐 것은 아니며 시청 시 CPU 비용이 있다.
- WebRTC 원본에는 픽셀 박스를 굽지 않는다. AI 상태/경보 배너는 계속 갱신한다.
  박스 확인은 선택 가능한 기존 MJPEG로 제공하며 canvas를 추가하지 않았다.
- 얼굴 등록 탭은 기존 거울 MJPEG를 유지한다.
- WebRTC 시작 제한 12초, 재생 프레임 정지 약 5초 + 검사 주기 1.5초 이내에 복귀한다.
- 탭 전환·페이지 숨김·페이지 종료 시 peer, video, 타이머와 MJPEG 연결을 정리한다.
  늦게 완료된 WHEP 세션도 DELETE한다. Cam3 인코더는 MediaMTX 기존 10초 유예 후 종료.
- `webrtcAdditionalHosts`에 Pi5 Tailscale 주소 `100.100.207.97`을 포함했다.
- Cloudflare HTTPS에서도 동일 출처 SDP 요청을 쓴다. 다만 HTTP 터널만으로
  WebRTC 미디어 경로가 열리는 것은 아니다. LAN/Tailscale ICE 경로가 없으면
  MJPEG로 복귀한다. 이번 변경에 TURN 서버를 새로 설치하지 않았다.
- 카메라/Pi5 자체가 끊긴 경우까지 끊김 없는 재생을 보장하지 않는다.

공식 참고: [MediaMTX WebRTC 연결·코덱 제약](https://mediamtx.org/docs/features/webrtc-specific-features),
[MediaMTX 스트림 제공 방식](https://mediamtx.org/docs/features/publish-and-read).

## 화면 높이와 검증

상태 제목, 설명, 분석 조건을 일정 높이로 예약하고 긴 내용은 해당 영역 안에서
스크롤한다. 실제 경보의 강조 색은 유지한다. 새 감지 기록/연결 경고는 페이지를
밀어내지 않는 떠 있는 알림으로 표시한다.

검증:

- Python unittest: 신규 시험/캡처/프록시/타이머/보안/격리 회귀 테스트 포함.
- `tests/browser_transport_check.py`: 실제 Chromium 두 WebRTC 재생,
  강제 HTTP 실패 및 디코드 정지 후 MJPEG 복귀, 오버레이 수동 선택,
  탭 전환 연결 해제, 1440/780/390px에서 상태 변경 전후 아래 영역 좌표 동일.
- 14:55:32 Pi4 의심 수신 → 14:56:02 시험 타이머 자동 해제 로그 확인.
- 14:57:05 Pi5 확정 버튼 → Pi4 `alarm` 수신 및 스피커 활성 로그.
- 실제 Pi4 페이지에서 `[시험]` 팝업 및 960×540 JPEG 표시 확인.
- 14:57:07 시험 해제 → Pi4 `normal` 및 스피커 정지 로그 확인.
- Hailo 확인 시 13.59 FPS, 카메라 약 15 FPS, MQTT 발행 거부 0.
  이는 순간 상태이며 전체 영상 지연/장기 안정성/현장 청취 확인을 대신하지 않는다.
- DB/센서 협업 서비스, sync timer 정상. 8081 listener 없음.

## Git 순서와 재배포

이번에는 Pi4 미커밋 협업 사본부터 원본과 해시를 대조해 커밋·푸시했다.
그 다음 Pi5 변경을 커밋하고 Pi4 커밋을 일반 merge해 푸시했다. force push,
강제 reset, 협업자 작업 덮어쓰기는 사용하지 않았다.

후속 변경은 Pi5 커밋·푸시 → Pi4 `pull --ff-only` → 해당 모듈 배포 → 자동 동기화
사본 검증·Pi4 커밋·푸시 → Pi5 `pull --ff-only` 순서로 처리했다.

안전한 운영 원칙:

1. 양쪽 `git status`와 원격 fetch를 먼저 확인한다. dirty 상태에서 무조건 pull하지 않는다.
2. 수정한 장비에서 변경 범위를 명시해 커밋한 후 원격 변경을 통합하고 push한다.
3. 다른 장비에서 `git pull --ff-only`. 실패하면 이력을 검토하고 일반 merge한다.
4. `/opt/smarthome`은 원본이다. reference를 원본으로 자동 역덮어쓰기하지 않는다.
5. 이번 Pi4 배포는 `pi4/integrations/fall_notice.*`만 원본의 해당 파일에 복사했다.
   Python 모듈 변경 시 `web.service`만 재시작한다.
6. 전용 경보 컨테이너만 `docker compose build automation` 및
   `docker compose up -d --no-deps automation`으로 갱신한다. 전체 installer는 실행하지 않는다.
7. runtime 모델, 얼굴 DB, .env, 캡처, 실제 장비 데이터는 장비별 독립 관리한다.

수정 파일은 `src/smarthome_vision/{fall_demo,evidence,webrtc,events,pipeline,app}.py`,
`static/{stream-player,fall-test,dashboard}.js`, `static/workspace.css`,
`templates/index.html`, `pi4/backend/automation.py`, `pi4/integrations/fall_notice.*`다.

## 15시 후속: WebRTC 원본 안내와 캡처 오버레이

WebRTC는 박스·관절을 금지하는 방식이 아니다. 현재 Dahua 경로가 **카메라 원본 H.264
그대로 전달**이므로 Pi5가 생성한 관절 그림이 영상 픽셀에 포함되지 않는 것이다.
오버레이를 구운 영상도 WebRTC로 보낼 수 있으나, 현재 시스템에서는 영상 합성과
H.264 재인코딩 경로를 추가해야 한다. 그 비용을 이번에 몰래 추가하지 않았다.
UI에 `WebRTC 원본 · 박스 OFF / AI 분석 ON`을 명시하고,
실시간 박스는 기존 `오버레이 확인 · 박스·관절·이름 (MJPEG)` 선택으로 유지했다.

이벤트 캡처 변경:

- 분석 스레드는 `(분석 프레임, pose 목록, 프레임 번호, 수신 시각)`을 한 쌍만 유지.
  프레임 목록을 누적하지 않으며, 별도 재추론도 하지 않는다.
- 실제 confirmed 생성은 같은 분석 스레드에서 해당 쌍을 캡처한다.
- 자홍색 사람 박스, 주황색 관절선·점. confidence 0.25 미만/화면 밖 관절 제외.
- 이미지 밖 하단 40px에 `FALL CONFIRMED` 또는 `MANUAL TEST - NOT AI FALL`,
  박스·보이는 관절 수, 프레임 번호 표시. 원 영상의 발끝·시계 등을 가리지 않는다.
- 메모리 저장/HTTP 조회 구조는 동일. Pi4 협업자 앱 소스 수정이나 재시작 불필요.
- 기존 깨끗한 캡처는 소급 변환하지 않는다. 이후 발생하는 이벤트부터 적용한다.

검증:

- 전체 unittest 100개 통과. 좌표 축소, 분석/최신 원본 불일치 방지, 오래된 pose,
  사람 없음, 시험 구분, 실제 AI 루프에서 confirmed 직전 프레임 고정까지 검증.
- 15:22 시험에서 분석 frame 726, 프레임 age 50ms, 박스 5개·보이는 관절 51개가
  포함된 960×580 JPEG를 Pi4의 기존 캡처 API로 조회했다.
- 시험 이벤트 경보 해제 확인. 낙상 임계값·Hailo 모델·시간 모델 입력 계약은 변경 없음.
- 15:22의 사람 숫자는 테스트 당시 검출 결과이며 정확도 평가 수치가 아니다.
