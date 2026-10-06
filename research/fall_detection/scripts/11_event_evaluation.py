from pathlib import Path
import json

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset


DATA_ROOT = Path("data/gru_dataset/v1_actor_disjoint_20f")
RUN_ROOT = Path("runs/gru_v1")
CHECKPOINT = RUN_ROOT / "best.pt"

BATCH_SIZE = 1024

THRESHOLDS = [
    round(x, 2)
    for x in np.arange(
        0.30,
        0.951,
        0.05,
    )
]

CONSECUTIVE_OPTIONS = [
    1,
    2,
    3,
    4,
]

RELEASE_FRAMES = 2

TARGET_RECALL_1S = 0.95

LABEL_NAMES = [
    "normal",
    "falling",
    "fallen",
]


def get_device():

    if torch.backends.mps.is_available():
        return torch.device("mps")

    if torch.cuda.is_available():
        return torch.device("cuda")

    return torch.device("cpu")


class FallGRU(nn.Module):

    def __init__(
        self,
        input_size,
        hidden_size,
        num_layers,
        dropout,
        num_classes,
    ):

        super().__init__()

        self.input_norm = nn.LayerNorm(
            input_size
        )

        self.gru = nn.GRU(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=(
                dropout
                if num_layers > 1
                else 0.0
            ),
            bidirectional=False,
        )

        self.head = nn.Sequential(
            nn.LayerNorm(
                hidden_size
            ),
            nn.Dropout(
                dropout
            ),
            nn.Linear(
                hidden_size,
                64,
            ),
            nn.ReLU(),
            nn.Dropout(
                dropout
            ),
            nn.Linear(
                64,
                num_classes,
            ),
        )

    def forward(self, x):

        x = self.input_norm(
            x
        )

        _, h_n = self.gru(
            x
        )

        return self.head(
            h_n[-1]
        )


def load_split(split):

    with np.load(
        DATA_ROOT
        / f"{split}.npz"
    ) as d:

        X = np.asarray(
            d["X"],
            dtype=np.float32,
        )

        y = np.asarray(
            d["y"],
            dtype=np.int64,
        )

    meta = pd.read_csv(
        DATA_ROOT
        / f"{split}_meta.csv.gz"
    )

    if (
        len(X) != len(y)
        or len(meta) != len(y)
    ):
        raise RuntimeError(
            f"{split}: "
            "X/y/meta length mismatch"
        )

    return X, y, meta


def predict_split(
    model,
    X,
    y,
    meta,
    device,
):

    loader = DataLoader(
        TensorDataset(
            torch.from_numpy(X),
            torch.from_numpy(y),
        ),
        batch_size=BATCH_SIZE,
        shuffle=False,
        num_workers=0,
    )

    probs = []

    model.eval()

    with torch.no_grad():

        for xb, _ in loader:

            logits = model(
                xb.to(device)
            )

            probs.append(
                torch.softmax(
                    logits,
                    dim=1,
                )
                .cpu()
                .numpy()
            )

    prob = np.concatenate(
        probs,
        axis=0,
    )

    out = meta.copy()

    out["y_true"] = y

    out["y_pred"] = (
        prob.argmax(
            axis=1
        )
    )

    for i, name in enumerate(
        LABEL_NAMES
    ):

        out[
            f"prob_{name}"
        ] = prob[:, i]

    # 실제 경보에서는
    # falling / fallen 모두 이상상태
    out["alert_score"] = (
        out["prob_falling"]
        + out["prob_fallen"]
    )

    return out


def alarm_onsets(
    scene,
    threshold,
    consecutive,
):

    scene = scene.sort_values(
        "timestamp"
    )

    active = False

    high_run = 0
    low_run = 0

    onsets = []

    for t, score in zip(
        scene["timestamp"],
        scene["alert_score"],
    ):

        if not active:

            if score >= threshold:
                high_run += 1
            else:
                high_run = 0

            if high_run >= consecutive:

                # consecutive개를 모두 관측한
                # 현재 시점에 경보 발생
                onsets.append(
                    float(t)
                )

                active = True

                high_run = 0
                low_run = 0

        else:

            if score < threshold:
                low_run += 1
            else:
                low_run = 0

            if (
                low_run
                >= RELEASE_FRAMES
            ):

                active = False

                high_run = 0
                low_run = 0

    return onsets


def estimate_dt(scene):

    ts = np.sort(
        scene[
            "timestamp"
        ].unique()
    )

    if len(ts) < 2:
        return 0.1

    d = np.diff(ts)

    d = d[
        d > 0
    ]

    if len(d) == 0:
        return 0.1

    return float(
        np.median(d)
    )


def evaluate_events(
    pred,
    threshold,
    consecutive,
    return_details=False,
):

    fall_videos = 0

    detected_end = 0
    detected_1s = 0
    detected_2s = 0

    latencies_1s = []
    latencies_2s = []

    false_alarms = 0

    negative_seconds = 0.0

    nonfall_videos = 0

    nonfall_with_alarm = 0

    fall_with_prefall_alarm = 0

    details = []


    for (
        scene_id,
        scene,
    ) in pred.groupby(
        "scene_id",
        sort=False,
    ):

        scene = (
            scene
            .sort_values(
                "timestamp"
            )
            .reset_index(
                drop=True
            )
        )

        dt = estimate_dt(
            scene
        )

        onsets = alarm_onsets(
            scene,
            threshold,
            consecutive,
        )

        is_fall = (
            int(
                scene[
                    "phase"
                ].max()
            )
            >= 2
        )

        base = {

            "scene_id":
                scene_id,

            "scenario_id":
                scene[
                    "scenario_id"
                ].iloc[0],

            "actor_id":
                scene[
                    "actor_id"
                ].iloc[0],

            "fall_class":
                scene[
                    "fall_class"
                ].iloc[0],

            "camera":
                int(
                    scene[
                        "camera"
                    ].iloc[0]
                ),

            "is_fall":
                int(
                    is_fall
                ),
        }


        # -----------------------------
        # 비낙상 영상
        # -----------------------------

        if not is_fall:

            nonfall_videos += 1

            negative_seconds += (
                len(scene)
                * dt
            )

            false_alarms += (
                len(onsets)
            )

            nonfall_with_alarm += (
                int(
                    bool(onsets)
                )
            )

            details.append(
                {
                    **base,

                    "fall_start_t":
                        np.nan,

                    "fall_end_t":
                        np.nan,

                    "first_valid_alarm_t":
                        np.nan,

                    "latency_sec":
                        np.nan,

                    "detected_by_end":
                        0,

                    "detected_by_1s":
                        0,

                    "detected_by_2s":
                        0,

                    "prefall_false_alarms":
                        0,

                    "nonfall_false_alarms":
                        len(onsets),
                }
            )

            continue


        # -----------------------------
        # 낙상 영상
        # -----------------------------

        fall_videos += 1

        falling = scene[
            scene[
                "phase"
            ] == 2
        ]

        if falling.empty:

            raise RuntimeError(
                f"{scene_id}: "
                "phase=2 not found"
            )


        fall_start_t = float(
            falling[
                "timestamp"
            ].min()
        )

        fall_end_t = float(
            falling[
                "timestamp"
            ].max()
        )


        # 낙상 시작 전은 정상 구간이므로
        # false alarm 평가시간에 포함
        pre_rows = scene[
            scene[
                "timestamp"
            ] < fall_start_t
        ]

        negative_seconds += (
            len(pre_rows)
            * dt
        )


        prefall = [
            t
            for t in onsets
            if t < fall_start_t
        ]

        false_alarms += (
            len(prefall)
        )

        fall_with_prefall_alarm += (
            int(
                bool(prefall)
            )
        )


        # 낙상 시작 이후에 새로 발생한
        # 첫 경보만 event detection으로 인정
        valid = [
            t
            for t in onsets
            if t >= fall_start_t
        ]


        first = (
            valid[0]
            if valid
            else np.nan
        )


        by_end = (
            bool(valid)
            and first
            <= fall_end_t
        )


        by_1s = (
            bool(valid)
            and first
            <= fall_end_t
            + 1.0
        )


        by_2s = (
            bool(valid)
            and first
            <= fall_end_t
            + 2.0
        )


        detected_end += int(
            by_end
        )

        detected_1s += int(
            by_1s
        )

        detected_2s += int(
            by_2s
        )


        if by_1s:

            latencies_1s.append(
                first
                - fall_start_t
            )


        if by_2s:

            latencies_2s.append(
                first
                - fall_start_t
            )


        details.append(
            {
                **base,

                "fall_start_t":
                    fall_start_t,

                "fall_end_t":
                    fall_end_t,

                "first_valid_alarm_t":
                    first,

                "latency_sec":
                    (
                        first
                        - fall_start_t
                        if not np.isnan(
                            first
                        )
                        else np.nan
                    ),

                "detected_by_end":
                    int(
                        by_end
                    ),

                "detected_by_1s":
                    int(
                        by_1s
                    ),

                "detected_by_2s":
                    int(
                        by_2s
                    ),

                "prefall_false_alarms":
                    len(prefall),

                "nonfall_false_alarms":
                    0,
            }
        )


    if fall_videos == 0:

        raise RuntimeError(
            "No fall videos found"
        )


    negative_hours = (
        negative_seconds
        / 3600.0
    )


    metrics = {

        "threshold":
            float(
                threshold
            ),

        "consecutive":
            int(
                consecutive
            ),

        "fall_videos":
            int(
                fall_videos
            ),

        "event_recall_by_fall_end":
            detected_end
            / fall_videos,

        "event_recall_by_1s":
            detected_1s
            / fall_videos,

        "event_recall_by_2s":
            detected_2s
            / fall_videos,

        "median_latency_1s":
            (
                float(
                    np.median(
                        latencies_1s
                    )
                )
                if latencies_1s
                else np.nan
            ),

        "p95_latency_1s":
            (
                float(
                    np.percentile(
                        latencies_1s,
                        95,
                    )
                )
                if latencies_1s
                else np.nan
            ),

        "median_latency_2s":
            (
                float(
                    np.median(
                        latencies_2s
                    )
                )
                if latencies_2s
                else np.nan
            ),

        "false_alarm_count":
            int(
                false_alarms
            ),

        "negative_exposure_hours":
            float(
                negative_hours
            ),

        "false_alarms_per_hour":
            (
                false_alarms
                / negative_hours
                if negative_hours > 0
                else np.nan
            ),

        "nonfall_videos":
            int(
                nonfall_videos
            ),

        "nonfall_video_false_alarm_rate":
            (
                nonfall_with_alarm
                / nonfall_videos
                if nonfall_videos
                else np.nan
            ),

        "prefall_alarm_rate":
            (
                fall_with_prefall_alarm
                / fall_videos
            ),
    }


    if return_details:

        return (
            metrics,
            pd.DataFrame(
                details
            ),
        )


    return metrics


def choose_best(grid):

    eligible = grid[
        grid[
            "event_recall_by_1s"
        ]
        >= TARGET_RECALL_1S
    ].copy()


    if not eligible.empty:

        best = (
            eligible
            .sort_values(
                [
                    "false_alarms_per_hour",
                    "median_latency_1s",
                    "event_recall_by_fall_end",
                    "consecutive",
                    "threshold",
                ],
                ascending=[
                    True,
                    True,
                    False,
                    True,
                    False,
                ],
            )
            .iloc[0]
        )

        return (
            best,
            "recall_target_met",
        )


    best = (
        grid
        .sort_values(
            [
                "event_recall_by_1s",
                "false_alarms_per_hour",
                "median_latency_1s",
            ],
            ascending=[
                False,
                True,
                True,
            ],
        )
        .iloc[0]
    )


    return (
        best,
        "recall_target_not_met",
    )


def summarize_fall_group(
    details,
    column,
):

    fall = details[
        details[
            "is_fall"
        ] == 1
    ]


    return (
        fall
        .groupby(
            column
        )
        .agg(

            videos=(
                "scene_id",
                "count",
            ),

            recall_by_end=(
                "detected_by_end",
                "mean",
            ),

            recall_by_1s=(
                "detected_by_1s",
                "mean",
            ),

            recall_by_2s=(
                "detected_by_2s",
                "mean",
            ),

            median_latency_sec=(
                "latency_sec",
                "median",
            ),

            prefall_false_alarms=(
                "prefall_false_alarms",
                "sum",
            ),
        )
        .reset_index()
    )


def json_safe(value):

    if pd.isna(
        value
    ):
        return None

    if isinstance(
        value,
        (
            int,
            np.integer,
        ),
    ):
        return int(
            value
        )

    if isinstance(
        value,
        (
            float,
            np.floating,
        ),
    ):
        return float(
            value
        )

    return value


def main():

    RUN_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )


    device = get_device()


    print(
        "=" * 90
    )

    print(
        "EVENT-LEVEL EVALUATION"
    )

    print(
        "=" * 90
    )

    print(
        "device:",
        device,
    )


    ckpt = torch.load(
        CHECKPOINT,
        map_location=device,
        weights_only=False,
    )


    model = FallGRU(

        input_size=int(
            ckpt[
                "input_size"
            ]
        ),

        hidden_size=int(
            ckpt[
                "hidden_size"
            ]
        ),

        num_layers=int(
            ckpt[
                "num_layers"
            ]
        ),

        dropout=float(
            ckpt[
                "dropout"
            ]
        ),

        num_classes=int(
            ckpt[
                "num_classes"
            ]
        ),

    ).to(
        device
    )


    model.load_state_dict(
        ckpt[
            "model_state"
        ]
    )


    # =================================================
    # Validation에서만 state machine 설정 결정
    # =================================================

    print()
    print(
        "Loading validation..."
    )


    X_val, y_val, meta_val = (
        load_split(
            "val"
        )
    )


    val_pred = predict_split(
        model,
        X_val,
        y_val,
        meta_val,
        device,
    )


    val_pred.to_csv(
        RUN_ROOT
        / "val_event_predictions.csv.gz",
        index=False,
        compression="gzip",
    )


    print(
        "Tuning on VALIDATION ONLY..."
    )


    grid_rows = []


    for threshold in THRESHOLDS:

        for consecutive in (
            CONSECUTIVE_OPTIONS
        ):

            m = evaluate_events(
                val_pred,
                threshold,
                consecutive,
            )


            grid_rows.append(
                m
            )


            print(

                f"thr="
                f"{threshold:.2f} "

                f"k="
                f"{consecutive} "

                f"end="
                f"{m['event_recall_by_fall_end']:.3f} "

                f"+1s="
                f"{m['event_recall_by_1s']:.3f} "

                f"FA/h="
                f"{m['false_alarms_per_hour']:.2f} "

                f"lat="
                f"{m['median_latency_1s']:.3f}s"
            )


    grid = pd.DataFrame(
        grid_rows
    )


    grid.to_csv(
        RUN_ROOT
        / "event_val_grid.csv",
        index=False,
    )


    best, mode = (
        choose_best(
            grid
        )
    )


    threshold = float(
        best[
            "threshold"
        ]
    )


    consecutive = int(
        best[
            "consecutive"
        ]
    )


    print()
    print(
        "=" * 90
    )

    print(
        "SELECTED ON VALIDATION"
    )

    print(
        "=" * 90
    )


    print(
        "mode        :",
        mode,
    )

    print(
        "threshold   :",
        threshold,
    )

    print(
        "consecutive :",
        consecutive,
    )

    print(
        "recall end  :",
        f"{best['event_recall_by_fall_end']:.4f}",
    )

    print(
        "recall +1s  :",
        f"{best['event_recall_by_1s']:.4f}",
    )

    print(
        "FA/hour     :",
        f"{best['false_alarms_per_hour']:.4f}",
    )

    print(
        "median delay:",
        f"{best['median_latency_1s']:.4f}s",
    )


    del X_val


    if device.type == "mps":

        torch.mps.empty_cache()


    # =================================================
    # 선택 완료 후 Test 평가
    # =================================================

    print()
    print(
        "Loading test..."
    )


    X_test, y_test, meta_test = (
        load_split(
            "test"
        )
    )


    test_pred = predict_split(
        model,
        X_test,
        y_test,
        meta_test,
        device,
    )


    test_pred.to_csv(
        RUN_ROOT
        / "test_event_predictions.csv.gz",
        index=False,
        compression="gzip",
    )


    (
        test_metrics,
        details,
    ) = evaluate_events(

        test_pred,

        threshold,

        consecutive,

        return_details=True,
    )


    details.to_csv(
        RUN_ROOT
        / "test_event_details.csv",
        index=False,
    )


    by_camera = (
        summarize_fall_group(
            details,
            "camera",
        )
    )


    by_class = (
        summarize_fall_group(
            details,
            "fall_class",
        )
    )


    by_camera.to_csv(
        RUN_ROOT
        / "event_test_by_camera.csv",
        index=False,
    )


    by_class.to_csv(
        RUN_ROOT
        / "event_test_by_fall_class.csv",
        index=False,
    )


    result = {

        "selection_mode":
            mode,

        "target_event_recall_1s":
            TARGET_RECALL_1S,

        "selected_threshold":
            threshold,

        "selected_consecutive":
            consecutive,

        "release_frames":
            RELEASE_FRAMES,

        "validation_selected_metrics":
            {
                key:
                    json_safe(
                        best[
                            key
                        ]
                    )

                for key in [
                    "event_recall_by_fall_end",
                    "event_recall_by_1s",
                    "event_recall_by_2s",
                    "median_latency_1s",
                    "p95_latency_1s",
                    "false_alarms_per_hour",
                    "nonfall_video_false_alarm_rate",
                    "prefall_alarm_rate",
                ]
            },

        "test_metrics":
            {
                key:
                    json_safe(
                        value
                    )

                for key, value
                in test_metrics.items()
            },
    }


    with (
        RUN_ROOT
        / "event_metrics.json"
    ).open(
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            result,
            f,
            ensure_ascii=False,
            indent=2,
        )


    print()
    print(
        "=" * 90
    )

    print(
        "TEST EVENT RESULT"
    )

    print(
        "=" * 90
    )


    for (
        key,
        value,
    ) in test_metrics.items():

        if isinstance(
            value,
            float,
        ):

            print(
                f"{key:32s}: "
                f"{value:.6f}"
            )

        else:

            print(
                f"{key:32s}: "
                f"{value}"
            )


    print()
    print(
        "BY CAMERA"
    )

    print(
        by_camera.to_string(
            index=False
        )
    )


    print()
    print(
        "BY FALL CLASS"
    )

    print(
        by_class.to_string(
            index=False
        )
    )


    print()
    print(
        "saved:",
        RUN_ROOT
        / "event_metrics.json",
    )


if __name__ == "__main__":

    main()
