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
itself. A candidate must first show rapid descent and must then retain a
horizontal pose, sufficient hip drop and temporal confirmation for the
configured confirmation window.
