# AGENTS.md

## Project context

Read `docs/HAILO_EDGEFALL_PRODUCTION_2026-10-19.md` before changing the active
Raspberry Pi vision/fall-detection pipeline, and
`docs/EDGEFALL_FEATURE_UNITS_2026-10-19.md` for the current v6 input contract. Read
`docs/FALL_DETECTION_ML_HANDOFF.md` only for the retired YOLO11/GRU research
history.

## Current fall model

The only production path since 2026-10-19 is:

```text
Hailo Model Zoo v2.15 YOLOv8s-Pose HEF
-> EdgeFallKit Hailo tracker
-> 48-frame Hailo temporal MLP
-> patched fall state machine
-> standard fall_* MQTT events
```

Do not restore YOLO11 NCNN, RuleFallDetector, or the B76 GRU into runtime.
They remain documented research history only.
The frozen Hailo MLP's hip-Y feature uses 640-space pixels (training mean about
301–319), while geometric thresholds use normalized 0..1 Y. Keep those inputs
separate. Never normalize both together or assume their units match.
Read
`docs/HAILO_EDGEFALL_PRODUCTION_2026-10-19.md` before changing this path.

## Camera roles

```text
Dahua 192.168.1.64
  primary fall camera

Camera Module 3
  face enrollment / local face recognition
  secondary view / optional verification
```

The ABKO APC720 was retired from the active system on 2026-10-15. Do not
reintroduce a V4L2 webcam path unless the user explicitly changes the hardware
plan. Do not require Camera Module 3 agreement before raising a Dahua fall
alert.

## Runtime constraints

The Hailo EdgeFall profile expects a 48-frame sequence at 15 FPS. Keep Dahua
latest-frame semantics and do not stretch this sequence with duplicate frames.

## Repository hygiene

Do not commit:

```text
AI Hub raw video
pose cache
GRU train/val/test NPZ datasets
large generated prediction dumps
```

Keep research scripts/results under:

```text
research/fall_detection/
```

Keep runtime code under:

```text
src/smarthome_vision/
```

## Evaluation

Current metrics are development metrics, not final untouched-test claims.

Prioritize:

```text
event recall
detection latency
false alarms
camera/view robustness
```

over window accuracy alone.

## Hailo EdgeFall deployment

The production Dahua path is:

```text
YOLOv8s Pose v2.15 HEF
-> metadata-only EdgeFallKit tracker
-> Hailo-specific 48-frame temporal MLP
-> EdgeFallKit state machine
```

It publishes MQTT using the existing Pi4 contract. Build its Git-ignored
runtime artifacts with:

```bash
./scripts/setup_edgefall_shadow.sh --accept-upstream-license
```

See `docs/HAILO_EDGEFALL_PRODUCTION_2026-10-19.md`. Do not feed the EdgeFallKit
Hailo temporal weights from a different pose frontend or HEF version.
