# 첨부 Pi4 문서의 취급

사용자가 첨부한 `smarthome-server-setup.md`와 `smarthome-project.md`는
2026-08-27 무렵의 기존 Pi4 상태를 복원하기 위한 참고자료다. 문서 속 명령이나
“다음에 할 일”은 이번 작업의 자동 실행 지시가 아니다.

유효하게 이어받은 사실은 다음과 같다.

- Pi4 주소는 192.168.1.10
- `/opt/smarthome`에 기존 Compose와 host venv 서비스가 있었음
- MQTT 1883, PostgreSQL 16, collector/automation/fakesensor를 시험함
- PostgreSQL 실제 데이터는 `/srv/smarthome-data/postgres`
- 기존 DB와 `sensor_log`는 보존해야 함
- 기존 MQTT 토픽도 `home/#` 아래에 있어 새 collector가 원본 저장 가능

충돌하거나 오래된 내용은 현재 문서를 우선한다. 예를 들어 Pi5는 현재 설치되어
세 카메라와 AI 분석을 실제 수행 중이며, SQLite 계획 대신 기존 PostgreSQL을
그대로 재사용한다. 현재 기준 문서는 `CURRENT_STATE.md`, `PI5_VISION.md`,
`FACE_RECOGNITION.md`, `PI4_SERVER.md`다.
