# Raspberry Pi 4 중앙 서버

## 역할

Pi4는 AI 추론을 하지 않는다. Pi5가 보내는 작은 MQTT 메시지를 받아 영속 저장하고,
낙상 상태를 경보로 바꾸며, 전시 관람자가 보는 최종 상태 화면을 제공한다.

```text
Pi5 세 카메라/AI
  -> MQTT home/vision/*
  -> Pi4 Mosquitto
       -> collector -> PostgreSQL
       -> automation -> safety state/alarm
       -> web :8081 -> 상태·사건·경보 취소
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
PostgreSQL 비밀번호와 관리자 키를 `pi4/.env`에 생성한다. DB는
`/srv/smarthome-data/postgres`에, MQTT 지속 데이터는 저장소의
`pi4/runtime/mqtt/data`에 둔다. 둘 다 Git에서 제외된다.

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
| web | Flask/Gunicorn | 8081 | 사용자 화면과 API |

모든 컨테이너는 `restart: unless-stopped`다. Docker 서비스가 부팅 때 시작하면
Pi4 재부팅 후 자동 복구된다.

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
false일 때 즉시 멈추게 구현한다. 현재 저장소에는 실제 하드웨어 드라이버가 아직
없다.

## 통합 시험

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
- Pi5 사건이 DB에 정확히 한 번 저장됨
- 낙상 확정 시 화면 경보와 alarm 토픽이 켜짐
- 관리 키 취소 시 alarm 토픽이 꺼짐
- 과거 `sensor_log`와 DB 내용이 보존됨
- Pi4/Pi5 동시 재부팅 뒤 3분 내 자동 복구
- 2시간 전시 부하에서 컨테이너 재시작과 DB 오류가 없음
