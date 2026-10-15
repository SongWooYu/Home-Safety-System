# EdgeFallKit Hailo Shadow — 2026-10-15

## Current status

The Raspberry Pi 5 now runs an isolated EdgeFallKit comparison path on the
Dahua camera:

```text
Dahua latest frame
  -> Hailo-8 YOLOv8s Pose, Model Zoo v2.15
  -> pose metadata only
  -> EdgeFallKit per-person tracker
  -> Hailo-specific 48-frame temporal MLP
  -> EdgeFallKit state machine
  -> Pi5 :8080 diagnostics only
```

This path does **not** publish MQTT and cannot trigger the Pi4 alarm. The
existing NCNN Rule detector and B76 GRU remain unchanged while the new path is
validated.

## Pinned artifacts

```text
EdgeFallKit commit:
ef3bda2fd865fe6b80119fb1c896a63bfc4228ee

YOLOv8s Pose HEF:
runtime/models/yolov8s_pose_v2_15_h8.hef

HEF SHA-256:
e19856699ed47cf866d23265827f960b263f287dab5e54e82c7ce37e12525a2d

Temporal profile:
edgefallkit-hailo8-yolov8s-pose-v1
```

The HEF and generated native library are kept under the Git-ignored `runtime/`
directory. No upstream model binary is committed.

## Why this works with HailoRT 4.23

The published EdgeFallKit container is locked to HailoRT 4.21.0. A direct
source build against this Pi's 4.23.0 runtime found one GStreamer tensor-meta
type change. After adapting that conversion in an isolated audit checkout, the
full native build and all six upstream tests passed.

The product integration avoids that dependency boundary entirely: the existing
HailoRT 4.23 GStreamer adapter produces pose dictionaries, and a tiny native
library receives only those pose values. The library links EdgeFallKit's
tracker, temporal classifier, weights and state machine; it does not link
HailoRT, decode RTSP or publish MQTT.

## Setup after a fresh clone

Review the upstream Hailo model terms, then run:

```bash
cd /home/pi/Home-Safety-System
./scripts/setup_edgefall_shadow.sh --accept-upstream-license
```

For an existing pinned checkout:

```bash
./scripts/setup_edgefall_shadow.sh \
  --source /path/to/edgefallkit \
  --offline
```

The setup verifies the HEF hash, checks the exact EdgeFallKit commit and builds:

```text
runtime/native/libedgefall_shadow.so
```

## First live measurement

Measured with the Pi5 development overlay open and both the old NCNN baseline
and the new Hailo path active:

```text
Hailo YOLOv8s effective FPS    10.52
Hailo mean inference           15.56 ms
Hailo p95 inference            21.40 ms
NCNN effective FPS              9.61
NCNN mean inference            33.88 ms
NCNN p95 inference             43.83 ms
```

The previous YOLOv8m Shadow was roughly 35 ms mean / 42 ms p95 in the observed
session, so v8s materially reduced pose latency. The combined Python comparison
loop still reaches only about 10.5 FPS rather than the EdgeFallKit training
rate of 15 FPS because NCNN and Hailo are both run sequentially for comparison.

One observed track produced a high temporal probability while `valid=false`
because shoulders/hips were not sufficiently visible. The EdgeFallKit state
remained `normal` and no event was raised. Probability alone must therefore not
be presented as an alarm.

## Dashboard

Open:

```text
http://<pi5-ip>:8080
```

The Hailo comparison panel now shows:

- exact HEF filename;
- Hailo FPS and latency;
- EdgeFall state;
- temporal probability;
- best person track ID.

The overlay label uses `EDGE #<track> <state> <probability>`. It remains a Pi5
development/exhibition overlay and is not placed on the clean WebRTC stream.

## Next gate

The next change should happen only after visual confirmation of v8s pose
coverage. To reach the model's 15 FPS reference domain, promote Hailo v8s to the
single primary pose backend and freeze the NCNN/B76 comparison path. Keep
EdgeFall in Shadow mode until staged-fall and 30-minute ADL results are recorded.
