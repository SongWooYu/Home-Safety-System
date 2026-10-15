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
