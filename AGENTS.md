# AGENTS.md

## Project context

Read `docs/FALL_DETECTION_ML_HANDOFF.md` before changing the Raspberry Pi vision/fall-detection pipeline.

## Current fall model

Use:

```text
models/fall_gru/b76_sqrt_ensemble/
```

Current deployment candidate:

```text
B_76_sqrt_3seed_ensemble
20 frames
10 FPS
76 features/frame
3 classes: normal / falling / fallen
3 independently trained GRUs
mean class probabilities
alert_score = P(falling) + P(fallen)
```

Do not replace it with the older single-seed `D_125_sqrt` model unless explicitly asked.

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

The temporal model was developed using pose features sampled at 10 FPS.

Do not feed 20 frames collected over 10+ seconds into a model trained for a 2-second window.

First verify whether Pi5 can sustain the required pose sampling rate.

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

## Fallback

Keep the existing rule-based fall detector available until the GRU runtime path is verified on Raspberry Pi 5.

## 2026-10-15 EdgeFallKit shadow

An experimental Hailo-only comparison path is available for the Dahua camera:

```text
YOLOv8s Pose v2.15 HEF
-> metadata-only EdgeFallKit tracker
-> Hailo-specific 48-frame temporal MLP
-> EdgeFallKit state machine
```

It is strictly Shadow-only and must not publish MQTT or trigger Pi4 audio until
field validation is accepted. Build its Git-ignored runtime artifacts with:

```bash
./scripts/setup_edgefall_shadow.sh --accept-upstream-license
```

See `docs/EDGEFALL_SHADOW_2026-10-15.md`. Do not feed the EdgeFallKit Hailo
temporal weights from a different pose frontend or HEF version.
