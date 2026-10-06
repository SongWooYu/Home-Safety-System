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

ABKO APC720
  face enrollment / local face recognition

Camera Module 3
  secondary view / optional verification
```

Do not require Camera Module 3 agreement before raising a Dahua fall alert.

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
