from pathlib import Path
import importlib.util

import numpy as np
import pandas as pd


BASE_SCRIPT = Path(
    "scripts/16_compare_event_val_corrected.py"
)

PRED_PATH = Path(
    "runs/event_compare_v1_v2_val/"
    "v2_val_predictions.csv.gz"
)

OUT_ROOT = Path(
    "runs/gru_v2_operating_point"
)

POLICIES = [
    "strict",
    "early_0p5s",
]


# -------------------------------------------------
# Fine grid
# -------------------------------------------------

THRESHOLDS = sorted(
    set(
        [
            round(x, 3)
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


def load_corrected_evaluator():

    if not BASE_SCRIPT.exists():

        raise RuntimeError(
            f"Missing: {BASE_SCRIPT}"
        )

    spec = (
        importlib.util
        .spec_from_file_location(
            "event_eval16",
            BASE_SCRIPT,
        )
    )

    if (
        spec is None
        or spec.loader is None
    ):

        raise RuntimeError(
            "Could not load "
            "script 16"
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


def pareto_frontier(
    df,
):

    # ---------------------------------------------
    # Pareto:
    #
    # maximize recall +1s
    # minimize nonfall clip FA
    #
    # latency는 별도 표기한다.
    # ---------------------------------------------

    ordered = (
        df
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

    rows = []

    best_recall = -1.0

    for _, row in (
        ordered.iterrows()
    ):

        recall = float(
            row[
                "event_recall_by_plus_1s"
            ]
        )

        if (
            recall
            > best_recall
            + 1e-12
        ):

            rows.append(
                row
            )

            best_recall = (
                recall
            )

    return (
        pd.DataFrame(
            rows
        )
        .reset_index(
            drop=True
        )
    )


def select_min_fa_for_recall(
    df,
    recall_target,
):

    eligible = df[
        df[
            "event_recall_by_plus_1s"
        ]
        >= recall_target
    ].copy()

    if eligible.empty:

        return (
            None,
            "target_not_met",
        )

    best = (
        eligible
        .sort_values(
            [
                "nonfall_video_false_alarm_rate",
                "false_alarms_per_hour",
                "median_latency_sec",
                "event_recall_by_end",
                "threshold",
                "consecutive",
            ],
            ascending=[
                True,
                True,
                True,
                False,
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


def select_quiet(
    df,
    max_nonfall_fa=0.10,
):

    eligible = df[
        df[
            "nonfall_video_false_alarm_rate"
        ]
        <= max_nonfall_fa
    ].copy()

    if eligible.empty:

        minimum_fa = df[
            "nonfall_video_false_alarm_rate"
        ].min()

        eligible = df[
            df[
                "nonfall_video_false_alarm_rate"
            ]
            == minimum_fa
        ].copy()

        mode = (
            "10pct_not_met"
        )

    else:

        mode = (
            "within_10pct"
        )

    best = (
        eligible
        .sort_values(
            [
                "event_recall_by_plus_1s",
                "event_recall_by_end",
                "median_latency_sec",
                "false_alarms_per_hour",
            ],
            ascending=[
                False,
                False,
                True,
                True,
            ],
        )
        .iloc[0]
    )

    return (
        best,
        mode,
    )


def row_to_dict(
    row,
):

    return {
        key:
            row[key]

        for key
        in row.index
    }


def print_candidate(
    name,
    row,
    mode,
):

    if row is None:

        print()
        print(
            name,
            ": NO CANDIDATE"
        )

        return

    print()
    print(
        "-" * 90
    )

    print(
        name,
        "/",
        mode
    )

    print(
        "-" * 90
    )

    print(
        "threshold             :",
        f"{row['threshold']:.3f}",
    )

    print(
        "consecutive           :",
        int(
            row[
                "consecutive"
            ]
        ),
    )

    print(
        "recall by end         :",
        f"{row['event_recall_by_end']:.4f}",
    )

    print(
        "recall +1s            :",
        f"{row['event_recall_by_plus_1s']:.4f}",
    )

    print(
        "recall +2s            :",
        f"{row['event_recall_by_plus_2s']:.4f}",
    )

    print(
        "median latency        :",
        f"{row['median_latency_sec']:.4f}s",
    )

    print(
        "p95 latency           :",
        f"{row['p95_latency_sec']:.4f}s",
    )

    print(
        "false alarms/hour     :",
        f"{row['false_alarms_per_hour']:.4f}",
    )

    print(
        "nonfall clip FA rate  :",
        f"{row['nonfall_video_false_alarm_rate']:.4f}",
    )

    print(
        "prefall FA video rate :",
        f"{row['prefall_false_alarm_video_rate']:.4f}",
    )


def main():

    OUT_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    evaluator = (
        load_corrected_evaluator()
    )

    if not PRED_PATH.exists():

        raise RuntimeError(
            f"Missing: {PRED_PATH}"
        )

    pred = (
        evaluator
        .load_predictions(
            "v2",
            PRED_PATH,
        )
    )

    print(
        "=" * 100
    )

    print(
        "GRU V2 FINE OPERATING-POINT SEARCH"
    )

    print(
        "=" * 100
    )

    print(
        "prediction rows :",
        len(pred),
    )

    print(
        "scenes          :",
        pred[
            "scene_id"
        ].nunique(),
    )

    print(
        "thresholds      :",
        len(
            THRESHOLDS
        ),
    )

    print(
        "consecutive     :",
        (
            min(
                CONSECUTIVE_OPTIONS
            ),
            max(
                CONSECUTIVE_OPTIONS
            ),
        ),
    )

    print(
        "test set        : "
        "NOT LOADED"
    )

    all_rows = []

    selected_rows = []

    for policy in POLICIES:

        print()
        print(
            "=" * 100
        )

        print(
            "POLICY:",
            policy
        )

        print(
            "=" * 100
        )

        rows = []

        total = (
            len(
                THRESHOLDS
            )
            * len(
                CONSECUTIVE_OPTIONS
            )
        )

        counter = 0

        for threshold in (
            THRESHOLDS
        ):

            for consecutive in (
                CONSECUTIVE_OPTIONS
            ):

                counter += 1

                metrics = (
                    evaluator.evaluate(
                        pred,
                        threshold,
                        consecutive,
                        policy,
                    )
                )

                row = {
                    "model":
                        "v2",

                    **metrics,
                }

                rows.append(
                    row
                )

                all_rows.append(
                    row
                )

                if (
                    counter % 100 == 0
                    or counter == total
                ):

                    print(
                        f"[{counter:04d}/"
                        f"{total:04d}] "
                        f"thr={threshold:.3f} "
                        f"k={consecutive}"
                    )

        grid = pd.DataFrame(
            rows
        )

        grid.to_csv(
            OUT_ROOT
            / (
                f"grid_{policy}.csv"
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
                f"pareto_{policy}.csv"
            ),
            index=False,
        )

        safety, safety_mode = (
            select_min_fa_for_recall(
                grid,
                0.95,
            )
        )

        balanced, balanced_mode = (
            select_min_fa_for_recall(
                grid,
                0.93,
            )
        )

        quiet, quiet_mode = (
            select_quiet(
                grid,
                0.10,
            )
        )

        print_candidate(
            "SAFETY >=95%",
            safety,
            safety_mode,
        )

        print_candidate(
            "BALANCED >=93%",
            balanced,
            balanced_mode,
        )

        print_candidate(
            "QUIET <=10% FA",
            quiet,
            quiet_mode,
        )

        for (
            profile,
            row,
            mode,
        ) in [
            (
                "safety",
                safety,
                safety_mode,
            ),
            (
                "balanced",
                balanced,
                balanced_mode,
            ),
            (
                "quiet",
                quiet,
                quiet_mode,
            ),
        ]:

            if row is None:
                continue

            selected_rows.append(
                {
                    "policy":
                        policy,

                    "profile":
                        profile,

                    "mode":
                        mode,

                    **row_to_dict(
                        row
                    ),
                }
            )

    all_df = pd.DataFrame(
        all_rows
    )

    selected_df = pd.DataFrame(
        selected_rows
    )

    all_df.to_csv(
        OUT_ROOT
        / "grid_all.csv",
        index=False,
    )

    selected_df.to_csv(
        OUT_ROOT
        / "selected_profiles.csv",
        index=False,
    )

    print()
    print(
        "=" * 100
    )

    print(
        "FINAL SELECTED PROFILES"
    )

    print(
        "=" * 100
    )

    cols = [
        "policy",
        "profile",
        "mode",
        "threshold",
        "consecutive",
        "event_recall_by_end",
        "event_recall_by_plus_1s",
        "event_recall_by_plus_2s",
        "median_latency_sec",
        "p95_latency_sec",
        "false_alarms_per_hour",
        "nonfall_video_false_alarm_rate",
        "prefall_false_alarm_video_rate",
    ]

    print(
        selected_df[
            cols
        ]
        .sort_values(
            [
                "policy",
                "profile",
            ]
        )
        .to_string(
            index=False
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
