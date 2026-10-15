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
edgefallkit-hailo8-yolov8s-pose-v1+strict-motion-v2
```

The HEF and generated native library are kept under the Git-ignored `runtime/`
directory. No upstream model binary is committed.

## First live ADL findings and strict policy correction

The first operator check found the following behavior:

- ordinary movement and sitting: no fall;
- slow bending: no fall;
- fast bending: false fall;
- lying down: usually classified as a fall.

Code inspection found two causes in the pinned Raspberry Pi Hailo adapter.
First, hip Y was passed to a model trained on normalized `0..1` coordinates as
a `0..640` pixel value. This placed the temporal classifier far outside its
training distribution. Second, a temporal-positive result could transition
directly from `normal` to `fallen`, without any preceding rapid descent or
persistent horizontal posture.

The Home-Safety-System build now applies a reproducible local policy patch:

1. normalize hip Y before both motion thresholds and the temporal MLP;
2. never allow temporal output alone to originate a fall;
3. arm only after rapid downward motion plus a horizontal cue;
4. normally confirm only when temporal-positive, horizontal torso **and** box,
   minimum hip-drop distance, evidence count and confirmation time all agree;
5. additionally confirm an exceptionally strong impact before track loss when
   speed is at least `0.75/s`, normalized hip drop is at least `0.05`, torso
   angle is at least `65°`, and box aspect ratio is at least `1.50`.

This is a stricter derivative policy, so upstream EdgeFallKit accuracy figures
must not be claimed for it. It remains Shadow-only and sends no MQTT alarm
until staged falls and ADL are measured again.

### Operator retest

Open `http://<pi5-ip>:8080`, keep the Dahua overlay visible, and judge only the
`EdgeFall` state/profile. The older Rule and B76 GRU fields are comparison
outputs and may disagree.

Run each action five times after the profile shown by the API/dashboard becomes
`edgefallkit-hailo8-yolov8s-pose-v1+strict-motion-v2`:

- ordinary walking and standing;
- sitting on a chair;
- slow bend and return upright;
- fast bend and return upright;
- deliberate slow lie-down;
- staged rapid fall with the existing mat and assistant.

The first five actions must produce no `fallen` transition. A staged fall may
move through `suspected` or directly reach `fallen` through the strong-impact
path; otherwise this policy is trading too much recall for false-positive
reduction and must remain Shadow-only.

### Second staged-fall finding

Repeated rapid falls onto the bed reached `suspected` but returned to `normal`.
The learned temporal probability peaked around `0.17`, far below its frozen
`0.75` threshold for three consecutive evaluations. One clear attempt still
showed strong geometry (`1.99/s` hip speed, `0.062` hip drop, `68°` torso,
`1.67` aspect ratio), but the person was reassigned from track `#1` to `#2`
before confirmation. Lowering the learned threshold would also admit observed
ADL false positives, so strict-motion-v2 adds only the high-specificity
strong-impact path described above. It remains Shadow-only pending live retest.

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

After the first operator test, this was replaced by a large fixed
`EDGEFALL SHADOW` status bar plus a larger per-track label. The legacy yellow
`FALL SUSPECTED` and red `FALL CONFIRMED` bars are Rule detector output, not
EdgeFall output.

EdgeFall transitions are now recorded as local-only events named
`fall_edgefall_*` and as `EDGEFALL_SHADOW_TRANSITION` lines in the systemd
journal. Both explicitly set `published_to_mqtt=false`; this observability
change does not promote EdgeFall out of Shadow mode.

## Next gate

The next change should happen only after visual confirmation of v8s pose
coverage. To reach the model's 15 FPS reference domain, promote Hailo v8s to the
single primary pose backend and freeze the NCNN/B76 comparison path. Keep
EdgeFall in Shadow mode until staged-fall and 30-minute ADL results are recorded.
