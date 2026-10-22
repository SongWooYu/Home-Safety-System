# Pi4 재정렬: Git, 8081 폐기, 협업 코드와 음성 시험

기준: 2026-10-22. Pi5 `192.168.1.20`, Pi4 `192.168.1.10`.
이번 범위는 Git 정렬·현재 상태 점검·8081 정리·음성 시험 편의 개선이다.
**협업자 8000 화면과 비전의 실제 통합, DB 통합은 아직 하지 않는다.**

## 1. 작업 위치와 Git

- Pi5/Pi4 공통 Git: `/home/pi/Home-Safety-System`, `main`.
- Pi4 협업자 원본: `/opt/smarthome` (수정·삭제하지 않음).
- 참고 복사본: `reference/collaborator-smarthome/`.
- `sync-collaborator-smarthome.timer/service`는 의도된 10초 자동 동기화이며 유지.
- Pi4 원본 `web/index.html`과 복사본 SHA256 일치 확인 후 `2083e24`로 커밋.
- Pi5의 최신 비전 이력과 `cfc209e`로 병합·GitHub push, Pi4 `pull --ff-only` 완료.
- 협업 변경: 방별 고정 카드/데이터 없음 표시, 그래프 1분 단위 시간축 정렬,
  갱신 주기 0.5초 → 3초. `pi4/`에 자동 병합하지 않고 참고 코드로 보존했다.
- 새로운 GitHub CLI 로그인 없이 기존 인증/공개 fetch로 진행했다.

## 2. 실제 구성과 8081 처리

| 구성 | 확인/조치 |
|---|---|
| `web.service`, `/opt/smarthome/web/app.py`, :8000 | 협업자 센서 대시보드, 유지 |
| `collector.service`, `automation.service` | 협업자 센서 수집/자동화, 유지 |
| `smarthome-postgres`, localhost:5432 | 협업자 DB, 유지 |
| `home-safety-pi4-mqtt-1`, :1883 | Pi5/음성 경보용 브로커, 유지 |
| `home-safety-pi4-automation-1` | vision → safety MQTT 자동화, 유지 |
| `smarthome-audio-alarm.service` | Pi4 호스트 ALSA 스피커 출력, 유지/갱신 |
| `home-safety-pi4-web-1`, :8081 | 중지 + restart=no, 포트 닫힘 |
| `home-safety-pi4-collector-1` | 실패 반복 중, 사용자 승인으로 중지 + restart=no |
| `home-safety-pi4-postgres-1` | 공유 데이터 디렉터리 중복 DB, 승인 후 중지 + restart=no |

8081은 다른 앱이 점유해서 못 쓰는 것이 아니라 **기존 웹 컨테이너가 열고 있지만
DB 초기화 실패로 재시작을 반복해 응답하지 않던 상태**였다. 점검 시 웹 재시작
약 1,900회, 수집기 약 2,260회. 수집기 로그에는
`permission denied: "mqtt_message" is a system catalog`가 있었다.
이 오류의 DB/schema 정합성 원인은 아직 수리/확정하지 않았다.

## 3. 중복 PostgreSQL 위험과 보존

서로 다른 PostgreSQL 프로세스 두 개가 실제로 동시에
`/srv/smarthome-data/postgres`를 사용했다. 이름만 다른 정상적인 DB 분리가 아니다.
사용자의 명시 승인 후 비전 측 중복 DB와 실패 수집기를 중지했다.

중복 DB 정지 시 공유 `postmaster.pid`가 제거돼 협업자 DB도 잠금 파일 오류로
한 번 자동 재시작했다. 이후 협업자 `/api/latest` HTTP 200과 논리 백업 성공을
확인했다. **무중단 처리였다고 주장하지 않으며 백업 성공이 전체 무결성 보증은 아니다.**

Pi4 비공개 백업 (Git 제외, 0600):

```text
/home/pi/Home-Safety-System/runtime/pi4-audit-20261022.7A7wMs/database.dump
```

컨테이너·DB 파일·볼륨은 삭제하지 않았다. `down -v`, DB 복구/마이그레이션,
협업자 서비스 통합은 실행하지 않았다. 중복 DB는 다시 시작하지 말 것.

재발 방지:

- Compose 기본 서비스는 MQTT/automation만. DB와 수집기는 `standalone-db`
  profile을 명시해야 함. 8081 웹은 추가 `legacy-web` profile 필요.
- 새 독립 설치의 DB 기본 경로를 `/srv/smarthome-data/home-safety-postgres`로 분리.
  **기존 Pi4 .env/DB 경로는 자동 변경하지 않았다.**
- 설치기가 기존 실제 이름 `smarthome-postgres`, `smarthome-mqtt`도 감지하여
  협업 스택이 있으면 기본 설치 중단. `--migrate-legacy`를 현재 Pi4에서 실행하지 말 것.
- 소리만 갱신할 때는 `install-audio-alarm.sh`만 실행한다.

## 4. 자연음성 및 관리키 없는 시험

현재 설치/소스/주요 자산 경로에서 이전 자연음성 파일은 찾지 못했다.
실행 중인 서비스는 `espeak-ng`로 부팅마다 안내 음성을 생성하고 있었다.
이번에는 **고정 문구만 온라인으로 한 번 합성하고, 실제 경보는 오프라인 WAV 재생**한다.

- 문구: “낙상이 감지되었습니다.”
- 합성: `edge-tts==7.3.1`, `ko-KR-SunHiNeural`, rate -5%.
- 형식: 48 kHz / mono / PCM 16-bit WAV.
- 설치 경로: `/usr/local/share/home-safety/fall-detected-ko.wav`.
- `ALARM_TTS_WAV`로 대체 파일 지정 가능. 파일 미존재/잘못된 형식이면 espeak fallback.
- Pi5 임시 생성 venv는 비전 .venv와 분리. Pi4 실행 시 edge-tts 설치/인터넷 불필요.
- 생성 파일 SHA256: `bd9095ed428cc08387d1140ac8b34e27bf45e29eea5e5eb2cf7d24ff37a6560c`.
- 파일과 DB 백업은 Git에 올리지 않으며 생성 스크립트/설치 방법만 보존한다.

`edge-tts`는 Microsoft Edge 온라인 음성 서비스를 사용하는 커뮤니티 도구이며,
공식 Azure SDK가 아니다. 설치 시 외부로 보내는 내용은 위 고정 문구뿐이다.
인식된 이름·카메라 영상·얼굴 특징은 합성 서비스에 보내지 않는다.
도구 사용 근거: [edge-tts 프로젝트](https://github.com/rany2/edge-tts).

재생성 예시 (별도 venv에 `edge-tts==7.3.1`, 시스템 ffmpeg 필요):

```sh
python pi4/scripts/prepare-natural-tts.py --output runtime/audio/fall-detected-ko.wav
# Pi4로 WAV를 복사한 뒤 Pi4에서:
sudo ALARM_TTS_ASSET=/absolute/path/to/fall-detected-ko.wav ./pi4/scripts/install-audio-alarm.sh
```

시험 위치: **Pi5 `http://192.168.1.20:8080/#audio-test-panel`**.
8000 협업 화면에는 아직 추가하지 않았다. 얼굴 목록/삭제 관리키는 그대로 유지한다.

1. 선택 음량을 조절하고 `음량 적용`을 누른다. 슬라이더 초깃값 50%는 장치 조회값이 아니다.
2. `음성 1회 재생`을 누른다. 관리키 없이 고정 문구만 재생한다.
3. 낙상 이벤트를 만들거나 반복 경보를 켜지 않는다.
4. 음량은 retained MQTT 설정이라 **이후 실제 경보 음량에도 적용**된다.

경로:

```text
Pi5 개발 화면 → Pi5 고정 음성 API → Pi4 MQTT :1883
  → smarthome-audio-alarm.service → ALSA bcm2835 Headphones (3.5mm)
```

API: `POST /api/audio/test {}`, `POST /api/audio/volume {"volume":50}`.
다른 origin의 브라우저 요청/비 JSON/범위 밖 음량/짧은 반복 클릭은 거부한다.
음성 명령은 non-retained, 음량만 retained. 브로커 PUBACK까지 확인하되 이는
사용자가 실제로 소리를 들었다는 보장은 아니다. 재생 실패는 Pi4 journal에서 확인한다.
실제 경보 중 시험 음성을 큐에 쌓지 않는다. 이 무인증 시험 경로는 신뢰하는 LAN용이다.
공용망/인터넷 노출 전에 별도 접근 제어가 필요하다.

## 5. 다음 우선순위 (이번에는 미실행)

1. 보존한 DB 백업의 복원 시험, schema/OID 및 권한 정합성 조사.
2. 협업자와 DB 및 브로커 한 개씩의 소유권/접속 계약 확정. 두 브로커가 같은 메시지를
   보는지 아직 확인하지 않았고, 코드/DB를 자동 합치지 않는다.
3. vision 수집기를 합의한 DB에 재연결. 현재 정지 상태이므로 비전 사건 DB 저장 완료로
   보고하면 안 된다. MQTT 경보 자동화·스피커는 별도 경로다.
4. 자연음성 청취와 음량 확인 후 실제 fall_confirmed → alarm → speaker → cancel 시험.
5. 협업자 8000에 이벤트/경보 제어와 Pi5 직접 WebRTC 영상 통합. 영상 바이트를 Pi4에서
   중계하지 않고, Pi5 개발 오버레이와 서비스 clean 영상을 구분한다.
6. 재부팅/절전 복귀/장시간 시험, 권한·네트워크 접근 범위 결정.

Pi5 Hailo/EdgeFall v6 모델·임계값·카메라 FPS·얼굴 등록 데이터는 변경하지 않았다.
