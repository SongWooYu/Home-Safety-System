# TC-CAM-002 rpicam 정지 이미지 저장 테스트

## 목적
rpicam-still 명령으로 Camera Module 3 이미지를 저장할 수 있는지 확인한다.

## 테스트 명령어
```bash
rpicam-still --nopreview -t 1000 -o captures/test.jpg
ls -lh captures/test.jpg
기대 결과
captures/test.jpg 파일이 생성되어야 한다.
실제 결과
captures/test.jpg 생성 확인
판정
 PASS
 FAIL
비고

원격 환경이므로 --nopreview 옵션을 사용함.

