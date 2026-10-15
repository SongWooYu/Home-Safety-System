# EdgeFallKit metadata bridge

This directory contains only the Home-Safety-System C ABI bridge. The setup
script links it with a pinned checkout of
[`suharvest/edgefallkit`](https://github.com/suharvest/edgefallkit), licensed
under Apache-2.0.

Pinned upstream commit:

```text
ef3bda2fd865fe6b80119fb1c896a63bfc4228ee
```

The generated library is written under `runtime/native/` and is not committed.
It consumes Hailo pose metadata only. It does not open RTSP, publish MQTT, or
change the active Rule/GRU alarm path.

`strict_confirmation.patch` is a local deployment policy layered on the pinned
source. It normalizes Hailo hip Y to the temporal model's `0..1` coordinate
contract and prevents a temporal-positive frame from creating a fall by
itself. The normal path requires rapid descent followed by horizontal posture,
sufficient hip drop and temporal confirmation. `windowed-impact-v3` also has a
high-specificity staged-impact path: a rapid descent (speed `>= 0.50/s` and
normalized hip drop `>= 0.04`) must be followed, within the existing 1.5-second
candidate window, by a horizontal final pose (torso angle `>= 65°` and box
aspect ratio `>= 1.50`). The cues do not have to peak on the same Hailo frame.
The bridge remains Shadow-only and never publishes MQTT.
