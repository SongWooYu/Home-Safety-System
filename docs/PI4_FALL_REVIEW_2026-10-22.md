# Pi4 사건 캡처 · 최근 50건 · 현재 WebRTC 확인

## 사용자 경로

- 협업자 대시보드: `http://192.168.1.10:8000`
- 독립 사건 확인 화면: `http://192.168.1.10:8000/fall-review`
- 특정 사건: `/fall-review?event=<event_id>`
- 대시보드 오른쪽 아래 `낙상 기록 · 현재 영상`으로 항상 접근 가능하다.
- 낙상 알림의 캡처 사진 또는 `이 사건 · 현재 영상 확인`을 누르면 새 탭에서
  해당 사건을 선택한다. `target=_blank`, `rel=noopener`를 사용한다.

왼쪽은 **발생 당시 고정 사진**, 오른쪽은 **현재 Dahua 영상**이다.
사진에는 당시 박스·관절이 들어가지만 현재 WebRTC는 원본 H.264이므로 박스·관절이 없다.
모델이나 추론 FPS, 얼굴 등록, Pi4 경보 제어는 변경하지 않았다.

## 기록/사진은 서로 다른 보관 한도

| 항목 | 저장 위치 | 한도 및 삭제 |
|---|---|---|
| 낙상 확정 사건 메타데이터 | Pi4 `FallNotices.events` | 메모리 최근 50건, 51번째부터 오래된 순서 삭제, 웹 서비스 재시작 시 초기화 |
| 발생 당시 박스·관절 JPEG | Pi5 `EvidenceStore` | 최대 50장, 장당 512 KB, 1시간 만료, 비전 서비스 재시작 시 초기화 |
| 현재 영상 | 브라우저 WebRTC | 저장하지 않음, 페이지 숨김/종료 시 peer 해제 |
| 브라우저 사진 | 선택한 한 장의 blob | 선택 변경 시 요청 취소 및 object URL 해제 |

기록 목록은 **실제 `fall_confirmed`와 수동 확정 시험**을 함께 보관한다.
의심/해제 메시지를 또 쌓아 50건을 소비하지 않는다. 따라서 확정 사건 목록이지
모든 상태 전이 로그는 아니다. 실제 AI/수동 시험 필터와 시험 안내를 제공한다.
새 사건은 목록만 갱신하고 사용자가 보고 있던 과거 사건을 다른 사건으로 바꾸지 않는다.
선택된 사건이 삭제되면 삭제 안내를 보여주며, 다른 사건 사진으로 대체하지 않는다.

팝업은 여전히 최근 수신 30초 내 확정만 표시한다. 새 기록 API는 30초가 지나도
메모리에 남은 50건을 반환한다. MQTT 재연결 후 오래된 경보를 다시 띄우지 않으며
retained 이벤트, 120초보다 오래된 이벤트, 중복 ID는 기존 정책대로 제외한다.
사진이 만료/삭제/연결 실패하면 사건 시각은 유지하되 사진 조회 불가를 명시한다.
DB/SD 영구 저장이나 과거 영상 녹화 기능은 추가하지 않았다.

## 전송 경로

```text
이벤트: Pi5 → MQTT home/vision/events → Pi4의 최근 50건 목록
사진:   브라우저 → Pi4 알려진 사건 ID 조회 → Pi5 JPEG 한 장
연결:   브라우저 → Pi4 WHEP 신호 프록시 → Pi5 MediaMTX :8889
영상:   Dahua H.264 → Pi5 MediaMTX :8189 ↔ 접속자 브라우저
```

Pi4에는 실시간 영상 decode/encode, RTSP 입력, MJPEG 프록시를 추가하지 않았다.
Pi4의 SDP 요청은 고정 `http://192.168.1.20:8889/dahuaclean/whep`만 사용하며
요청/응답 128 KiB, 타임아웃 8초, 리디렉션 금지, 같은 출처 검사와 session ID
검증을 적용한다. 임의 URL/카메라 경로를 지정할 수 없다. MediaMTX Location은
Pi4의 상대 경로로 변환하여 브라우저가 내부 HTTP에 SDP를 직접 전송하지 않게 한다.
이미 종료된 peer의 DELETE 404는 멱등 성공 204로 처리한다.

MediaMTX의 UDP/TCP 8189 후보는 Pi5 LAN `192.168.1.20`, Tailscale
`100.100.207.97`을 포함한다. Pi4 페이지를 제공하는 HTTP 연결과 영상 ICE 연결은
별개다. Cloudflare HTTP 터널만으로 외부 영상 전달을 보장하지 않는다.
외부 브라우저는 Pi5와 연결 가능한 Tailscale 등 경로가 필요하다. TURN은 추가하지 않았다.

브라우저는 하나의 peer만 사용한다. 사건을 바꿔도 영상을 다시 열지 않는다.
초기 연결 14초 제한, 디코드 프레임 6초 이상 정지(+1.5초 점검 주기) 시
기존 peer를 닫고 재연결한다. 재시도 간격은 2초부터 최대 30초까지 늘린다.
페이지 숨김/종료 시 peer·재시도·프레임 점검을 해제하고, 복귀 시 새로 연결한다.
뒤늦게 생성된 WHEP 세션도 삭제한다. 연결 실패 시 Pi4 MJPEG 중계로 복귀하지 않는다.

## 현재 AI 상태와 과거 사건 구분

Pi4는 Pi5 `/api/status`에서 Dahua 상태만 읽어 제한된 필드를 반환한다.
브라우저당 매 프레임이 아니라 약 2.5초마다 조회하며 Pi4에서 1초 캐시를 공유한다.
Pi5 HTTP 요청은 최대 2초/128 KiB다. 영상 프레임이 3초 초과로 오래되거나 연결
실패이면 `unknown`으로 표시하고 마지막 정상 상태를 현재 상태인 것처럼 유지하지 않는다.
`현재 확정 경보 없음`은 AI의 현재 상태이며 선택한 과거 사건의 처리 완료를 뜻하지 않는다.
경보 해제/스피커 조작 기능은 이 읽기 전용 화면에 없다.

## 수정/배포 범위

소스: `pi4/integrations/fall_notice.py`, `fall_notice.js`, `fall_review/`.
Pi4 배포: `/opt/smarthome/web/fall_notice.py`, `static/fall_notice.js`, `fall_review/`.
기존 `app.py`의 `install_fall_notice(app)` 및 `index.html`의 script hook을 재사용한다.
협업자 app/index, 센서·차트·DB·자동화 코드, 8081, 다른 서비스는 수정하지 않는다.
배포 시 Python 라우트를 반영하기 위해 `web.service`만 재시작한다.
원본→reference 자동 동기화를 유지하고 변경 사본을 검증하여 Git에 반영한다.

## 검증

- `tests/test_fall_review.py`: 51건 수신 후 50건 유지/최고령 삭제, 30초 후 기록
  조회, 사진 만료/없는 ID, 자산 경로 제한, 같은 출처/SDP 제한/고정 Pi5 경로,
  세션 Location 변환/종료 경쟁, 현재 상태 캐시/오프라인 unknown.
- `tests/browser_fall_review_check.py`: HTTP 시험 자료 50건(실제 MQTT 발행 없음),
  실제 Pi5 WebRTC 재생, ICE 원격 주소 확인, 1440/780/390px 레이아웃,
  수동 시험 필터, 사건 변경 시 peer 한 개 유지, 삭제된 사건 안내,
  페이지 숨김/복귀, 프레임 정지 재연결, 팝업 사진에서 특정 사건 새 탭 열기.
- 로컬 시험에서 원격 ICE 후보 `192.168.1.20:8189 UDP host` 확인.
  이는 Pi4 영상 중계/TURN이 아닌 Pi5 직접 연결이다.
- 실제 Wi-Fi 환경의 지연/외부 Tailscale 연결/장시간 운영 검증은 별도 확인이 필요하다.

실행 예시(Playwright가 설치된 별도 환경의 경로는 장비에 맞게 지정):

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -q
python tests/browser_fall_review_check.py --base http://192.168.1.10:8000
```

### 실제 배포 확인 (2026-10-22 15:45–15:47 KST)

- 전체 Python 회귀 테스트 **108개 통과**.
- 실제 Pi4 `:8000`을 대상으로 위 브라우저 시험 통과. ICE 원격 후보는
  `192.168.1.20:8189/UDP/host`; 실시간 영상은 Pi4가 아닌 Pi5에서 수신했다.
- 15:46:09 수동 confirmed → Pi4 MQTT 수신/목록 저장 → 92,284바이트 JPEG 조회.
  캡처는 `pose_frame_matched=true`, frame 21687, age 33ms, 박스 4개/관절 38개였다.
- 해당 실제 사건 화면에서 960×580 캡처와 1920×1080 WebRTC 동시 표시 확인.
  시각 검증 화면은 Git 제외 `runtime/pi4-fall-review-verified.png`에 저장했다.
- 15:46:11 시험 clear 발행 후 Pi4 수신 상태 `normal`까지 확인했다. 시험 이벤트
  한 건은 실제 감지와 구별된 상태로 최근 목록에 남겨 사용자가 확인할 수 있다.
- 협업자 `/opt/smarthome/web/app.py`, `index.html` SHA-256은 배포 전후 동일.
  web/collector/automation/audio/sync timer 모두 active, 8081 listener 없음.
- 확인 시 Pi5 두 카메라 online, MQTT 연결/발행 거부 0, Hailo 실효 13.32 FPS.
  이는 순간 측정이며 장시간 안정성/정확도나 모든 외부 네트워크 연결의 보장은 아니다.
- Git: Pi5 기능 `3967c87` → Pi4 pull/모듈 배포/동기화 사본 `07077f7` → Pi5 pull.
  이 검증 문서도 양쪽 main에 순서대로 반영한다. force push는 사용하지 않는다.
