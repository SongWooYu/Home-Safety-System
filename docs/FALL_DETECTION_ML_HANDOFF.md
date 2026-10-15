# Fall Detection ML / Vision Handoff

> **2026-10-15 hardware override:** ABKO APC720 is retired. Camera Module 3 now
> owns face enrollment and recognition. All later ABKO role references in this
> historical handoff describe the pre-retirement configuration and must not be
> used to recreate the active V4L2 path.

> Project: `SongWooYu/Home-Safety-System`  
> Updated: 2026-10-06  
> Purpose: authoritative handoff for ChatGPT, Codex, coding agents, and future maintainers.  
> Scope: AI Hub fall-detection research, Mac training workspace, promoted deployment artifacts, camera roles, Raspberry Pi 5 integration plan.

---

## 1. Read this first

The project currently has **two intentionally separate local workspaces**:

```text
~/Projects/
├── home-safety-ml/       # research / dataset / training / evaluation
└── Home-Safety-System/   # actual product / graduation-project Git repository
```

Do **not** merge the entire `home-safety-ml` workspace into the product repository.

The current deployment candidate is **not** the earlier single-seed `D_125_sqrt` model.

The current prototype candidate is:

```text
B_76_sqrt_3seed_ensemble
```

which means:

```text
76-feature temporal input
+ sqrt inverse class weighting
+ three independently trained GRUs
+ arithmetic mean of class probabilities
```

The three ensemble members are:

```text
models/fall_gru/b76_sqrt_ensemble/seed_42/best.pt
models/fall_gru/b76_sqrt_ensemble/seed_123/best.pt
models/fall_gru/b76_sqrt_ensemble/seed_2026/best.pt
```

---

## 2. Why this model was selected

Earlier single-seed experiments suggested that:

```text
D_125_sqrt
= 125 dynamic features
+ sqrt inverse class weighting
```

was best.

However, multi-seed experiments using:

```text
seed = 42
seed = 123
seed = 2026
```

showed that `D_125_sqrt` was not stable enough at the event operating-point level.

The simpler:

```text
B_76_sqrt
= 76 features
+ sqrt inverse class weighting
```

was therefore trained with three seeds and combined by averaging probabilities.

The B ensemble gave the most practical development-time score stability and event robustness.

### Ensemble definition

For each 20-frame window:

```text
model_42  -> softmax P(normal/falling/fallen)
model_123 -> softmax P(normal/falling/fallen)
model_2026-> softmax P(normal/falling/fallen)

mean_prob = arithmetic mean of the three class-probability vectors

alert_score =
    mean_prob[falling]
    +
    mean_prob[fallen]
```

---

## 3. Current temporal model specification

```text
Name             B_76_sqrt_3seed_ensemble
Task             temporal fall-state classification
Classes          normal / falling / fallen
Sequence         20 frames
Sampling rate    10 FPS
Temporal window  approximately 2 seconds
Feature dim      76
GRU hidden       128
GRU layers       2
Dropout          0.2
Weighting        sqrt inverse-frequency
```

### 76 frame features

17 COCO joints:

```text
17 × [
    bbox-relative x,
    bbox-relative y,
    keypoint confidence,
    valid mask
]
= 68
```

Global features:

```text
bbox center x
bbox center y
bbox width
bbox height
log(height / width)
bbox confidence
frame valid
visible keypoint ratio

= 8
```

Total:

```text
68 + 8 = 76
```

---

## 4. Promoted model metadata

The product repository contains:

```text
models/fall_gru/b76_sqrt_ensemble/
├── deployment_candidate.json
├── model_manifest.json
├── SHA256SUMS
├── seed_42/
│   └── best.pt
├── seed_123/
│   └── best.pt
└── seed_2026/
    └── best.pt
```

Each model is approximately 736 KiB.

The generated manifest records:

```text
seed 42:
  best epoch       8
  val macro-F1     0.8332832698
  SHA-256          cedefb5abfcaa385f94c39c72c99ec076e8f87fbc24b53caf347468c125ba952

seed 123:
  best epoch       5
  val macro-F1     0.8329972206
  SHA-256          d957b8eb130954b1bd0aa1019cdf00b2660d2e7cd52d88d43b1644a96a4082ee

seed 2026:
  best epoch       5
  val macro-F1     0.8441361893
  SHA-256          b70c3cab85c08fe638141810454d7d0f3287a805e0b254a605907c724fe9cfbc
```

Integrity verification already succeeded for:

```text
seed_42/best.pt
seed_123/best.pt
seed_2026/best.pt
deployment_candidate.json
model_manifest.json
```

with:

```bash
shasum -a 256 -c SHA256SUMS
```

---

## 5. Current provisional event profiles

Primary evaluation policy:

```text
STRICT
```

Current B-ensemble development profiles:

### Balanced

```text
threshold   = 0.92
consecutive = 1
status      = provisional_default
```

### Quiet

```text
threshold   = 0.89
consecutive = 4
status      = provisional
```

### Safety

```text
threshold   = 0.80
consecutive = 3
status      = core_only_not_frozen
```

`Safety` is **not frozen**.

The final threshold must not be considered a production specification until long continuous ADL negative-video evaluation is performed.

---

## 6. Evaluation methodology caveat

The project has extensively used the AI Hub **official Validation set** as development material.

Therefore:

```text
current metrics = development/prototype metrics
```

They must not be described as a final untouched benchmark.

The previous internal test split is also no longer fully untouched because early v1 test results were observed before later model design changes.

For a rigorous final study, the preferred structure is:

```text
AI Hub Training
  -> training
  -> internal validation
  -> model selection / threshold tuning

AI Hub official Validation
  -> final evaluation only
```

---

## 7. AI Hub dataset and split rules

Dataset:

```text
AI Hub 71641
낙상사고 위험동작 영상-센서 쌍 데이터
```

Validation data used during development:

```text
2,272 videos
284 physical scenarios
8 camera views per scenario
24 actors
```

Critical leakage rule:

```text
C1 ~ C8 from the same physical scenario must never be split across train/val/test.
```

Actor-disjoint splitting was also used.

Do not replace this with random window/video splitting.

---

## 8. Pose extraction reference domain

The GRU training features were extracted using:

```text
YOLO11n-Pose pretrained
imgsz       = 960
confidence  = 0.10
sampling    = 10 FPS
device      = Apple M4 MPS
```

Full validation pose cache:

```text
2,272 / 2,272 videos
```

Current local cache:

```text
~/Projects/home-safety-ml/data/pose_cache/val_yolo11n_pose_960_10fps
```

Current cache size is approximately:

```text
62 MB
```

This reference domain is important.

Do not assume that a Raspberry Pi configuration such as:

```text
imgsz=320
confidence=0.35
1.5 FPS
```

is interchangeable with the training pose domain.

---

## 9. Research workspace

Research workspace:

```text
~/Projects/home-safety-ml
```

Current high-level contents:

```text
data/
models/
runs/
scripts/
```

Approximate sizes at the time of promotion:

```text
data/pose_cache   62 MB
data/gru_dataset 153 MB
runs              33 MB
models             6 MB
scripts          700 KB
```

This workspace is small enough to keep and should **not** be deleted.

It is the reproducibility workspace for the fall-detection research.

---

## 10. Research scripts

The research scripts were copied into:

```text
research/fall_detection/scripts/
```

Current sequence:

```text
01_inspect_aihub_video_labels.py
02_build_manifest.py
03_pose_smoke.py
04_pose_grid_benchmark.py
05_pose_roi_benchmark.py
06_pose_representative_benchmark.py
07_extract_pose_cache.py
08_make_actor_split.py
09_build_gru_dataset.py
10_train_gru.py
11_event_evaluation.py
12_build_gru_dataset_v2.py
13_train_gru_v2.py
14_compare_event_val_v1_v2.py
15_train_gru_binary_alert.py
16_compare_event_val_corrected.py
17_refine_v2_operating_point.py
18_analyze_v2_strict_frontier.py
18_train_gru_ablation_bc.py
19_compare_gru_ablation_event.py
20_compare_ablation_event.py
21_train_gru_multiseed.py
22_compare_bd_multiseed_event.py
23_diagnose_bd_score_stability.py
```

### Important evaluator history

`11_event_evaluation.py` and `14_compare_event_val_v1_v2.py` are historical.

The corrected event-overlap semantics were implemented later.

Use the later corrected evaluation logic when reproducing event metrics.

Do not blindly treat every old CSV as equally authoritative.

---

## 11. Research artifacts promoted to Git

Research artifacts now live under:

```text
research/fall_detection/
├── scripts/
├── splits/
└── results/
    ├── ablation/
    ├── multiseed/
    └── stability/
```

Important files include:

```text
research/fall_detection/splits/actor_assignments.csv

research/fall_detection/results/ablation/
  gru_ablation_window_summary.csv
  selected_profiles.csv

research/fall_detection/results/multiseed/
  B_76_sqrt_seed_42_grid.csv
  B_76_sqrt_seed_123_grid.csv
  B_76_sqrt_seed_2026_grid.csv
  D_125_sqrt_seed_42_grid.csv
  D_125_sqrt_seed_123_grid.csv
  D_125_sqrt_seed_2026_grid.csv
  d_frozen_operating_points.csv
  per_seed_profile_selection.csv
  profile_pass_summary.csv

research/fall_detection/results/stability/
  B_76_sqrt_ensemble_strict_grid.csv
  D_125_sqrt_ensemble_strict_grid.csv
  ensemble_profiles.csv
  ensemble_score_diagnostics.csv
  fixed_fa_budget_per_seed.csv
  score_diagnostics.csv
```

At promotion time:

```text
models/fall_gru/b76_sqrt_ensemble ≈ 2.2 MB
research/fall_detection           ≈ 2.2 MB
```

---

## 12. Current Git repository state before commit

Repository:

```text
~/Projects/Home-Safety-System
```

Current new untracked paths after promotion:

```text
models/fall_gru/
research/
```

A plain `git diff --stat` showed nothing because these paths were still untracked.

Before committing, inspect with:

```bash
git status --short
find models/fall_gru research/fall_detection -type f | sort
```

Do not use `git add .` without first checking that no generated dataset/cache/video files were copied into the repository.

---

## 13. External SSD status

External dataset root:

```text
/Volumes/AIData/aihub71641
```

Current storage:

```text
downloads  ≈ 55 GB
raw        ≈ 25 GB
```

Raw validation:

```text
/Volumes/AIData/aihub71641/raw/val
```

contains:

```text
2,272 MP4 files
≈ 25 GB
```

The `downloads` directory contains only three files:

```text
VS.fixed.zip  ≈ 54.78 GB
rebuild_vs.py ≈ 2.79 KB
repair_vs_order.py ≈ 2.54 KB
```

The 54.78 GB `VS.fixed.zip` is a rebuilt/download archive and is redundant with the successfully extracted 2,272 MP4 files.

### Storage policy

Keep:

```text
/Volumes/AIData/aihub71641/raw/val
```

for now.

Reason: Raspberry Pi deployment may force a different pose backend, input size, or sampling rate. In that case the 2,272 original videos may need to be reprocessed.

The large download archive can be deleted after the promoted repository/model artifacts are committed and the raw 2,272-video set is rechecked.

Do not delete the raw MP4 dataset yet.

---

## 14. Camera hardware — authoritative current list

The actual camera list is:

### 1. Dahua IP Camera

```text
IP: 192.168.1.64
role: primary fall-detection camera
transport: RTSP/TCP
```

### 2. ABKO APC720 USB Webcam

```text
role: face enrollment / controlled near-field face recognition
transport: V4L2/OpenCV
```

The earlier mention of an Anker webcam was a memory error.

**ABKO APC720 is the correct hardware.**

### 3. Raspberry Pi Camera Module 3

```text
role: secondary view / event verification
transport: Picamera2/libcamera
```

The Camera Module 3 role is intentionally secondary for now.

---

## 15. Recommended camera responsibility split

Do not run every AI task on every camera.

### Dahua

```text
primary fall camera
pose ON
tracking ON
GRU ON
face OFF
```

### ABKO APC720

```text
face enrollment ON
face recognition ON
pose OFF
fall OFF
generic YOLO OFF unless explicitly needed
```

### Camera Module 3

```text
secondary live view
face OFF
fall OFF initially
optional secondary pose later
```

The first production-like fall path should be:

```text
Dahua RTSP
  -> YOLO Pose
  -> person tracker
  -> per-track 20-frame sequence
  -> 76-feature extraction
  -> 3-seed GRU ensemble
  -> event state machine
  -> MQTT
```

---

## 16. Do not require two-camera agreement for a fall alert

Do **not** implement:

```text
Dahua says FALL
AND
Camera Module 3 says FALL
=> alert
```

This creates unnecessary false negatives if the second camera is occluded or misses the person.

Preferred design:

```text
Dahua fall result
=> primary alert

Camera Module 3 evidence
=> optional secondary verification / confidence enrichment
```

Example metadata:

```json
{
  "event_type": "fall_confirmed",
  "primary_camera": "dahua",
  "secondary_verified": false
}
```

---

## 17. Current Home-Safety-System vision implementation

The product repository already has three camera source types:

```text
Picamera2
V4L2
RTSP
```

Current historical Pi fall path is still an MVP based on:

```text
YOLO11n-Pose NCNN
+ torso angle
+ bbox ratio
+ temporal rule state
```

The new 3-seed GRU ensemble has not yet replaced the runtime rule-based fall detector.

Do not delete the rule detector immediately.

Recommended runtime abstraction:

```text
RuleFallDetector
TemporalGruFallDetector
```

with configuration such as:

```text
fall_backend: rule
fall_backend: gru
```

The rule path should remain available as a fallback during Pi integration.

---

## 18. Raspberry Pi domain gap

Current research pose domain:

```text
960 / conf 0.10 / 10 FPS
```

Historical Pi configuration:

```text
320 / conf 0.35 / approximately 1.5 FPS pose analysis
```

This difference is too large to ignore.

The temporal model assumes approximately:

```text
20 frames @ 10 FPS
≈ 2 seconds
```

If the Pi only provides:

```text
20 frames @ 2 FPS
≈ 10 seconds
```

then the temporal input distribution is fundamentally different.

Therefore:

```text
10 Hz pose sequence is the first deployment target.
```

If the Pi cannot sustain it, retrain/evaluate at the achievable sampling rate instead of stretching the same 20-frame model over a much longer time span.

---

## 19. Raspberry Pi integration order

Do not modify the whole system at once.

Recommended sequence:

1. Inventory Pi5 OS, Python, packages, NCNN/Hailo state.
2. Verify all three physical cameras.
3. Verify ABKO `/dev/v4l/by-id/...`, modes, FPS, pixel formats.
4. Verify Dahua RTSP stability.
5. Benchmark Dahua source resolution:
   - 1280×720
   - 1920×1080
6. Benchmark pose input:
   - 640
   - 960
7. Determine whether stable 10 Hz pose is achievable.
8. Add tracker.
9. Add per-track 20-frame 76-feature buffer.
10. Add the three GRU models and probability averaging.
11. Add event state machine.
12. Publish MQTT event.
13. Re-enable ABKO face station.
14. Add Camera Module 3 as secondary view.
15. Run the three-camera combined load test.

---

## 20. Metrics to collect on Pi5

Capture:

```text
source FPS
decode latency
dropped frames
RTSP reconnects
```

Pose:

```text
input size
mean latency
p95 latency
effective FPS
person detection rate
visible keypoint ratio
pose coverage
```

Temporal model:

```text
76-feature extraction latency
single-GRU latency
3-GRU ensemble latency
```

System:

```text
CPU
RAM
temperature
throttling
network bitrate
```

Event layer:

```text
fall-end recall
+1s recall
detection latency
false alarms
```

---

## 21. False-alarm metric caveat

The current AI Hub data consists largely of short staged clips.

Therefore:

```text
FA/hour derived from these short clips
```

must **not** be interpreted as real household false alarms per hour.

A future continuous ADL negative dataset is required, including:

```text
walking
sitting
standing up
lying on bed/sofa
picking up objects
crouching
kneeling
stretching
cleaning
camera occlusion
partial frame exit
multiple people
lighting changes
```

Final operational thresholds should be tuned/validated against such long continuous data.

---

## 22. Face recognition scope

Current repository face stack:

```text
YuNet detector
SFace embedding
cosine similarity
front / left / right templates
```

ABKO APC720 should be the controlled face-registration station.

Do not automatically assume that an identity recognized on ABKO is the identity of a person falling in the Dahua view.

Cross-camera identity association would require additional tracking/re-identification logic.

For the graduation project, face registration/recognition and fall detection may remain separate AI functions.

---

## 23. Rules for future coding agents

A future coding agent should follow these rules unless explicitly instructed otherwise:

1. **Do not replace the current ensemble with a single-seed D model.**
2. **Do not random-split AI Hub C1~C8 views.**
3. **Do not use the historical 1.5 FPS pose configuration with the 10 FPS temporal model without retraining.**
4. **Do not run face recognition on all cameras.**
5. **Do not make Camera Module 3 agreement mandatory for a Dahua fall alert.**
6. **Do not remove the current rule-based detector until GRU deployment is verified.**
7. **Do not commit AI Hub raw video, pose cache, GRU NPZ datasets, or large generated prediction files.**
8. **Do not treat current development metrics as final untouched test performance.**
9. **Keep research and runtime code separate.**
10. **Use event-level metrics, not only window accuracy/F1.**

---

## 24. Current next action

Before writing runtime GRU integration code, finish the repository promotion:

```text
1. add this handoff document
2. inspect git status
3. stage only the intended research/model/docs paths
4. commit
5. optionally remove the redundant 54.78 GB VS.fixed.zip
6. keep the 25 GB raw/val MP4 dataset
7. start Raspberry Pi 5 inventory and camera benchmark
```

Suggested commit scope:

```text
models/fall_gru/b76_sqrt_ensemble/
research/fall_detection/
docs/FALL_DETECTION_ML_HANDOFF.md
```

Suggested commit message:

```text
Promote fall detection ensemble and research artifacts
```

---

## 25. Source of truth hierarchy

When documents conflict, use this order:

1. `models/fall_gru/b76_sqrt_ensemble/model_manifest.json`
2. `models/fall_gru/b76_sqrt_ensemble/deployment_candidate.json`
3. `research/fall_detection/results/stability/`
4. this handoff document
5. older research notes / old single-seed deployment notes

The latest model choice is:

```text
B_76_sqrt_3seed_ensemble
```

not `D_125_sqrt`.

---

## 26. One-line project state

The research phase has produced a reproducible 3-seed GRU ensemble candidate and promoted its artifacts into the main repository; the next phase is to validate the **Dahua -> Pose 10 Hz -> Tracker -> 76-feature sequence -> 3-GRU ensemble -> MQTT** path on the Raspberry Pi 5 while using ABKO APC720 for face enrollment and Camera Module 3 as a secondary view.
