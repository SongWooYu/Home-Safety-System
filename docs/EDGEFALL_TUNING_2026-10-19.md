# EdgeFall 오탐 진단 및 v5 조정

적용: 2026-10-19 야간, Pi5 `/home/pi/Home-Safety-System`.
Pi4/협업자 `/opt/smarthome`/얼굴 등록 DB는 수정하지 않았다. FPS도 유지했다.

> 후속 수정: v5 시험에서 확정 0건을 확인했다. 핵심 원인은 MLP 골반 입력의 단위
> 불일치였다. [v6 수정 보고서](EDGEFALL_FEATURE_UNITS_2026-10-19.md)가 최신 상태다.
> 60Hz 적용 후 플리커가 사라진 것은 사용자가 확인했다.

## 확인한 원인과 확인하지 못한 것

기존 이벤트 버퍼 100개(한국 시각 21:03:06–21:10:52)에서 의심 47건, 확정 8건이었다.
확정 8건 모두 `temporal_positive=false`였다. 일부 확정 시 모델 점수는 0~0.07%였다.
시각별 정답 영상이 없으므로 이것이 전부 오탐이었다고 말할 수는 없다. 다만
학습 모델이 아닌 로컬 기하 조건으로 확정됐다는 것은 확인했다.

v4의 강한 하강+수평 자세, 또는 의심 진입 뒤 0.8초 수평 유지 조건은 모델 양성을
요구하지 않았다. 의도적으로 눕는 동작과 관절 좌표의 튐도 확정될 수 있었다.
위쪽 구도에서 영상 Y/몸통 각도는 실제 수직 낙하 높이와 다르다. 침대/바닥/의도를
구분하는 장면 이해 모델은 없다. 원본 Hailo 시간 분류기 평가 27클립은 우리 현장
전체 파이프라인의 정확도 보증이 아니다.

화면의 track/0% 문제는 `_ai_loop`에서 운영 track 저장 후 사용하지 않는 shadow
정리 코드가 같은 배열을 지우던 버그였다. 비활성 비교 경로는 운영 결과를 지우지
않도록 수정하고 실제 루프를 한 번 실행하는 회귀 테스트를 추가했다.

## 당시 정책: temporal-required-v5 (현재는 v6)

- Hailo YOLOv8s-Pose HEF, EdgeFall Hailo MLP 가중치, 48프레임/15Hz 시간축 유지.
- 최종 확정은 **모델 양성 AND 움직임·자세 후보**가 모두 필요하다.
- 모델 기준: 점수 약 0.75 이상, 3회 연속 평가. 약 0.2초마다 평가하며 3개 연속
  영상 프레임을 의미하지 않는다. 점수는 교정된 실제 사고 확률이 아니다.
- 기존 v4 기하 조건은 후보로 계산/표시하되 모델 미동의 시 확정하지 않는다.
- 양쪽 골반 평균↔한쪽 골반으로 가시성이 바뀌거나 pose가 사라지면 이전 속도
  기준과 미확정 후보를 초기화한다. 이미 확정된 경보는 이 이유로 해제하지 않는다.
- v5에서는 관절과 MLP feature를 직전 버전대로 유지했지만, 그 직전 버전의
  골반 Y 단위가 이미 잘못되어 있었다(v6에서 수정). 시간 모델에 별도 좌표
  smoothing이나 새 모델을 추가하지 않았다.
- 새 native ABI는 버전 2. 버전 검사가 오래된 `.so`를 거부한다.
- MQTT의 `fall_suspected`, `fall_confirmed`, `fall_cleared` 계약은 유지한다.
  details에 `confirmation_policy`, `decision_reason`, `geometry_candidate`,
  `motion_continuous`를 추가했다. broker 연결/전달 검증은 별도다.

중요: v5는 오탐 경로를 차단한 **검증용 보수적 조정**이지 정확도가 입증된 완성판이
아니다. 실제 낙상에서 MLP가 낮으면 확정되지 않는다. 이 경우 임계값을 임의로
낮추기 전에 pose 가시성·추적 연속성·입력 전처리와 학습 domain을 비교해야 한다.
현재 letterbox+Hailo postprocess와 upstream frontend의 차이도 후속 확인 대상이다.

## 화면에서 보는 것

| 표시 | 뜻 |
|---|---|
| 동작 후보 · 모델 미동의 | 기하 조건은 충족했지만 MLP 연속 양성은 아님 |
| 움직임 의심 · 확정 전 | 하강/자세 후보 단계 |
| 모델 양성 · 동작 조건 미충족 | 모델 점수만으로 확정하지 않음 |
| 관절 다시 연결 · 속도 판정 보류 | 골반 가시성이 바뀌어 속도 기준을 새로 잡음 |
| 모델·동작 조건 모두 충족 | 새로운 확정 이벤트 |
| 확정된 경보 유지 중 | 이미 발생한 경보의 유지/회복 단계 |

노란 의심과 빨간 확정은 구분한다. 과거 확정은 화면 기록에 남고, 기록 확인 버튼은
MQTT 경보 취소가 아니다. 얼굴 등록 화면/모델은 변경하지 않았다.

## Dahua LED 플리커

조회 모델: IPC-HFW4431R-Z. 주간/야간/일반 및 기존 임시 프로필의
`AntiFlicker=0`(Outdoor)을 `2`(60Hz)로 바꾸고 GET으로 재확인했다.
1080p H.264 15 FPS, 비트레이트, 수동 셔터/노출 모드는 변경하지 않았다.
적용 후 사용자가 줄무늬 소실을 확인했다. 다시 나타나면 1/120초 셔터와 다른
광원의 A/B 비교를 진행한다. LED PWM에 따라 60Hz 설정만으로 충분하지 않을 수 있다.

스크립트는 기본 dry-run이며, 변경 전 anti-flicker 값만 백업한다. 자격증명은
기존 설정에서 읽고 출력/백업하지 않는다.

```sh
cd /home/pi/Home-Safety-System
PYTHONPATH=src .venv/bin/python scripts/dahua_flicker.py
PYTHONPATH=src .venv/bin/python scripts/dahua_flicker.py --apply
```

이번 변경 복구(필요할 때만):

```sh
PYTHONPATH=src .venv/bin/python scripts/dahua_flicker.py --apply --restore runtime/diagnostics/camera-backups/20261019T123106779546Z.json
```

근거: [Dahua 공식 줄무늬 해결 안내](https://dahuatac.zendesk.com/hc/en-gb/articles/12639291029650-Image-Flicker-or-Stripe),
[Dahua API 문서](https://snr.systems/site/data-files/Dahua/IP_camera/DAHUA_HTTP_API_FOR_IPC%26SD-V1.40.pdf).

## 판정 근거 기록

`runtime/diagnostics/dahua-edgefall.jsonl`에 분석한 프레임마다 아래 정보를 기록한다.

- UTC ISO 시각, monotonic 시각, 프레임 번호, 프레임 크기
- 사람 박스, 17개 관절의 좌표/신뢰도 (얼굴 특징·이미지·RTSP 계정 없음)
- track ID/age/missed/valid, 점수, 모델 양성, 기하 후보, 결정 이유
- 하강 속도·거리·몸통 각도, 입력 age, 추론 시간, 오류

별도 thread와 256개 제한 queue를 사용한다. 저장이 밀리면 AI를 기다리게 하지 않고
기록을 드롭하며 API/UI의 누락 건수에 표시한다. 파일은 20 MB x 3개(약 60 MB)로
순환하므로 오래된 기록은 덮어쓴다. 시간별/사람별 기록률에 따라 보존 시간이 다르다.
동일 프레임을 AI에 다시 넣지 않으며 영상 인코딩/저장은 추가하지 않았다.

기존 100개 이벤트와 v4 실행 파일은 로컬
`runtime/fall-tuning-backup.fqg1JE/`에 보존했다. 이 디렉토리 및 진단 파일은 Git 제외.
이전 ABI와 새 Python은 서로 호환되지 않으므로 `.so`만 단독 롤백하면 안 된다.
이전 코드/실행 파일을 함께 복구해야 한다. 기준 Git commit은 `0029f09`다.

## 검증 및 사용자가 할 시험

- native 후보+모델 양성 확정, 후보만/모델만 확정 금지, 중복 확정 방지
- 골반 가시성 전환 시 가짜 하강 차단
- 실제 AI 루프에서 운영 track 보존
- 진단 로그 회전/flush/기록 오류 후 지속
- 기존 얼굴/Pi4 계약과 UI 회귀 검사
- 실제 Chromium에서 두 스트림 렌더링, 후보/확정 안내, 모바일 가로 넘침 검사
  (브라우저 모의 상태만 사용, 실제 MQTT 시험 경보 발행 없음)

배포 직후 무인 상태 실측: 입력 약 15 FPS, Pose 약 13.7 FPS, 평균 약 16.7 ms,
p95 약 26.7 ms. 로그 누락/오류 없음. 사람이 있는 조건의 낙상 정확도는 아직
검증하지 않았다. 당시 Pi4 MQTT는 연결되지 않아 소리 전달은 확인하지 못했다.

다음 현장 시험은 페이지 새로고침 후, 걷기/앉기 → 천천히 눕기 → 안전한 연기 낙상
순서로 한다. 각 행동의 대략적인 시각과 노란 후보/빨간 확정 여부를 남긴다. 일부러
강하게 넘어질 필요는 없으며 매트와 보조자를 이용한다. 실제 낙상인데 노란색에
머물면 모델 점수와 관절 누락을 로그로 재생 비교한다. 얼굴 등록은 그대로 사용한다.

재현 빌드와 자동 테스트:

```sh
./scripts/setup_edgefall_shadow.sh --source /home/pi/Home-Safety-System/runtime/vendor/edgefallkit --offline
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
```

설치 스크립트는 실행 중인 `.so`를 덮어 쓰지 않고 새 파일을 원자적으로 교체한다.
새 코드를 운영 프로세스에 로드하려면 `sudo systemctl restart smarthome-vision`이 필요하다.
