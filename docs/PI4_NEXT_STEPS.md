# Raspberry Pi 4 다음 작업 체크리스트

구현과 설치 절차의 기준 문서는 [PI4_SERVER.md](PI4_SERVER.md)다. 이 문서는
현장에서 순서대로 확인할 짧은 체크리스트다.

## 1. 설치 전

- [ ] Pi4 주소가 `192.168.1.10`인지 확인
- [ ] 기존 `/srv/smarthome-data/postgres` 용량과 권한 확인
- [ ] 기존 PostgreSQL과 Mosquitto 컨테이너 이름 확인
- [ ] 기존 `/opt/smarthome`과 systemd 서비스 상태 기록
- [ ] 최소 수 GB의 여유 공간과 정상 전원 확인

## 2. Git 기반 마이그레이션

- [ ] `/home/pi/Home-Safety-System` clone
- [ ] `sudo ./pi4/scripts/install.sh --migrate-legacy /opt/smarthome`
- [ ] 생성된 `/srv/smarthome-data/backups/pre-git-migration-*.sql` 확인
- [ ] `./pi4/scripts/status.sh`에서 5개 서비스 healthy/running 확인
- [ ] 과거 `sensor_log` 행이 그대로 있는지 확인
- [ ] `http://192.168.1.10:8081` 접속

## 3. Pi5 연동

- [ ] Pi5 `/api/status`에서 `mqtt_connected: true`
- [ ] Pi4 화면에 cam3, webcam, dahua가 15초 이내 최신 상태로 표시
- [ ] 사람 등장/퇴장 한 번씩 DB 저장
- [ ] 같은 `event_id`가 중복 저장되지 않음
- [ ] `./pi4/scripts/smoke-test.sh`로 경보·취소 확인
- [ ] 실제 낙상 시연으로 suspected→alarm→cancelled 확인

## 4. 하드웨어 출력

- [ ] 스피커 또는 부저 연결 방식 선택
- [ ] `home/safety/fall/alarm`의 active true/false 구독
- [ ] 취소 뒤 즉시 정지
- [ ] 장치 연결이 끊겨도 Pi4 웹·DB 서비스는 계속 동작

## 5. 운영 완료

- [ ] Pi4와 Pi5를 동시에 재부팅해 자동 복구
- [ ] 2시간 이상 카메라·MQTT·DB·화면 유지
- [ ] 로그와 DB 증가량 측정
- [ ] Mosquitto 계정과 방화벽 적용
- [ ] 전시 직전 DB/설정 백업과 복구 리허설

## 후순위

- “나 괜찮아” 음성 취소
- 행동 분류와 사람 추적 ID
- 카메라별 낙상 임계값 보정
- Hailo 가속
- ESP32 감시 전용 입력
