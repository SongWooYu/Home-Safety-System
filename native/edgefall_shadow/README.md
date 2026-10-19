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
It consumes Hailo pose metadata only. It does not open RTSP or publish MQTT;
the Python adapter owns the production `fall_*` MQTT contract. Since
2026-10-19 this Hailo/EdgeFall path is the active alarm path and the former
Rule/GRU runtime is retired.

`strict_confirmation.patch` is a local deployment policy layered on the pinned
source. Current profile is `units-separated-v6`, ABI version 2. It normalizes
hip Y for geometry ONLY; the frozen Hailo MLP expects pixel hip Y, not 0..1.
`temporalFrameFrom()` supplies the 640-space pixel value to feature 51 because
the frozen scaler's bin means are about 301–319. Native feature-contract and
tracker/classifier parity tests guard this distinction. The v5 profile mistakenly
sent normalized Y to both consumers and missed all events in the user's trial.
The policy still requires BOTH a learned temporal positive and a geometric
candidate for every new fall event. Temporal output alone cannot alert either.

Earlier v3/v4 impact and 0.8-second horizontal-persistence paths bypassed the
temporal gate. The observed 8 recent confirmed events were all temporal-negative;
these were not proof of successful learned classification. Those paths are now
diagnostic candidates only unless the temporal gate also agrees. Do not call
these geometry conditions high-specificity without a labeled evaluation.

A missing pose or a change in visible hip support resets unconfirmed motion
evidence. It never silently clears an already confirmed alarm. Raw pose features
and the learned weights/75% threshold remain unchanged. The bridge exposes
`geometry_candidate` and `motion_continuous`; Python adds decision explanations.
An ABI version check rejects older libraries instead of reading mismatched structs.

Historical `shadow` path/function names remain for reproducible builds, not a
second inference pipeline. The installer replaces the library atomically so a
running service never maps a partially overwritten library. See
[the v6 report](../../docs/EDGEFALL_FEATURE_UNITS_2026-10-19.md) for limitations and tests.
