# Pi5 음성·얼굴 등록 / Pi4 독립 낙상 알림 변경 기록

기준: 2026-10-22. 작업 위치 `/home/pi/Home-Safety-System` (Pi5).

## 1. Cloudflare 터널에서 TTS 제어가 거부되던 원인

`https://vision.aihous.site` → Pi5의 로컬 cloudflared →
`http://localhost:8080` 경로다. 기존 API는 브라우저의 HTTPS Origin과
Flask가 보는 HTTP scheme을 비교해 정상 요청을 403으로 거부했다.

`src/smarthome_vision/request_origin.py`에서 다음을 적용했다.

- 실제 접속 peer가 `127.0.0.1` / `::1`인 경우에만 단일
  `X-Forwarded-Proto: http|https`를 인정한다.
- Host는 전달된 실제 Host로 비교한다. 임의 X-Forwarded-Host나
  LAN에서 보낸 X-Forwarded-Proto는 신뢰하지 않는다.
- 다른 Origin, `Sec-Fetch-Site: cross-site`, 잘못된 Origin은 계속 거부한다.
- 터널/Cloudflare Access 정책 자체는 변경하지 않았다.
- 이는 출처 위조 방어이지 로그인 인증이 아니다. 관리 키 없는 데모 제어이므로
  공개 주소를 아는 사람이 직접 API를 사용하는 것을 막지는 않는다.
  향후 외부 운영 인증은 별도 의사결정이 필요하다.

Cloudflare One 스킬의 신뢰 경계 점검에 따라 보호를 제거하는 대신
로컬 connector 경로만 보정했다. 참고:
[Cloudflare 요청 헤더](https://developers.cloudflare.com/fundamentals/reference/http-headers/),
[Flask 프록시 신뢰 설정](https://flask.palletsprojects.com/en/stable/deploying/proxy_fix/).

## 2. 음량과 TTS

- Pi5 슬라이더/API, MQTT 발행 adapter, Pi4 오디오 수신기의 범위: **60~100%**.
- UI 기본 선택: **70%**. 실제 장치에도 retained MQTT 명령으로 70%를 적용했다.
- UI 선택 숫자는 장치에서 되돌려 받은 실측 음량이 아니다. `음량 적용`을 눌러야 한다.
- 낮은 음량을 무음으로 해석하지 않는다. 무음 기능을 추가한다면 별도 명령으로 설계한다.
- 기존 자연스러운 한국어 **SunHiNeural** 사전 생성 WAV를 그대로 사용한다.
  재생 때 인터넷 합성은 하지 않는다.
- `POST /api/audio/test`는 음성 1회만 재생한다. 가짜 낙상이나 DB 이벤트를 만들지 않는다.
- 시험: 실제 HTTPS 터널 → HTTP 200 → MQTT QoS 1 확인 → Pi4 로그
  `queued one-shot TTS playback`, `one-shot TTS playback completed` 확인.
  실제 청감과 적정 음압은 사용자가 확인해야 한다.

## 3. 얼굴 등록: 시간표가 아니라 실제 자세에 따라 진행

이전 화면은 약 10초짜리 안내 애니메이션 후 저장 단계에서만 각도 부족을 확인했다.
새 화면은 다음 API를 사용한다.

| API | 역할 |
|---|---|
| `POST /api/faces/enrollment` | 이름·카메라로 단일 등록 세션 시작 |
| `GET /api/faces/enrollment/<id>` | 현재 요구 방향, 즉시 피드백, 유효 표본 수 |
| `DELETE /api/faces/enrollment/<id>` | 취소, 미완료 특징 폐기 |

운영 로직은 별도 `face_enrollment.py`에 있다.

1. 정면 → 화면 오른쪽 → 화면 왼쪽 순서로 실제 YuNet 눈·코 위치를 확인한다.
2. 방향별 서로 다른 최신 프레임에서 선명한 특징을 최소 5개 확보하고,
   같은 자세가 최소 0.8초 유지돼야 다음 단계로 진행한다.
3. 얼굴 없음/여러 얼굴/잘린 얼굴/흐림/과도한 측면/잘못된 방향이면 즉시 안내한다.
   현재 방향의 연속 표본은 초기화되며, 완료된 방향은 유지한다.
4. 처음 얼굴 특징과의 유사성을 확인해 중간에 사람이 바뀌는 것을 억제한다.
   이 역시 생체 위변조 검증이나 완전한 동일인 보장은 아니다.
5. 1.5초보다 오래된 프레임이나 같은 timestamp의 반복 프레임으로 진행하지 않는다.
6. 최대 45초. 시간 초과·취소는 **저장하지 않는다**. 세 방향을 모두 통과했을 때만
   세 템플릿을 함께 저장하고 세션 내 특징 버퍼를 폐기한다.
7. 서버 검사는 최대 약 4 Hz, 브라우저 상태 확인은 250ms 간격이다.
   추가 얼굴 검사는 등록 중에만 수행한다. Hailo 낙상 모델·FPS·임계값은 변경하지 않았다.

YuNet의 yaw는 눈 사이 거리 대비 코의 수평 위치를 이용한 **근사치**다.
3D 스캔·정부 앱 수준의 본인 인증·사진 공격 방지를 구현한 것은 아니다.
기존 수동/시간제 API는 호환용으로 남아 있지만 대시보드는 새 세션 API만 사용한다.
얼굴 삭제·목록 관리의 기존 관리 키 정책은 그대로다.

기존 얼굴 DB의 배포 전후 SHA-256은 같았다. 등록 데이터는 수정하지 않았다.
사용자 얼굴로 실제 좌우 안내 정확도와 선명도 기준을 확인하는 시험은 남아 있다.

## 4. Pi4 협업자 화면: 낙상 알림만 독립 추가

원본 `/opt/smarthome/web`을 보존하고 다음만 추가했다.

- `fall_notice.py`: 기존 1883 브로커의 `home/vision/events` 구독,
  읽기 전용 `/api/fall-notices` API.
- `static/fall_notice.js`: 우측 상단 비모달 알림. Shadow DOM으로 스타일·변수 격리.
- 기존 `app.py`: 모듈 import/설치 2줄과 주석.
- 기존 `index.html`: script 태그 1개.

나머지 센서 카드, 차트, DB 쿼리, 자동화, 기존 API는 변경하지 않았다.
Git 관리용 원본 모듈은 `pi4/integrations/`, 협업자 실제 소스의 공유 사본은
`reference/collaborator-smarthome/web/`에 있다. 운영 시 원본과 미러를 각각 수정하지
말고 `/opt/smarthome`의 변경 및 자동 동기화 결과를 확인한다.

### 알림 정책

- **`fall_confirmed`만 표시**. 의심, 해제, 사람 인식, 음성 시험 명령은 표시하지 않는다.
- X / 화면 바깥 클릭 / Esc로 닫는다. 기존 페이지 클릭도 그대로 전달한다.
- 닫기는 **UI 확인만** 의미한다. MQTT 경보 해제나 스피커 중단 명령을 발행하지 않는다.
- QoS 중복 event ID는 제거한다. retained 및 오래된 이벤트는 재생하지 않는다.
- 표시 대기 이벤트는 최근 수신 30초 이내만, 메모리 큐는 50개로 제한한다.
- 브라우저 조회는 2초 간격. 이 알림 지연은 영상 지연과 별개다.
- 새로고침 후에도 해당 탭에서 닫은 최근 event ID는 sessionStorage로 기억한다.
- 이 모듈은 DB에 쓰지 않는다. 기존 비전 이벤트 DB 수집기 재연결은 별도 과제다.

### 배포·복구

배포 전 Pi4 백업:
`/home/pi/Home-Safety-System/runtime/fall-notice-backup.6LbOPM/`.
여기에 기존 app.py, index.html, 설치된 audio_alarm-old.py가 있다.

문제가 있으면 **다른 협업자 변경이 추가되지 않았는지 먼저 확인**한 뒤
위의 import/설치 훅과 script 태그만 제거하고 `web.service`를 재시작하면 된다.
백업 파일로 전체 덮어쓰면 이후 협업자의 변경을 잃을 수 있으므로 피한다.
중복 DB/옛 8081 web/실패 collector 컨테이너는 계속 중지 상태이며 재시작하지 않았다.
`sync-collaborator-smarthome.timer`도 계속 active다.

## 5. 검증 및 사용자 시험

- Python 회귀 테스트 **81개 통과**.
- Chromium JS 구문 및 실행 오류 없음.
- 실제 HTTPS 브라우저 요청이 정상 출처 검사 통과, 타 출처 요청은 403 유지.
- 얼굴 안내 모의 시험: 10초가 지나도 잘못된 방향이면 다음 단계로 넘어가지 않음.
- Pi4 모의 이벤트: 최초 숨김 → 낙상 알림 → X/바깥 클릭/Esc 닫기 → 중복 재표시 없음.
  **운영 MQTT에 가짜 낙상을 발행하지 않았다**. 실제 낙상 → 알림창 전체 연결 시험은
  사용자가 안전한 기존 시연 조건에서 확인해야 한다.
- Pi4 `web`, 협업자 `collector`, 협업자 `automation`, 자동 동기화 active,
  `/api/latest` HTTP 200, 기본 DB healthy. 8081 listener 없음.
- Pi5 두 카메라 online, MQTT 연결, 입력 약 15 FPS, Dahua Hailo 약 14 FPS 확인.
  등록 중의 현장 성능/각도 정확도 시험이나 장시간 안정성 보증은 아니다.

사용자 시험 순서:

1. Pi5 화면을 한 번 새로고침. 터널에서도 음량 적용 → 음성 1회 재생.
2. 얼굴 등록 시작 후 일부러 정면만 유지: 오른쪽 단계에 멈추고 재안내해야 한다.
3. 그림 방향대로 고개를 돌려 완료. 중간 취소 시 저장되지 않아야 한다.
4. Pi4 `:8000`을 열고 실제 `fall_confirmed` 발생 시 우측 상단 알림 확인.
5. X/바깥 클릭은 화면만 닫는지 확인. 스피커 해제는 기존 경보 제어로 수행.

이번 변경은 배포된 작업 트리 상태다. 별도의 GitHub push는 수행하지 않았다.
