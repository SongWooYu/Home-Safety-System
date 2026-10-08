# Raspberry Pi 4 중앙 서버

## 역할

Pi4는 AI 추론과 영상 중계를 하지 않는다. Pi5가 보내는 MQTT 메시지를 저장하고
낙상 상태를 경보로 바꾼다. 전시 브라우저는 Pi4에서 화면·상태 API를 받고,
영상만 Pi5 MediaMTX와 WebRTC로 직접 연결한다.

```text
Pi5 세 카메라/AI -> MQTT home/vision/* -> Pi4 MQTT/DB/자동화
Pi4 web :8081 -> HTML, 상태·사건·경보 취소
브라우저 <-> Pi5 MediaMTX :8889/:8189 -> AI 오버레이 WebRTC
```

## Git clone 후 새 설치

Pi4 주소는 `192.168.1.10`으로 먼저 고정하거나 DHCP 예약한다.

```bash
cd /home/pi
git clone https://github.com/SongWooYu/Home-Safety-System.git
cd Home-Safety-System
sudo ./pi4/scripts/install.sh
```

스크립트는 Docker/Compose가 없으면 Ubuntu/Debian 패키지로 설치하고, 무작위
PostgreSQL 비밀번호와 관리자 키를 `pi4/.env`에 생성한다. `.env`는
`root:<운영자 그룹>` 0640으로 설정되어 운영 사용자가 status/Compose 명령을
실행할 수 있다. DB는 `/srv/smarthome-data/postgres`에, MQTT 지속 데이터는
저장소의 `pi4/runtime/mqtt/data`에 둔다. 둘 다 Git에서 제외된다.

기본 설치는 `alsa-utils`, `mosquitto-clients`와 Pi4 호스트의
`smarthome-audio-alarm.service`도 설치한다. 스피커를 쓰지 않을 때만
`sudo INSTALL_AUDIO_ALARM=0 ./pi4/scripts/install.sh`로 생략한다.

설치 후:

```bash
./pi4/scripts/status.sh
sudo sed -n 's/^ADMIN_TOKEN=//p' pi4/.env
```

브라우저에서 `http://192.168.1.10:8081`에 접속한다.

## 기존 /opt/smarthome에서 마이그레이션

첨부된 2026-08-27 기록에 따르면 기존 Pi4에는 다음이 있다.

- `/opt/smarthome` Docker Compose
- Mosquitto와 PostgreSQL 16 컨테이너
- `/srv/smarthome-data/postgres` DB
- host venv collector와 systemd 서비스
- 과거 `sensor_log` 테이블 및 센서/자동화 시험

기존 컨테이너가 감지되면 일반 설치는 아무것도 중단하지 않고 종료한다. 다음
명령을 명시적으로 실행해야만 마이그레이션한다.

```bash
cd /home/pi/Home-Safety-System
git pull --ff-only
sudo ./pi4/scripts/install.sh --migrate-legacy /opt/smarthome
```

마이그레이션 순서:

1. 실행 중인 PostgreSQL 컨테이너 환경에서 DB 이름·사용자·비밀번호를 읽음
2. `/srv/smarthome-data/backups/pre-git-migration-*.sql`에 `pg_dumpall` 생성
3. 과거 collector/automation/fakesensor systemd 서비스를 중지·비활성화
4. 과거 Compose를 `down`하되 절대 `-v`를 사용하지 않음
5. 과거 DB bind 디렉터리를 새 PostgreSQL 16 컨테이너가 재사용
6. 새 테이블을 `IF NOT EXISTS`로 추가
7. 새 스택을 빌드·시작하고 `/health` 확인

과거 디렉터리와 DB는 자동 삭제하지 않는다. 새 구성이 검증된 뒤 별도 백업을
확인하고 사람이 직접 정리한다.

## 서비스 구성

| 서비스 | 이미지/실행 | 외부 포트 | 역할 |
|---|---|---:|---|
| mqtt | eclipse-mosquitto 2 | 1883 | 메시지 브로커 |
| postgres | PostgreSQL 16 | 없음 | 내부 영속 저장 |
| collector | Python 3.12 | 없음 | `home/#` 수집·정규화 |
| automation | Python 3.12 | 없음 | 낙상 상태와 경보 토픽 |
| web | Flask/Gunicorn | 8081 | 사용자 화면, 상태 API, 경보 취소(영상 바이트 미경유) |
| audio alarm | 호스트 systemd + ALSA | 없음 | MQTT alarm을 3.5 mm 스피커로 재생 |

모든 컨테이너는 `restart: unless-stopped`다. Docker 서비스가 부팅 때 시작하면
Pi4 재부팅 후 자동 복구된다.

## AI 처리 영상 전달

영상은 MQTT로 보내지 않는다. MQTT는 이벤트와 상태에만 사용한다. 실제 영상은
다음 경로로 전달한다.

```text
카메라 -> Pi5 BGR/AI 분석/오버레이 JPEG
       -> 로컬 FFmpeg: H.264 640x360, 15 FPS, 1,000 kbit/s
       -> Pi5 MediaMTX: 로컬 RTSP 게시
       -> WebRTC/ICE(UDP 8189 우선, TCP 8189 대체)
       -> 전시 브라우저
```

브라우저가 `192.168.1.10:8081`의 Pi4 화면을 열어도 영상 iframe은
`192.168.1.20:8889/<camera>`를 직접 연다. Pi4 Flask/Gunicorn에는 영상 바이트가
들어오지 않는다. 전시 브라우저 자체가 Pi4에서 실행된다면 Pi4의 브라우저는
여전히 H.264를 수신·디코딩하지만, Pi4 백엔드·Docker 네트워크·Python 메모리는
영상 중계에 쓰이지 않는다.

`pi4/.env` 설정:

```dotenv
VISION_API_URL=http://192.168.1.20:8080
WEBRTC_BASE_URL=http://192.168.1.20:8889
WEBRTC_CAMERAS=cam3,webcam,dahua
```

확인 경로:

```bash
curl -s http://192.168.1.10:8081/api/vision/health
curl -L -I http://192.168.1.20:8889/cam3
```

방화벽이 있다면 브라우저에서 Pi5의 TCP 8889와 UDP 8189를 허용한다. UDP가
막히면 TCP 8189 ICE 대체 경로를 사용하지만 지연이 늘 수 있다. Pi5의 TCP 8080은
Pi4 상태 확인과 개발 대시보드용이다. 자세한 설치·조정·장애 확인은
[WebRTC 스트리밍 문서](WEBRTC_STREAMING.md)를 따른다.

## 데이터 모델

- `mqtt_message`: 카메라 주기 상태를 제외한 `home/#` 원본 JSON
- `vision_event`: `event_id`가 유일한 정규화 AI 사건
- 5초 주기 카메라 상태는 누적하지 않고 `vision_status`에 카메라별 최신값만 upsert해 SD 카드 사용량을 줄임
- `vision_status`: 카메라별 가장 최근 retain 상태
- `safety_state`: 현재 전체 낙상 상태
- 과거 `sensor_log`: 삭제하거나 변경하지 않음

Pi5 스키마 1.1의 `event_id`를 기본 키로 사용한다. 구형 이벤트에 ID가 없으면
payload SHA-256을 대체 키로 사용한다.

## MQTT 토픽

| 토픽 | 방향 | retain | 설명 |
|---|---|---|---|
| `home/vision/events` | Pi5→Pi4 | 아니오 | 사람/낙상 상태 변화 |
| `home/vision/status/<camera>` | Pi5→Pi4 | 예 | 5초 주기 카메라 상태 |
| `home/safety/fall/state` | Pi4 automation→전체 | 예 | normal/suspected/alarm/cancelled |
| `home/safety/fall/alarm` | Pi4 automation→장치 | 예 | `active: true/false` |
| `home/safety/fall/command` | UI/음성/버튼→Pi4 | 아니오 | `{"action":"cancel"}` |

스피커나 부저는 `home/safety/fall/alarm`을 구독해 `active=true`일 때 작동하고,
false일 때 즉시 멈춘다. 현재 구현은 Pi4의 `bcm2835 Headphones`(3.5 mm)를
`aplay`로 사용한다. 별도 장치를 쓰면 `/etc/default/smarthome-audio-alarm`에
`ALARM_AUDIO_DEVICE=<ALSA 장치>`를 지정하고 서비스를 재시작한다.

```bash
systemctl status smarthome-audio-alarm.service
journalctl -u smarthome-audio-alarm.service -n 50 --no-pager
```

## 통합 시험

2026-10-08 Pi5에서 실제 확인한 결과:

- Pi4 `/health`와 `/api/vision/health` 정상
- 세 Pi5 retain 상태가 Pi4 `overview`에 반영
- 비경보 `integration_probe` MQTT→collector→PostgreSQL→웹 API 왕복 성공
- 같은 `event_id`를 QoS 1로 2회 발행해도 `vision_event`에는 1행만 저장
- Pi5 전용 키 `~/.ssh/home_safety_pi4_ed25519`로 `pi@192.168.1.10` 접속 확인
- Pi4 스피커 MQTT true/false 실기 시험과 취소 시 재생 종료 확인

실제 `fall_confirmed` smoke test는 경보를 울리고 DB를 변경한다. 현장에 사람이
있고 관리 키로 즉시 취소할 수 있을 때만 실행한다.

```bash
cd /home/pi/Home-Safety-System
./pi4/scripts/status.sh
./pi4/scripts/smoke-test.sh
```

smoke test는 `smoke-test` 카메라의 `fall_confirmed`를 한 번 발행한다. 화면과
DB에 한 번 나타나고 경보가 활성화되는지 본 뒤 관리 키로 취소한다. 그 다음
Pi5 실제 카메라에서 동일 흐름을 확인한다.

DB 중복 확인 예:

```bash
docker compose --env-file pi4/.env -f pi4/compose.yml exec postgres \
  psql -U smarthome -d smarthome -c \
  "select event_id,count(*) from vision_event group by event_id having count(*) > 1;"
```

## 운영 명령

```bash
docker compose --env-file pi4/.env -f pi4/compose.yml ps
docker compose --env-file pi4/.env -f pi4/compose.yml logs -f --tail=100
docker compose --env-file pi4/.env -f pi4/compose.yml up -d --build
docker compose --env-file pi4/.env -f pi4/compose.yml stop
```

운영 중 `docker compose down -v`, PostgreSQL 데이터 디렉터리 삭제, 비밀번호가
포함된 `.env` 커밋을 금지한다.

## 보안 전환

현재 Mosquitto의 `allow_anonymous true`는 Pi5와의 첫 통합을 유지하기 위한
사설 전시장 LAN 임시 설정이다. 학교 공용망 또는 외부 접근 전에 다음을 해야 한다.

1. Mosquitto 계정 파일과 `allow_anonymous false`
2. Pi5 `.env`의 `MQTT_USERNAME`, `MQTT_PASSWORD`
3. Pi4 컨테이너에도 동일 자격 증명
4. 방화벽에서 1883과 8081을 지정된 관리망으로만 허용
5. 가능하면 TLS 또는 별도 VLAN

웹의 경보 취소는 `ADMIN_TOKEN` 헤더가 있어야 한다. 그러나 MQTT가 익명인 동안
같은 LAN 사용자가 command 토픽을 직접 발행할 수 있으므로 이것만으로 완전한
보안은 아니다.

## Pi4 완료 기준

- 세 카메라 retain 상태가 15초 이내 최신으로 표시됨
- Pi4 화면에서 세 AI 오버레이 영상이 브라우저-Pi5 WebRTC로 자동 재연결되며 표시됨
- Pi5 사건이 DB에 정확히 한 번 저장됨
- 낙상 확정 시 화면 경보와 alarm 토픽이 켜짐
- 관리 키 취소 시 alarm 토픽이 꺼짐
- 과거 `sensor_log`와 DB 내용이 보존됨
- Pi4/Pi5 동시 재부팅 뒤 3분 내 자동 복구
- 2시간 전시 부하에서 컨테이너 재시작과 DB 오류가 없음
