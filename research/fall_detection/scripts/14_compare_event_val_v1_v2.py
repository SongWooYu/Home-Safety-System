from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn

from torch.utils.data import (
    DataLoader,
    TensorDataset,
)


MODELS = {
    "v1": {
        "data_root": Path(
            "data/gru_dataset/v1_actor_disjoint_20f"
        ),
        "checkpoint": Path(
            "runs/gru_v1/best.pt"
        ),
    },

    "v2": {
        "data_root": Path(
            "data/gru_dataset/v2_actor_disjoint_20f_dynamic"
        ),
        "checkpoint": Path(
            "runs/gru_v2/best.pt"
        ),
    },
}


OUT_ROOT = Path(
    "runs/event_compare_v1_v2_val"
)


BATCH_SIZE = 1024


THRESHOLDS = [
    0.50,
    0.55,
    0.60,
    0.65,
    0.70,
    0.75,
    0.80,
    0.85,
    0.90,
    0.93,
    0.95,
    0.97,
    0.98,
    0.99,
]


CONSECUTIVE_OPTIONS = [
    1,
    2,
    3,
    4,
    5,
]


RELEASE_FRAMES = 3

EARLY_TOLERANCE_SEC = 0.5

TARGET_RECALL_PLUS_1S = 0.95


LABEL_NAMES = [
    "normal",
    "falling",
    "fallen",
]


def get_device():

    if (
        torch.backends
        .mps
        .is_available()
    ):
        return torch.device(
            "mps"
        )

    if torch.cuda.is_available():
        return torch.device(
            "cuda"
        )

    return torch.device(
        "cpu"
    )


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


        self.input_norm = (
            nn.LayerNorm(
                input_size
            )
        )


        self.gru = nn.GRU(

            input_size=
                input_size,

            hidden_size=
                hidden_size,

            num_layers=
                num_layers,

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


    def forward(
        self,
        x,
    ):

        x = self.input_norm(
            x
        )


        _, h_n = self.gru(
            x
        )


        return self.head(
            h_n[-1]
        )


def load_validation(
    data_root,
):

    with np.load(
        data_root
        / "val.npz"
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
        data_root
        / "val_meta.csv.gz"
    )


    if (
        len(X) != len(y)
        or len(meta) != len(y)
    ):

        raise RuntimeError(
            "Validation length mismatch: "
            f"X={len(X)} "
            f"y={len(y)} "
            f"meta={len(meta)}"
        )


    return (
        X,
        y,
        meta,
    )


def load_model(
    checkpoint_path,
    device,
):

    ckpt = torch.load(

        checkpoint_path,

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


    model.eval()


    return (
        model,
        ckpt,
    )


def predict_validation(
    model,
    X,
    y,
    meta,
    device,
):

    loader = DataLoader(

        TensorDataset(
            torch.from_numpy(
                X
            ),
            torch.from_numpy(
                y
            ),
        ),

        batch_size=
            BATCH_SIZE,

        shuffle=False,

        num_workers=0,
    )


    probs = []


    with torch.no_grad():

        for xb, _ in loader:

            logits = model(
                xb.to(
                    device
                )
            )


            prob = torch.softmax(
                logits,
                dim=1,
            )


            probs.append(
                prob
                .cpu()
                .numpy()
            )


    prob = np.concatenate(
        probs,
        axis=0,
    )


    out = meta.copy()


    out[
        "y_true"
    ] = y


    out[
        "y_pred"
    ] = prob.argmax(
        axis=1
    )


    for i, name in enumerate(
        LABEL_NAMES
    ):

        out[
            f"prob_{name}"
        ] = prob[
            :,
            i,
        ]


    out[
        "alert_score"
    ] = (
        out[
            "prob_falling"
        ]
        +
        out[
            "prob_fallen"
        ]
    )


    return out


def estimate_dt(
    scene,
):

    ts = np.sort(
        scene[
            "timestamp"
        ].unique()
    )


    if len(ts) < 2:

        return 0.1


    diff = np.diff(
        ts
    )


    diff = diff[
        diff > 0
    ]


    if len(diff) == 0:

        return 0.1


    return float(
        np.median(
            diff
        )
    )


def build_alarm_intervals(
    scene,
    threshold,
    consecutive,
    release_frames,
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


    times = (
        scene[
            "timestamp"
        ]
        .to_numpy(
            dtype=float
        )
    )


    scores = (
        scene[
            "alert_score"
        ]
        .to_numpy(
            dtype=float
        )
    )


    if len(times) == 0:

        return []


    dt = estimate_dt(
        scene
    )


    active = False

    high_run = 0

    low_run = 0

    start_time = None

    intervals = []


    for t, score in zip(
        times,
        scores,
    ):

        if not active:

            if (
                score
                >= threshold
            ):

                high_run += 1

            else:

                high_run = 0


            if (
                high_run
                >= consecutive
            ):

                # 실제 경보가 발생하는 시점:
                # consecutive 조건을 모두 확인한
                # 현재 frame
                start_time = float(
                    t
                )

                active = True

                high_run = 0

                low_run = 0


        else:

            if (
                score
                < threshold
            ):

                low_run += 1

            else:

                low_run = 0


            if (
                low_run
                >= release_frames
            ):

                intervals.append(
                    {
                        "start":
                            float(
                                start_time
                            ),

                        "end":
                            float(
                                t
                            ),
                    }
                )


                active = False

                start_time = None

                high_run = 0

                low_run = 0


    if active:

        intervals.append(
            {
                "start":
                    float(
                        start_time
                    ),

                "end":
                    float(
                        times[-1]
                        + dt
                    ),
            }
        )


    return intervals


def choose_detection(
    intervals,
    allowed_start,
    deadline,
):

    starts = [

        interval[
            "start"
        ]

        for interval
        in intervals

        if (
            interval[
                "start"
            ]
            >= allowed_start
        )

        and (
            interval[
                "start"
            ]
            <= deadline
        )
    ]


    if not starts:

        return np.nan


    return float(
        min(
            starts
        )
    )


def evaluate_policy(
    pred,
    threshold,
    consecutive,
    policy,
):

    if policy not in {
        "strict",
        "early_0p5s",
    }:

        raise ValueError(
            policy
        )


    early_sec = (
        0.0
        if policy == "strict"
        else EARLY_TOLERANCE_SEC
    )


    fall_videos = 0

    detected_end = 0

    detected_plus_1s = 0

    detected_plus_2s = 0


    latency_plus_1s = []


    false_alarm_count = 0

    negative_seconds = 0.0


    nonfall_videos = 0

    nonfall_with_alarm = 0


    fall_videos_with_prefall_alarm = 0


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


        intervals = (
            build_alarm_intervals(
                scene,
                threshold,
                consecutive,
                RELEASE_FRAMES,
            )
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


        # =============================================
        # Non-fall
        # =============================================

        if not is_fall:

            nonfall_videos += 1


            duration = (
                float(
                    scene[
                        "timestamp"
                    ].max()
                )
                -
                float(
                    scene[
                        "timestamp"
                    ].min()
                )
                +
                dt
            )


            negative_seconds += max(
                duration,
                0.0,
            )


            fa_count = len(
                intervals
            )


            false_alarm_count += (
                fa_count
            )


            nonfall_with_alarm += int(
                fa_count > 0
            )


            details.append(
                {
                    **base,

                    "policy":
                        policy,

                    "fall_start_t":
                        np.nan,

                    "fall_end_t":
                        np.nan,

                    "allowed_start_t":
                        np.nan,

                    "first_valid_alarm_t":
                        np.nan,

                    "latency_from_fall_start_sec":
                        np.nan,

                    "detected_by_end":
                        0,

                    "detected_by_plus_1s":
                        0,

                    "detected_by_plus_2s":
                        0,

                    "false_alarms":
                        fa_count,

                    "alarm_intervals":
                        len(
                            intervals
                        ),
                }
            )


            continue


        # =============================================
        # Fall video
        # =============================================

        fall_videos += 1


        falling = scene[
            scene[
                "phase"
            ] == 2
        ]


        if falling.empty:

            raise RuntimeError(
                f"{scene_id}: "
                "no phase=2 samples"
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


        allowed_start_t = (
            fall_start_t
            - early_sec
        )


        first_eval_t = float(
            scene[
                "timestamp"
            ].min()
        )


        negative_seconds += max(
            0.0,

            allowed_start_t
            - first_eval_t,
        )


        prefall_intervals = [

            interval

            for interval
            in intervals

            if (
                interval[
                    "start"
                ]
                < allowed_start_t
            )
        ]


        false_alarm_count += len(
            prefall_intervals
        )


        fall_videos_with_prefall_alarm += int(
            len(
                prefall_intervals
            )
            > 0
        )


        first_end = (
            choose_detection(
                intervals,
                allowed_start_t,
                fall_end_t,
            )
        )


        first_plus_1s = (
            choose_detection(
                intervals,
                allowed_start_t,
                fall_end_t + 1.0,
            )
        )


        first_plus_2s = (
            choose_detection(
                intervals,
                allowed_start_t,
                fall_end_t + 2.0,
            )
        )


        by_end = (
            not np.isnan(
                first_end
            )
        )


        by_plus_1s = (
            not np.isnan(
                first_plus_1s
            )
        )


        by_plus_2s = (
            not np.isnan(
                first_plus_2s
            )
        )


        detected_end += int(
            by_end
        )


        detected_plus_1s += int(
            by_plus_1s
        )


        detected_plus_2s += int(
            by_plus_2s
        )


        if by_plus_1s:

            latency_plus_1s.append(
                first_plus_1s
                - fall_start_t
            )


        details.append(
            {
                **base,

                "policy":
                    policy,

                "fall_start_t":
                    fall_start_t,

                "fall_end_t":
                    fall_end_t,

                "allowed_start_t":
                    allowed_start_t,

                "first_valid_alarm_t":
                    first_plus_1s,

                "latency_from_fall_start_sec":
                    (
                        first_plus_1s
                        - fall_start_t
                        if by_plus_1s
                        else np.nan
                    ),

                "detected_by_end":
                    int(
                        by_end
                    ),

                "detected_by_plus_1s":
                    int(
                        by_plus_1s
                    ),

                "detected_by_plus_2s":
                    int(
                        by_plus_2s
                    ),

                "false_alarms":
                    len(
                        prefall_intervals
                    ),

                "alarm_intervals":
                    len(
                        intervals
                    ),
            }
        )


    negative_hours = (
        negative_seconds
        / 3600.0
    )


    return {

        "policy":
            policy,

        "threshold":
            float(
                threshold
            ),

        "consecutive":
            int(
                consecutive
            ),

        "release_frames":
            RELEASE_FRAMES,

        "fall_videos":
            int(
                fall_videos
            ),

        "event_recall_by_end":
            detected_end
            / fall_videos,

        "event_recall_by_plus_1s":
            detected_plus_1s
            / fall_videos,

        "event_recall_by_plus_2s":
            detected_plus_2s
            / fall_videos,

        "median_latency_sec":
            (
                float(
                    np.median(
                        latency_plus_1s
                    )
                )
                if latency_plus_1s
                else np.nan
            ),

        "p95_latency_sec":
            (
                float(
                    np.percentile(
                        latency_plus_1s,
                        95,
                    )
                )
                if latency_plus_1s
                else np.nan
            ),

        "false_alarm_count":
            int(
                false_alarm_count
            ),

        "negative_exposure_hours":
            float(
                negative_hours
            ),

        "false_alarms_per_hour":
            (
                false_alarm_count
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
                if nonfall_videos > 0
                else np.nan
            ),

        "prefall_false_alarm_video_rate":
            (
                fall_videos_with_prefall_alarm
                / fall_videos
            ),

    }, pd.DataFrame(
        details
    )


def select_operating_point(
    grid,
):

    eligible = grid[
        grid[
            "event_recall_by_plus_1s"
        ]
        >= TARGET_RECALL_PLUS_1S
    ].copy()


    if not eligible.empty:

        best = (
            eligible
            .sort_values(
                [
                    "false_alarms_per_hour",
                    "nonfall_video_false_alarm_rate",
                    "median_latency_sec",
                    "threshold",
                    "consecutive",
                ],

                ascending=[
                    True,
                    True,
                    True,
                    False,
                    True,
                ],
            )
            .iloc[0]
        )


        return (
            best,
            "target_met",
        )


    best = (
        grid
        .sort_values(
            [
                "event_recall_by_plus_1s",
                "false_alarms_per_hour",
                "nonfall_video_false_alarm_rate",
                "median_latency_sec",
            ],

            ascending=[
                False,
                True,
                True,
                True,
            ],
        )
        .iloc[0]
    )


    return (
        best,
        "target_not_met",
    )


def print_selected(
    model_name,
    policy,
    best,
    mode,
):

    print()
    print(
        "-" * 90
    )


    print(
        f"{model_name.upper()} "
        f"/ {policy} "
        f"/ {mode}"
    )


    print(
        "-" * 90
    )


    print(
        "threshold              :",
        f"{best['threshold']:.2f}",
    )


    print(
        "consecutive            :",
        int(
            best[
                "consecutive"
            ]
        ),
    )


    print(
        "recall by end          :",
        f"{best['event_recall_by_end']:.4f}",
    )


    print(
        "recall by +1s          :",
        f"{best['event_recall_by_plus_1s']:.4f}",
    )


    print(
        "recall by +2s          :",
        f"{best['event_recall_by_plus_2s']:.4f}",
    )


    print(
        "median latency         :",
        f"{best['median_latency_sec']:.4f}s",
    )


    print(
        "p95 latency            :",
        f"{best['p95_latency_sec']:.4f}s",
    )


    print(
        "false alarms/hour      :",
        f"{best['false_alarms_per_hour']:.4f}",
    )


    print(
        "nonfall clip FA rate   :",
        f"{best['nonfall_video_false_alarm_rate']:.4f}",
    )


    print(
        "prefall FA video rate  :",
        f"{best['prefall_false_alarm_video_rate']:.4f}",
    )


def main():

    OUT_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )


    device = get_device()


    print(
        "=" * 90
    )


    print(
        "VALIDATION EVENT COMPARISON: "
        "GRU V1 vs V2"
    )


    print(
        "=" * 90
    )


    print(
        "device               :",
        device,
    )


    print(
        "target recall +1s    :",
        TARGET_RECALL_PLUS_1S,
    )


    print(
        "release frames       :",
        RELEASE_FRAMES,
    )


    print(
        "early tolerance      :",
        EARLY_TOLERANCE_SEC,
        "sec",
    )


    print(
        "test set             : "
        "NOT LOADED"
    )


    all_grid = []

    selected_rows = []


    for (
        model_name,
        cfg,
    ) in MODELS.items():

        print()
        print(
            "=" * 90
        )


        print(
            "MODEL",
            model_name.upper(),
        )


        print(
            "=" * 90
        )


        (
            X,
            y,
            meta,
        ) = load_validation(
            cfg[
                "data_root"
            ]
        )


        (
            model,
            ckpt,
        ) = load_model(
            cfg[
                "checkpoint"
            ],
            device,
        )


        print(
            "input size           :",
            ckpt[
                "input_size"
            ],
        )


        print(
            "best epoch           :",
            ckpt[
                "epoch"
            ],
        )


        print(
            "checkpoint val F1    :",
            ckpt[
                "val_macro_f1"
            ],
        )


        print(
            "validation shape     :",
            X.shape,
        )


        pred = (
            predict_validation(
                model,
                X,
                y,
                meta,
                device,
            )
        )


        pred.to_csv(

            OUT_ROOT
            / (
                f"{model_name}"
                "_val_predictions.csv.gz"
            ),

            index=False,

            compression="gzip",
        )


        del X


        if (
            device.type
            == "mps"
        ):

            torch.mps.empty_cache()


        for policy in [
            "strict",
            "early_0p5s",
        ]:

            grid_rows = []


            for threshold in (
                THRESHOLDS
            ):

                for consecutive in (
                    CONSECUTIVE_OPTIONS
                ):

                    (
                        metrics,
                        _,
                    ) = evaluate_policy(
                        pred,
                        threshold,
                        consecutive,
                        policy,
                    )


                    row = {
                        "model":
                            model_name,

                        **metrics,
                    }


                    grid_rows.append(
                        row
                    )


                    all_grid.append(
                        row
                    )


            grid = pd.DataFrame(
                grid_rows
            )


            (
                best,
                mode,
            ) = select_operating_point(
                grid
            )


            print_selected(
                model_name,
                policy,
                best,
                mode,
            )


            (
                _,
                details,
            ) = evaluate_policy(

                pred,

                float(
                    best[
                        "threshold"
                    ]
                ),

                int(
                    best[
                        "consecutive"
                    ]
                ),

                policy,
            )


            details.to_csv(

                OUT_ROOT
                / (
                    f"{model_name}_"
                    f"{policy}_"
                    "selected_details.csv"
                ),

                index=False,
            )


            selected_rows.append(
                {
                    "model":
                        model_name,

                    "policy":
                        policy,

                    "selection_mode":
                        mode,

                    **{
                        key:
                            best[
                                key
                            ]

                        for key
                        in best.index
                    },
                }
            )


    grid_df = pd.DataFrame(
        all_grid
    )


    selected_df = pd.DataFrame(
        selected_rows
    )


    grid_df.to_csv(

        OUT_ROOT
        / "validation_grid_all.csv",

        index=False,
    )


    selected_df.to_csv(

        OUT_ROOT
        / "selected_operating_points.csv",

        index=False,
    )


    print()
    print(
        "=" * 90
    )


    print(
        "FINAL COMPARISON"
    )


    print(
        "=" * 90
    )


    cols = [
        "model",
        "policy",
        "selection_mode",
        "threshold",
        "consecutive",
        "event_recall_by_end",
        "event_recall_by_plus_1s",
        "event_recall_by_plus_2s",
        "median_latency_sec",
        "false_alarms_per_hour",
        "nonfall_video_false_alarm_rate",
    ]


    print(
        selected_df[
            cols
        ]
        .sort_values(
            [
                "policy",
                "model",
            ]
        )
        .to_string(
            index=False
        )
    )


    print()
    print(
        "saved:",
        OUT_ROOT,
    )


    print(
        "NOTE: test set was NOT loaded."
    )


if __name__ == "__main__":

    main()
