from pathlib import Path
import importlib.util

import numpy as np
import pandas as pd


BASE_EVALUATOR = Path(
    "scripts/16_compare_event_val_corrected.py"
)

OUT_ROOT = Path(
    "runs/gru_ablation_event"
)


MODELS = {
    "A_76_inverse": Path(
        "runs/event_compare_v1_v2_val/"
        "v1_val_predictions.csv.gz"
    ),

    "B_76_sqrt": Path(
        "runs/gru_ablation_76_sqrt/"
        "val_predictions.csv.gz"
    ),

    "C_125_inverse": Path(
        "runs/gru_ablation_125_inverse/"
        "val_predictions.csv.gz"
    ),

    "D_125_sqrt": Path(
        "runs/event_compare_v1_v2_val/"
        "v2_val_predictions.csv.gz"
    ),
}


THRESHOLDS = sorted(
    set(
        [
            round(
                x,
                3,
            )
            for x in np.arange(
                0.30,
                0.991,
                0.01,
            )
        ]
        +
        [
            0.995,
            0.997,
            0.999,
        ]
    )
)


CONSECUTIVE_OPTIONS = list(
    range(
        1,
        13,
    )
)


def load_evaluator():

    spec = (
        importlib.util
        .spec_from_file_location(
            "event16",
            BASE_EVALUATOR,
        )
    )

    if (
        spec is None
        or spec.loader is None
    ):

        raise RuntimeError(
            "Could not load "
            "corrected evaluator"
        )

    module = (
        importlib.util
        .module_from_spec(
            spec
        )
    )

    spec.loader.exec_module(
        module
    )

    return module


def load_model_predictions(
    evaluator,
    name,
    path,
):

    if not path.exists():

        raise RuntimeError(
            f"Missing: {path}"
        )

    # 모두 3-class 모델
    # alert_score =
    # P(falling) + P(fallen)

    df = pd.read_csv(
        path
    )

    required = {
        "scene_id",
        "timestamp",
        "phase",
        "prob_falling",
        "prob_fallen",
    }

    missing = (
        required
        - set(
            df.columns
        )
    )

    if missing:

        raise RuntimeError(
            f"{name}: "
            f"missing "
            f"{sorted(missing)}"
        )

    df[
        "alert_score"
    ] = (
        df[
            "prob_falling"
        ]
        +
        df[
            "prob_fallen"
        ]
    )

    df[
        "alert_score"
    ] = np.clip(
        df[
            "alert_score"
        ],
        0.0,
        1.0,
    )

    return df


def make_grid(
    evaluator,
    pred,
):

    rows = []

    total = (
        len(
            THRESHOLDS
        )
        *
        len(
            CONSECUTIVE_OPTIONS
        )
    )

    counter = 0

    for threshold in THRESHOLDS:

        for consecutive in (
            CONSECUTIVE_OPTIONS
        ):

            counter += 1

            metrics = (
                evaluator.evaluate(
                    pred,
                    threshold,
                    consecutive,
                    "strict",
                )
            )

            rows.append(
                metrics
            )

            if (
                counter % 150 == 0
                or counter == total
            ):

                print(
                    f"  "
                    f"[{counter:04d}/"
                    f"{total:04d}] "
                    f"thr="
                    f"{threshold:.3f} "
                    f"k="
                    f"{consecutive}"
                )

    return pd.DataFrame(
        rows
    )


def pareto_frontier(
    df,
):

    # Objectives:
    #
    # maximize:
    # - recall end
    # - recall +1s
    #
    # minimize:
    # - nonfall FA
    # - p95 latency

    data = (
        df
        .reset_index(
            drop=True
        )
    )

    keep = []

    values = data[
        [
            "event_recall_by_end",
            "event_recall_by_plus_1s",
            "nonfall_video_false_alarm_rate",
            "p95_latency_sec",
        ]
    ].to_numpy(
        dtype=float
    )

    n = len(
        data
    )

    for i in range(
        n
    ):

        a = values[i]

        dominated = False

        for j in range(
            n
        ):

            if i == j:
                continue

            b = values[j]

            not_worse = (
                b[0] >= a[0]
                and b[1] >= a[1]
                and b[2] <= a[2]
                and b[3] <= a[3]
            )

            strictly_better = (
                b[0] > a[0]
                or b[1] > a[1]
                or b[2] < a[2]
                or b[3] < a[3]
            )

            if (
                not_worse
                and strictly_better
            ):

                dominated = True
                break

        if not dominated:

            keep.append(
                i
            )

    return (
        data.iloc[
            keep
        ]
        .copy()
        .sort_values(
            [
                "nonfall_video_false_alarm_rate",
                "event_recall_by_plus_1s",
            ],
            ascending=[
                True,
                False,
            ],
        )
        .reset_index(
            drop=True
        )
    )


def select_profile(
    grid,
    profile,
):

    if profile == "fast":

        eligible = grid[
            (
                grid[
                    "event_recall_by_end"
                ]
                >= 0.85
            )
            &
            (
                grid[
                    "event_recall_by_plus_1s"
                ]
                >= 0.93
            )
            &
            (
                grid[
                    "p95_latency_sec"
                ]
                <= 1.30
            )
            &
            (
                grid[
                    "nonfall_video_false_alarm_rate"
                ]
                <= 0.20
            )
        ].copy()

    elif profile == "balanced":

        eligible = grid[
            (
                grid[
                    "event_recall_by_end"
                ]
                >= 0.83
            )
            &
            (
                grid[
                    "event_recall_by_plus_1s"
                ]
                >= 0.93
            )
            &
            (
                grid[
                    "p95_latency_sec"
                ]
                <= 1.30
            )
            &
            (
                grid[
                    "nonfall_video_false_alarm_rate"
                ]
                <= 0.15
            )
        ].copy()

    elif profile == "quiet":

        eligible = grid[
            (
                grid[
                    "event_recall_by_end"
                ]
                >= 0.75
            )
            &
            (
                grid[
                    "p95_latency_sec"
                ]
                <= 1.35
            )
            &
            (
                grid[
                    "nonfall_video_false_alarm_rate"
                ]
                <= 0.10
            )
        ].copy()

    else:

        raise ValueError(
            profile
        )

    if eligible.empty:

        return None

    # 공통:
    # 1. +1s recall 최대
    # 2. end recall 최대
    # 3. nonfall FA 최소
    # 4. p95 최소
    # 5. median 최소

    return (
        eligible
        .sort_values(
            [
                "event_recall_by_plus_1s",
                "event_recall_by_end",
                "nonfall_video_false_alarm_rate",
                "false_alarms_per_hour",
                "p95_latency_sec",
                "median_latency_sec",
            ],
            ascending=[
                False,
                False,
                True,
                True,
                True,
                True,
            ],
        )
        .iloc[0]
    )


def print_profile(
    model,
    profile,
    row,
):

    print()

    if row is None:

        print(
            f"{model} / "
            f"{profile.upper()}: "
            f"NO CANDIDATE"
        )

        return

    print(
        f"{model} / "
        f"{profile.upper()}"
    )

    print(
        "  threshold        :",
        f"{row['threshold']:.3f}",
    )

    print(
        "  consecutive      :",
        int(
            row[
                "consecutive"
            ]
        ),
    )

    print(
        "  recall end       :",
        f"{row['event_recall_by_end']:.4f}",
    )

    print(
        "  recall +1s       :",
        f"{row['event_recall_by_plus_1s']:.4f}",
    )

    print(
        "  recall +2s       :",
        f"{row['event_recall_by_plus_2s']:.4f}",
    )

    print(
        "  median latency   :",
        f"{row['median_latency_sec']:.4f}s",
    )

    print(
        "  p95 latency      :",
        f"{row['p95_latency_sec']:.4f}s",
    )

    print(
        "  nonfall FA rate  :",
        f"{row['nonfall_video_false_alarm_rate']:.4f}",
    )

    print(
        "  FA/hour          :",
        f"{row['false_alarms_per_hour']:.4f}",
    )

    print(
        "  prefall FA rate  :",
        f"{row['prefall_false_alarm_video_rate']:.4f}",
    )


def main():

    OUT_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    evaluator = (
        load_evaluator()
    )

    print(
        "=" * 110
    )

    print(
        "4-WAY GRU EVENT-LEVEL ABLATION"
    )

    print(
        "=" * 110
    )

    print(
        "policy : STRICT ONLY"
    )

    print(
        "test   : NOT LOADED"
    )

    print()

    print(
        "FAST:"
    )
    print(
        "  end>=85%, +1s>=93%, "
        "p95<=1.30s, nonfall FA<=20%"
    )

    print(
        "BALANCED:"
    )
    print(
        "  end>=83%, +1s>=93%, "
        "p95<=1.30s, nonfall FA<=15%"
    )

    print(
        "QUIET:"
    )
    print(
        "  end>=75%, "
        "p95<=1.35s, nonfall FA<=10%"
    )

    summaries = []

    all_grids = []

    for (
        model_name,
        prediction_path,
    ) in MODELS.items():

        print()
        print(
            "=" * 110
        )

        print(
            "MODEL:",
            model_name
        )

        print(
            "=" * 110
        )

        pred = (
            load_model_predictions(
                evaluator,
                model_name,
                prediction_path,
            )
        )

        print(
            "rows  :",
            len(
                pred
            )
        )

        print(
            "scenes:",
            pred[
                "scene_id"
            ].nunique(),
        )

        grid = make_grid(
            evaluator,
            pred,
        )

        grid.insert(
            0,
            "model",
            model_name,
        )

        all_grids.append(
            grid
        )

        grid.to_csv(
            OUT_ROOT
            / (
                f"{model_name}"
                "_strict_grid.csv"
            ),
            index=False,
        )

        pareto = (
            pareto_frontier(
                grid
            )
        )

        pareto.to_csv(
            OUT_ROOT
            / (
                f"{model_name}"
                "_strict_pareto.csv"
            ),
            index=False,
        )

        for profile in [
            "fast",
            "balanced",
            "quiet",
        ]:

            row = (
                select_profile(
                    grid,
                    profile,
                )
            )

            print_profile(
                model_name,
                profile,
                row,
            )

            if row is None:

                summaries.append(
                    {
                        "model":
                            model_name,

                        "profile":
                            profile,

                        "candidate":
                            False,
                    }
                )

            else:

                summaries.append(
                    {
                        "model":
                            model_name,

                        "profile":
                            profile,

                        "candidate":
                            True,

                        "threshold":
                            float(
                                row[
                                    "threshold"
                                ]
                            ),

                        "consecutive":
                            int(
                                row[
                                    "consecutive"
                                ]
                            ),

                        "recall_end":
                            float(
                                row[
                                    "event_recall_by_end"
                                ]
                            ),

                        "recall_plus_1s":
                            float(
                                row[
                                    "event_recall_by_plus_1s"
                                ]
                            ),

                        "recall_plus_2s":
                            float(
                                row[
                                    "event_recall_by_plus_2s"
                                ]
                            ),

                        "median_latency":
                            float(
                                row[
                                    "median_latency_sec"
                                ]
                            ),

                        "p95_latency":
                            float(
                                row[
                                    "p95_latency_sec"
                                ]
                            ),

                        "nonfall_fa":
                            float(
                                row[
                                    "nonfall_video_false_alarm_rate"
                                ]
                            ),

                        "fa_per_hour":
                            float(
                                row[
                                    "false_alarms_per_hour"
                                ]
                            ),

                        "prefall_fa":
                            float(
                                row[
                                    "prefall_false_alarm_video_rate"
                                ]
                            ),
                    }
                )

    summary = pd.DataFrame(
        summaries
    )

    all_grid = pd.concat(
        all_grids,
        ignore_index=True,
    )

    all_grid.to_csv(
        OUT_ROOT
        / "all_models_strict_grid.csv",
        index=False,
    )

    summary.to_csv(
        OUT_ROOT
        / "selected_profiles.csv",
        index=False,
    )

    print()
    print(
        "=" * 110
    )

    print(
        "FINAL EVENT ABLATION"
    )

    print(
        "=" * 110
    )

    display_cols = [
        "model",
        "profile",
        "candidate",
        "threshold",
        "consecutive",
        "recall_end",
        "recall_plus_1s",
        "recall_plus_2s",
        "median_latency",
        "p95_latency",
        "nonfall_fa",
        "fa_per_hour",
    ]

    for col in display_cols:

        if col not in (
            summary.columns
        ):

            summary[
                col
            ] = np.nan

    print(
        summary[
            display_cols
        ]
        .sort_values(
            [
                "profile",
                "model",
            ]
        )
        .to_string(
            index=False,
            float_format=lambda x:
                f"{x:.4f}",
        )
    )

    print()
    print(
        "saved:",
        OUT_ROOT
    )

    print(
        "TEST SET WAS NOT LOADED."
    )


if __name__ == "__main__":
    main()
