# TC-CAM-003 rpicam 영상 저장 테스트

## 목적
rpicam-vid 명령으로 640x480, 15FPS 영상을 저장할 수 있는지 확인한다.

## 테스트 명령어
```bash
rpicam-vid --nopreview --width 640 --height 480 --framerate 15 -t 5000 -o captures/test_640x480_15fps.h264
ls -lh captures/test_640x480_15fps.h264
기대 결과
captures/test_640x480_15fps.h264 파일이 생성되어야 한다.
실제 결과
h264 파일 생성 확인
판정
 PASS
 FAIL
