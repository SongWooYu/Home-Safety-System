# Raspberry Pi 4 다음 작업

## 역할 분리

- Raspberry Pi 5: 세 카메라 수집, 사람/자세/낙상/얼굴 분석, 개발용 대시보드
- Raspberry Pi 4: MQTT 중앙 브로커, 이벤트 저장, 위험 상태 판단, 알림과 장치 제어, 최종 서비스 화면
- Dahua 카메라: 공유기 연결, `192.168.1.64`
- Raspberry Pi 4 MQTT 예정 주소: `192.168.1.10:1883`
- Raspberry Pi 5 Vision 대시보드: `192.168.1.20:8080`

## 현재 Pi 5가 보내는 MQTT

- `home/vision/events`: 사람 출입 및 낙상 상태 변화
- `home/vision/status/cam3`: Camera Module 3 상태, 5초 retain
- `home/vision/status/webcam`: 웹캠 상태, 5초 retain
- `home/vision/status/dahua`: Dahua 상태, 5초 retain

## Pi 4 우선 작업

1. Mosquitto 확인
   - 서비스 자동 시작과 `1883` LISTEN 확인
   - Pi 5에서 publish/subscribe 왕복 시험
   - 전시장 LAN 밖에서는 접근하지 못하도록 방화벽 또는 bind 설정
2. 이벤트 수집 서비스
   - `home/vision/events` 구독
   - SQLite에 시간, 카메라, 이벤트 종류, 신뢰도, 세부 정보를 저장
   - 중복 메시지와 재연결 처리
3. 위험 상태 머신
   - `normal -> suspected -> confirmed -> alarm -> acknowledged/cancelled`
   - 카메라별 상태와 전체 주택 상태를 분리
   - 낙상 확정 후 일정 시간 내 취소되지 않으면 경보
4. 알림 및 장치 제어
   - 스피커/부저 작동
   - 모니터 전체 화면 경고
   - 수동 확인·취소 버튼
   - 추후 ESP32나 다른 노드에는 별도 command 토픽으로 전달
5. 최종 서비스 화면
   - Pi 5의 `:8080`은 분석 확인용으로 유지
   - Pi 4에는 사용자용 상태/이벤트/경보 화면을 별도 구성
   - 최근 사건, 현재 카메라 상태, 확인/취소만 단순하게 표시
6. 운영 안정성
   - systemd 자동 시작
   - MQTT 재접속과 오프라인 표시
   - 로그 용량 제한
   - 전원 재부팅 후 자동 복구 시험

## 후순위 고도화

- 사람 행동 분류: 서기, 앉기, 눕기, 걷기
- 다중 사람 추적 ID와 얼굴 이름 연결
- 전시장 촬영 데이터로 낙상 임계값 또는 시계열 모델 학습
- “나 괜찮아” 음성 취소
- Hailo-8 도착 후 자세/얼굴 추론 가속
- ESP32 카메라 감시 전용 화면 통합

## Pi 4 완료 기준

- Pi 5 세 카메라의 retain 상태를 Pi 4에서 확인할 수 있음
- 낙상 테스트 이벤트가 Pi 4 DB에 한 번만 저장됨
- 경보가 울리고 화면에 표시됨
- 수동 취소 후 경보가 중단됨
- Pi 4와 Pi 5를 재부팅해도 모든 서비스가 자동 복구됨
