# 자원 제약 기반 시스템 전면 재검토

기준일: 2026-09-17

## 1. 최종 결론

현재 장비로 졸업작품 시연은 가능하다. 다만 **학습, 실시간 AI 추론, 영상 인코딩,
DB·웹 서비스를 한 장치에 몰아넣으면 안 된다.** 권장 역할은 다음과 같다.

| 장치 | 맡길 일 | 맡기지 않을 일 |
|---|---|---|
| Mac mini M4 | 데이터 전처리, 전이학습, 평가, ONNX 내보내기 | 전시장 상시 서버 |
| Raspberry Pi 5 8 GB | 세 카메라 수집, 얼굴/pose/낙상 추론, 오버레이, 영상 제공 | 대규모 학습, 영구 DB |
| AI HAT+ Hailo-8 26 TOPS | 지원되는 INT8 모델의 실시간 **추론** | 모델 학습과 역전파 |
| Raspberry Pi 4 4 GB | MQTT, PostgreSQL, 자동화, 최종 웹, 경보 제어 | AI 추론, 영상 프록시·트랜스코딩 |

즉 권장 흐름은 **Mac에서 학습 → 호환 환경에서 Hailo 모델로 변환 → Pi5에서
추론 → Pi4에서 사건 저장과 경보**다. Hailo가 도착하기 전에는 Pi5 CPU에서
저주기 MVP를 유지하되 불필요한 카메라별 AI를 끈다.

## 2. 요구사항 재정의

### 필수 시연 기능

1. 웹캠 앞에서 한 사람을 정면·좌·우로 등록한다.
2. 특정 얼굴 구역에 들어온 사람을 등록자/미등록자로 구분한다.
3. Camera Module 3와 Dahua에서 사람과 낙상 위험을 감지한다.
4. 낙상 확정 사건을 MQTT로 Pi4에 전송한다.
5. Pi4가 DB 저장, 화면 경보, 스피커/부저 상태를 제어한다.
6. 운영자가 경보를 취소할 수 있다.

### 이번 범위에서 제외하거나 후순위로 둘 것

- Pi5에서 낙상 데이터셋 학습
- 세 카메라 모두에서 항상 얼굴 인식
- Pi4를 거치는 영상 프록시
- 모든 영상을 상시 녹화하거나 DB에 저장
- 다중 카메라 사람 재식별과 완전한 행동 분류
- 음성 인식과 LLM

## 3. 왜 Pi5에서 학습하면 안 되는가

Pi5 CPU에서도 작은 실험을 실행할 수는 있지만, 실제 낙상 데이터의 영상 디코딩,
augmentation, 역전파, 반복 평가를 수행하면 시간이 매우 길고 메모리·열·SD I/O를
지속적으로 사용한다. 동시에 현재 세 카메라 수집, NCNN 추론, JPEG 생성,
H.264 소프트웨어 인코딩까지 실행하므로 실시간 시연 서비스와 자원을 직접 경쟁한다.

Hailo-8 26 TOPS를 장착해도 이 결론은 바뀌지 않는다. Raspberry Pi 공식 문서는
AI HAT+의 TOPS를 **inference performance**로 설명하고, Hailo 문서도 Dataflow
Compiler가 **학습된 모델**을 Hailo-8 형식으로 최적화·변환한다고 설명한다.
따라서 Hailo는 학습 시간을 단축하는 GPU가 아니라 배포 후 추론을 가속하는 NPU다.

참고: [Raspberry Pi AI HAT+ 공식 문서](https://www.raspberrypi.com/documentation/accessories/ai-hat-plus.html),
[Hailo-8 제품 개요](https://hailo.ai/hailo-files/hailo-8-product-brief-en/)

## 4. Mac mini M4를 학습기로 사용하는 판단

Mac mini M4 기본형은 10코어 CPU, 10코어 GPU, 16코어 Neural Engine, 16 GB 통합
메모리와 기본 256 GB SSD 구성이다. PyTorch는 Apple silicon에서 MPS GPU 학습을
지원하고 Ultralytics도 YOLO 학습의 `device=mps` 경로를 제공한다. 따라서 Pi5보다
훨씬 적절한 학습 장치다.

다만 다음 제한을 전제로 한다.

- 16 GB 통합 메모리이므로 nano/small 모델, 작은 batch로 시작한다.
- 일부 PyTorch 연산은 MPS에서 미지원·저성능일 수 있어 CPU fallback이나 코드
  조정이 필요할 수 있다.
- 기본 256 GB SSD는 대규모 영상 원본, 추출 프레임, 캐시, 체크포인트를 함께 두기
  부족할 수 있다. 학습 데이터 작업용 외장 SSD를 Mac에 사용하는 것이 현실적이다.
- 이 외장 SSD는 취소한 “Pi 운영 USB” 계획과 별개이며 학습 작업 공간일 뿐이다.
- 호환 문제가 계속되거나 학습 시간이 너무 길면 마지막 수단으로 NVIDIA CUDA
  PC/학교 서버/단기 클라우드 GPU를 사용한다.

공식 근거: [Mac mini (2024) 사양](https://support.apple.com/en-in/121555),
[Apple의 PyTorch Metal 가속](https://developer.apple.com/metal/pytorch/),
[Ultralytics 학습 문서](https://docs.ultralytics.com/modes/train/)

## 5. AI Hub 낙상 데이터 검토

예시로 제시된 AI Hub `71641`은 낙상사고 위험동작 영상-센서 쌍 데이터다.
공식 설명 기준으로 영상 약 22,672개와 이미지 약 226,720개, 8개 카메라 방향,
전방·후방·측방 낙상과 비낙상 데이터를 포함한다. JSON에는 BBOX, keypoint,
`fall_start_frame`, `fall_end_frame`, 배우 ID와 카메라 번호 등이 있어 pose 기반
시간 모델에 유용하다.

그러나 바로 내려받아 학습할 수 있다고 전제하면 안 된다.

- 보건의료 데이터로서 신청·심사와 보안 구역 절차가 안내되어 있다.
- 연구계획, 소속 확인, 경우에 따라 IRB 관련 서류가 필요하다.
- 영상 전처리에 시간이 많이 걸린다고 데이터 페이지 자체가 경고한다.
- 공개 데이터의 촬영 각도·환경과 실제 전시 공간 사이에 domain gap이 있다.
- 프레임을 무작위 분리하면 같은 사람·같은 영상이 train/test에 섞여 성능이
  과대평가될 수 있다.

따라서 우선 데이터 이용 가능 여부를 확인하고, 배우 ID 기준으로 train/validation/
test를 분리한다. 카메라 번호별 성능도 따로 보고, 마지막에는 실제 전시장 카메라로
동의받아 촬영한 소량의 연기 데이터로 별도 시험한다.

출처: [AI Hub 낙상사고 위험동작 영상-센서 쌍 데이터](https://www.aihub.or.kr/aihubdata/data/view.do?dataSetSn=71641)

## 6. 권장 낙상 모델 구조

### 6.1 단일 프레임 낙상 detector만 쓰지 않는 이유

사람이 누워 있는 한 장면만 보면 실제 낙상, 바닥에 앉기, 몸 숙이기, 카메라 원근을
구분하기 어렵다. 현재 “앉은 자세를 낙상으로 판정”한 문제도 이 한계와 연결된다.
낙상은 자세뿐 아니라 직립에서 급격히 내려가는 **시간 변화**가 핵심이다.

### 6.2 권장 2단계 파이프라인

```text
프레임
  -> 사람 pose/keypoint 추론
  -> 사람별 tracking
  -> 1~3초 keypoint 시퀀스 정규화
  -> 경량 시간 분류기
  -> 의심/확정/해제 상태 머신
  -> MQTT event
```

1단계는 사람의 keypoint를 구한다. 2단계는 LSTM/TCN/작은 1D CNN 또는 특징 기반
분류기가 여러 프레임의 높이 변화, 몸통 각도, 관절 속도, 바닥 체류 시간을 본다.
마지막 상태 머신이 짧은 오탐을 제거한다.

이 방식의 장점:

- 단일 이미지 detector보다 앉기와 넘어짐을 구분하기 쉽다.
- 시간 분류기는 작아서 Pi5 CPU에서도 실행 가능하다.
- Hailo 도착 후 가장 무거운 pose 추론만 NPU로 옮길 수 있다.
- keypoint 중심 데이터는 원본 영상보다 저장·학습·개인정보 부담이 작다.
- AI Hub의 keypoint와 낙상 시작/종료 annotation을 활용하기 좋다.

### 6.3 모델 크기 전략

- 처음부터 새 모델을 학습하지 않고 사전학습 pose 모델을 전이 사용한다.
- 먼저 pose 모델은 고정하고 keypoint 시퀀스 분류기만 학습한다.
- 전시장 미탐 원인이 pose 자체라면 그때 pose fine-tuning을 검토한다.
- Hailo Model Zoo 또는 Raspberry Pi/Hailo 예제에서 실제 Hailo-8 호환 pose 모델을
  먼저 선택하고, 그 출력 형식에 시간 분류기를 맞춘다.
- 현재 YOLO11n-pose NCNN을 Hailo에서 그대로 실행할 수 있다고 가정하지 않는다.

## 7. 학습과 배포 파이프라인

```text
AI Hub/자체 데이터
  -> Mac: 권한 확인, 추출, 정제, actor 기준 분할
  -> Mac: pose 추출 또는 fine-tuning
  -> Mac: 시간 분류기 학습과 평가
  -> ONNX export
  -> 호환되는 Ubuntu x86 빌드 환경: Hailo DFC로 INT8 양자화/HEF 생성
  -> Pi5 + HailoRT: 실시간 추론
```

Hailo Model Zoo는 Hailo-8/Hailo-8L용 브랜치와 Dataflow Compiler 버전 호환을
별도로 안내한다. macOS에서 HEF 변환까지 무조건 된다고 전제하지 말고, Hailo-8에
맞는 DFC/HailoRT 조합을 고정한 Ubuntu x86 환경이나 공식 컨테이너를 준비한다.

출처: [Hailo Model Zoo](https://github.com/hailo-ai/hailo_model_zoo)

저장소에는 대규모 데이터셋을 커밋하지 않는다. 다음만 버전 관리한다.

- 데이터 변환 스크립트와 데이터셋 YAML
- 학습 설정, seed, 패키지 버전
- 실험 지표와 confusion matrix
- 배포 모델의 버전·해시·라이선스
- 크기가 허용되는 최종 artifact 또는 별도 Release/LFS 위치

## 8. 얼굴 인식 범위 재조정

현재 전역 `face_recognition.enabled` 때문에 등록 가능 여부와 별개로 모든 카메라
worker에서 얼굴 분석이 실행될 수 있다. 요구사항은 웹캠 등록과 특정 구역 구분이므로
다음과 같이 카메라별 옵션을 추가하는 것이 합리적이다.

| 카메라 | 얼굴 등록 | 얼굴 인식 | 낙상 |
|---|---:|---:|---:|
| ABKO 웹캠 | 켬 | 켬, 얼굴 구역 안에서만 | 끔 |
| Camera Module 3 | 기본 끔 | 끔 | 켬 |
| Dahua | 끔 | 끔 | 켬 |

Camera Module 3도 예비 등록기로 남기고 싶다면 관리자 설정에서만 켠다. 세 카메라의
먼 얼굴을 0.5 FPS로 계속 분석하는 것보다 웹캠의 등록 구역만 처리하는 편이 CPU,
개인정보, 오인식 측면에서 낫다.

등록자는 정면·좌·우 템플릿을 유지하되 다음 개선 순서가 적절하다.

1. 흐림·밝기·얼굴 크기 품질 검사를 통과한 프레임만 등록
2. 각도별 1개가 아니라 우수한 embedding 2~3개 보존
3. 웹캠 얼굴 구역 안의 사람만 등록/인식
4. tracker ID와 얼굴 결과를 일정 시간 결합
5. 실제 참여자로 false accept/false reject를 함께 측정

## 9. Pi5 추론 자원 재배치

### Hailo 도착 전

- Camera Module 3, Dahua: 사람/pose/낙상만 실행
- 웹캠: 얼굴 등록/인식만 실행; 일반 객체와 낙상은 끔
- pose 1~2 FPS, 객체 3~5 FPS 범위에서 시작
- 개발 화면과 WebRTC/HDMI를 동시에 상시 실행하지 않음
- H.264 publisher는 시청 중에만 실행

### Hailo 도착 후

1. Active Cooler를 장착하고 AI HAT+를 설치한다.
2. Raspberry Pi 공식 패키지와 `hailortcli`로 장치를 확인한다.
3. 공식 pose/detection 예제를 한 카메라에서 먼저 측정한다.
4. 두 낙상 카메라를 Hailo batch/multi-stream에 연결한다.
5. CPU에는 캡처, tracker, 시간 분류기, MQTT, UI만 남긴다.
6. 그 뒤에야 해상도나 AI FPS를 올린다.

26 TOPS는 지원 모델의 처리량을 높이지만, 카메라 디코딩, OpenCV, JPEG/H.264 인코딩,
브라우저 렌더링과 네트워크를 자동으로 가속하지 않는다. 따라서 현재 영상 버벅임이
Hailo 장착만으로 전부 사라진다고 기대하면 안 된다. AI 추론 부하는 크게 줄겠지만
영상 경로는 별도로 계속 관리해야 한다.

## 10. 영상 표시 운영 정책

### 전시 당일 권장

가장 안정적인 방식은 Pi5 `HDMI-A-2`에 시연 화면을 직접 띄우고, Pi4는 경보·DB·
서비스 화면만 담당하는 것이다. 단, 로컬 화면도 기존 MJPEG 세 개를 계속 생성하면
Pi5 CPU를 사용하므로 다음 중 하나만 주 영상으로 선택한다.

1. **권장:** Pi5 로컬 WebRTC/H.264 또는 최적화된 단일 전시 화면
2. 개발 시: Pi5 `:8080` MJPEG
3. 원격 시연 시: PC 브라우저가 Pi5 WebRTC 직접 수신

동시에 여러 브라우저에서 세 MJPEG와 세 WebRTC를 열지 않는다. 사람 등록이 필요할
때만 개발/등록 패널을 열고, 시연 중에는 이벤트 목록의 갱신 주기도 느리게 유지한다.

### 네트워크 원칙

- Dahua는 공유기에 유선으로 유지한다.
- Pi5와 전시 브라우저는 가능하면 5 GHz Wi-Fi를 사용한다.
- Pi5 `.20`, Pi4 `.10`, Dahua `.64`는 DHCP 예약 또는 충돌 없는 고정 주소로 관리한다.
- MJPEG와 WebRTC를 같은 카메라에서 중복 시청하지 않는다.
- 외부 포트포워딩은 하지 않는다.
- 끊김 시험은 FPS뿐 아니라 Wi-Fi 신호, packet loss, Pi 온도, CPU, 송신 대기열을
  함께 기록한다.

## 11. Pi4 4 GB 역할 검토

Pi4 4 GB는 MQTT, PostgreSQL, 소규모 Flask/Gunicorn, automation을 실행하기에
충분한 편이다. 현재 Compose 구조도 영상 바이트를 받지 않기 때문에 합리적이다.
Pi4의 역할을 줄이기보다 **제어 평면으로 고정**하는 것이 좋다.

```text
Pi5 data plane: 카메라 -> AI -> 영상/사건
Pi4 control plane: MQTT -> DB -> 상태/경보 -> 웹/스피커
```

Pi4 운영 조건:

- DB에는 사건과 최신 상태만 저장하고 연속 영상은 저장하지 않는다.
- Docker 로그 크기와 PostgreSQL 보존 기간을 제한한다.
- WebRTC 영상은 브라우저가 Pi5에서 직접 받는다.
- Grafana, 대형 로그 수집기, 영상 녹화 서버는 추가하지 않는다.
- swap 사용, 메모리, SD 쓰기량을 장시간 시험한다.
- 전시 전 Pi4/Pi5 동시 재부팅 후 3분 이내 복구를 검증한다.

Pi4 자체 브라우저를 전시 모니터로 쓰면 H.264 디코딩 자원은 여전히 Pi4가 쓴다.
큰 모니터가 Pi5에 연결된다면 Pi4는 브라우저까지 맡지 않아도 된다.

## 12. 데이터와 개인정보

- 얼굴 원본 이미지는 저장하지 않고 embedding만 Pi5 로컬에 둔다.
- embedding도 생체정보로 취급하고 등록 동의와 삭제 경로를 제공한다.
- 낙상 학습 원본과 추출 프레임은 Mac 학습 저장소에만 두고 Git/Pi SD에 넣지 않는다.
- 운영 DB에는 사건 시간, 카메라, 상태, 신뢰도와 필요한 소량 metadata만 저장한다.
- 사건 snapshot이 꼭 필요할 때만 동의, 보존 기간, 자동 삭제를 먼저 정의한다.
- 공개 데이터의 이용 조건과 AI Hub 승인 범위를 기록한다.

## 13. 평가 기준

frame mAP 하나만으로 낙상 시스템을 평가하지 않는다.

| 지표 | 의미 |
|---|---|
| event recall | 실제 연기한 낙상을 몇 건 잡았는가 |
| event precision | 발생한 낙상 경보 중 실제 낙상 비율 |
| false alarms/hour | 앉기·숙이기·바닥 작업 중 시간당 오경보 |
| detection latency | 넘어지기 시작부터 경보까지 걸린 시간 |
| recovery accuracy | 사람이 일어났거나 취소했을 때 정상 해제되는가 |
| camera-angle result | Camera Module 3와 Dahua 방향별 성능 |

검증 데이터는 같은 영상 프레임이 학습과 시험에 섞이지 않게 actor/video 단위로
분리한다. 전시장에서는 정면·측면 낙상, 앉기, 물건 줍기, 바닥에 천천히 눕기,
부분 가림을 각각 여러 번 시험한다.

## 14. 단계별 실행 계획

### 단계 A — 현재 안정화

- 현재 CPU MVP를 기준 버전으로 태그
- Pi4 최신 clone/install과 MQTT/DB 왕복 시험
- 웹캠은 얼굴만, Camera Module 3/Dahua는 낙상만 처리하도록 카메라별 스위치 구현
- 실제 스피커/부저 subscriber 구현
- Pi5와 Pi4 2시간 통합 부하 시험

완료 기준: 세 카메라 온라인, 사건 1회 저장, 경보/취소, 재부팅 자동 복구.

### 단계 B — 데이터 준비

- AI Hub 이용 승인 조건 확인
- Mac 학습 디렉터리와 외장 SSD 결정
- annotation 변환, actor 기준 split, keypoint 추출 스크립트 작성
- 실제 전시장 동작의 동의 기반 소규모 검증 세트 준비

완료 기준: 재현 가능한 dataset manifest와 누수 없는 train/val/test.

### 단계 C — Mac 기준 모델

- 현재 규칙을 baseline으로 수치화
- keypoint 시퀀스 분류기부터 학습
- 앉기/숙이기 hard negative를 추가
- ONNX export와 CPU 추론 결과 일치 확인

완료 기준: 규칙보다 false alarms/hour가 낮고 낙상 event recall이 개선됨.

### 단계 D — Hailo 통합

- AI HAT+와 Active Cooler 장착
- HailoRT/공식 pose 예제 검증
- 버전이 맞는 DFC 환경에서 HEF 생성
- 두 낙상 카메라 동시 처리량·온도·지연 측정
- 기존 NCNN 경로를 fallback으로 유지

완료 기준: 목표 FPS에서 2시간 동안 throttling·재시작 없이 동작.

### 단계 E — 전시 고정

- HDMI-A-2 또는 원격 WebRTC 중 주 화면 하나를 결정
- 얼굴 등록, 낙상, 경보, 취소의 3분 시연 순서 확정
- 네트워크 장애와 모델 장애 시 복구 절차 인쇄
- 실명·비밀번호·RTSP URL이 화면/로그에 노출되지 않는지 확인

## 15. 지금 바로 결정된 변경 방향

문서 기준으로 다음 변경은 타당하지만, 이번 재검토에서는 운영 코드를 즉시 바꾸지
않고 다음 구현 단계의 작업으로 남긴다.

1. `face_recognition`을 카메라별로 켜고 웹캠에만 적용
2. 웹캠의 `fall_detection`을 끄고 Camera Module 3/Dahua만 사용
3. 웹캠 얼굴 등록 구역(ROI) 추가
4. 연속 영상 대신 keypoint 시퀀스 기반 낙상 분류기 인터페이스 추가
5. Hailo/NCNN backend를 설정으로 선택할 수 있게 유지
6. Pi4 DB/log retention과 실제 alarm subscriber 구현

## 16. 위험과 대안

| 위험 | 영향 | 대응 |
|---|---|---|
| AI Hub 승인·다운로드 지연 | 학습 일정 지연 | 공개 소형 데이터/자체 연기 데이터로 파이프라인 먼저 구현 |
| MPS 연산 호환 문제 | Mac 학습 실패·저속 | 작은 모델, CPU fallback, 최종적으로 CUDA 서버 |
| 모델의 Hailo 변환 실패 | NPU 배포 지연 | Hailo 지원 pose 모델을 먼저 선택, NCNN fallback 유지 |
| Wi-Fi 혼잡 | 원격 영상 끊김 | HDMI-A-2 로컬 시연, 5 GHz, 영상 경로 하나만 사용 |
| 앉기·숙이기 오탐 | 시연 신뢰도 저하 | 시간 모델, hard negative, 지속 시간, 운영자 취소 |
| 멀리 있는 얼굴 오인식 | 등록자 구분 실패 | 웹캠 ROI, 품질 필터, 다각도 embedding, tracker 결합 |

## 17. 최종 권고

지금 Pi4 계획을 폐기할 필요는 없다. Pi4는 제어 서버로 적합하고, Pi5는 AI 영상
노드로 분리하는 현재 큰 방향이 맞다. 바꿔야 할 것은 Pi5의 모든 카메라에 모든 AI를
적용하던 방식과 Pi5에서 학습까지 하려는 구상이다.

졸업작품의 성공 가능성을 가장 높이는 순서는 다음과 같다.

1. 현재 전체 사건 흐름을 Pi4까지 먼저 완성한다.
2. 얼굴은 웹캠 구역, 낙상은 두 시연 카메라로 연산을 분리한다.
3. Mac mini M4에서 pose 시퀀스 낙상 모델을 학습한다.
4. Hailo가 오면 학습이 아니라 pose 추론 가속에 사용한다.
5. 전시 당일에는 Pi5 HDMI 화면을 우선하고 네트워크 영상은 보조로 둔다.
