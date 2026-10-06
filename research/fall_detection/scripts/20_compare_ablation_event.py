from pathlib import Path
import importlib.util

import numpy as np
import pandas as pd


BASE_SCRIPT = Path(
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


# ============================================================
# Development profile constraints
#
# IMPORTANT:
# These are NOT production specifications.
# They are common constraints for model comparison.
# ============================================================

PROFILES = {

    "safety": {

        "core": {
            "event_recall_by_plus_1s_min": 0.95,
            "event_recall_by_end_min": 0.80,
            "p95_latency_sec_max": 1.30,
            "nonfall_video_false_alarm_rate_max": 0.15,
        },

        "robust": {
            "local_min_recall_plus_1s_min": 0.93,
            "local_min_recall_by_end_min": 0.70,
            "local_max_nonfall_fa_max": 0.17,
            "local_max_p95_latency_max": 1.45,
        },

        "sort": [
            ("local_min_recall_plus_1s", False),
            ("local_min_recall_by_end", False),
            ("local_max_nonfall_fa", True),
            ("nonfall_video_false_alarm_rate", True),
            ("local_max_p95_latency", True),
        ],
    },


    "balanced": {

        "core": {
            "event_recall_by_plus_1s_min": 0.93,
            "event_recall_by_end_min": 0.80,
            "p95_latency_sec_max": 1.30,
            "nonfall_video_false_alarm_rate_max": 0.125,
        },

        "robust": {
            "local_min_recall_plus_1s_min": 0.90,
            "local_min_recall_by_end_min": 0.65,
            "local_max_nonfall_fa_max": 0.14,
            "local_max_p95_latency_max": 1.45,
        },

        "sort": [
            ("local_max_nonfall_fa", True),
            ("nonfall_video_false_alarm_rate", True),
            ("local_min_recall_plus_1s", False),
            ("local_min_recall_by_end", False),
            ("local_max_p95_latency", True),
        ],
    },


    "quiet": {

        "core": {
            "event_recall_by_plus_1s_min": 0.90,
            "event_recall_by_end_min": 0.75,
            "p95_latency_sec_max": 1.35,
            "nonfall_video_false_alarm_rate_max": 0.10,
        },

        "robust": {
            "local_min_recall_plus_1s_min": 0.88,
            "local_min_recall_by_end_min": 0.55,
            "local_max_nonfall_fa_max": 0.125,
            "local_max_p95_latency_max": 1.45,
        },

        "sort": [
            ("local_max_nonfall_fa", True),
            ("nonfall_video_false_alarm_rate", True),
            ("local_min_recall_plus_1s", False),
            ("local_min_recall_by_end", False),
            ("local_max_p95_latency", True),
        ],
    },
}


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
            "Could not load script 16"
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


def add_local_stability(
    df,
):

    result = df.copy()

    local_min_recall_1s = []
    local_min_recall_end = []

    local_max_nonfall_fa = []
    local_max_p95 = []

    for _, row in df.iterrows():

        neighborhood = df[
            (
                np.abs(
                    df["threshold"]
                    - row["threshold"]
                )
                <= 0.0200001
            )
            &
            (
                np.abs(
                    df["consecutive"]
                    - row["consecutive"]
                )
                <= 1
            )
        ]

        local_min_recall_1s.append(
            neighborhood[
                "event_recall_by_plus_1s"
            ].min()
        )

        local_min_recall_end.append(
            neighborhood[
                "event_recall_by_end"
            ].min()
        )

        local_max_nonfall_fa.append(
            neighborhood[
                "nonfall_video_false_alarm_rate"
            ].max()
        )

        local_max_p95.append(
            neighborhood[
                "p95_latency_sec"
            ].max()
        )

    result[
        "local_min_recall_plus_1s"
    ] = local_min_recall_1s

    result[
        "local_min_recall_by_end"
    ] = local_min_recall_end

    result[
        "local_max_nonfall_fa"
    ] = local_max_nonfall_fa

    result[
        "local_max_p95_latency"
    ] = local_max_p95

    return result


def apply_constraints(
    df,
    constraints,
):

    mask = pd.Series(
        True,
        index=df.index,
    )

    for name, value in (
        constraints.items()
    ):

        if name.endswith("_min"):

            column = name[:-4]

            mask &= (
                df[column]
                >= value
            )

        elif name.endswith("_max"):

            column = name[:-4]

            mask &= (
                df[column]
                <= value
            )

        else:

            raise RuntimeError(
                f"Unknown constraint: {name}"
            )

    return (
        df[mask]
        .copy()
        .reset_index(drop=True)
    )


def sort_candidates(
    df,
    sort_spec,
):

    if df.empty:
        return df

    columns = [
        x[0]
        for x in sort_spec
    ]

    ascending = [
        x[1]
        for x in sort_spec
    ]

    return (
        df
        .sort_values(
            columns,
            ascending=ascending,
        )
        .reset_index(drop=True)
    )


def choose_profile(
    df,
    profile,
    config,
):

    core = apply_constraints(
        df,
        config["core"],
    )

    core = sort_candidates(
        core,
        config["sort"],
    )

    robust = apply_constraints(
        core,
        config["robust"],
    )

    robust = sort_candidates(
        robust,
        config["sort"],
    )

    if not robust.empty:

        row = robust.iloc[0].copy()

        mode = "ROBUST"

    elif not core.empty:

        row = core.iloc[0].copy()

        mode = "CORE_ONLY"

    else:

        return None

    row["profile"] = profile
    row["selection_mode"] = mode

    return row


def print_selected(
    selected,
):

    print()

    print(
        "=" * 130
    )

    print(
        "FINAL EVENT-LEVEL ABLATION PROFILE SUMMARY"
    )

    print(
        "=" * 130
    )

    if selected.empty:

        print(
            "NO PROFILE CANDIDATES"
        )

        return

    cols = [

        "model",
        "profile",
        "selection_mode",

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

        "local_min_recall_plus_1s",
        "local_min_recall_by_end",

        "local_max_nonfall_fa",
        "local_max_p95_latency",
    ]

    print(
        selected[
            cols
        ]
        .sort_values(
            [
                "profile",
                "selection_mode",
                "model",
            ]
        )
        .to_string(
            index=False,
            float_format=lambda x: f"{x:.4f}",
        )
    )


def main():

    OUT_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    evaluator = (
        load_corrected_evaluator()
    )

    print(
        "=" * 110
    )

    print(
        "4-WAY GRU STRICT EVENT ABLATION"
    )

    print(
        "=" * 110
    )

    print(
        "policy          : strict"
    )

    print(
        "thresholds      :",
        len(THRESHOLDS),
    )

    print(
        "consecutive     :",
        (
            min(CONSECUTIVE_OPTIONS),
            max(CONSECUTIVE_OPTIONS),
        ),
    )

    print(
        "TEST SET        : NOT LOADED"
    )

    all_model_grids = []

    selected_rows = []

    for model_name, pred_path in (
        MODELS.items()
    ):

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

        if not pred_path.exists():

            raise RuntimeError(
                f"Missing: {pred_path}"
            )

        pred = (
            evaluator
            .load_predictions(
                model_name,
                pred_path,
            )
        )

        print(
            "prediction rows:",
            len(pred),
        )

        print(
            "scenes         :",
            pred["scene_id"].nunique(),
        )

        rows = []

        total = (
            len(THRESHOLDS)
            * len(CONSECUTIVE_OPTIONS)
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

                row = {
                    "model":
                        model_name,

                    **metrics,
                }

                rows.append(
                    row
                )

                if (
                    counter % 200 == 0
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

        grid = add_local_stability(
            grid
        )

        grid.to_csv(
            OUT_ROOT
            / f"{model_name}_strict_grid.csv",
            index=False,
        )

        all_model_grids.append(
            grid
        )

        for profile, config in (
            PROFILES.items()
        ):

            best = choose_profile(
                grid,
                profile,
                config,
            )

            if best is None:

                print(
                    f"{profile:8s}: "
                    "NO ACCEPTABLE CANDIDATE"
                )

                continue

            selected_rows.append(
                best
            )

            print(
                f"{profile:8s}: "
                f"{best['selection_mode']:9s} "
                f"thr={best['threshold']:.3f} "
                f"k={int(best['consecutive'])} "
                f"end={best['event_recall_by_end']:.4f} "
                f"+1s={best['event_recall_by_plus_1s']:.4f} "
                f"p95={best['p95_latency_sec']:.4f} "
                f"nonfall="
                f"{best['nonfall_video_false_alarm_rate']:.4f}"
            )

    all_grid = pd.concat(
        all_model_grids,
        ignore_index=True,
    )

    all_grid.to_csv(
        OUT_ROOT
        / "all_models_strict_grid.csv",
        index=False,
    )

    selected = pd.DataFrame(
        selected_rows
    )

    selected.to_csv(
        OUT_ROOT
        / "selected_profiles.csv",
        index=False,
    )

    print_selected(
        selected
    )

    print()

    print(
        "=" * 110
    )

    print(
        "WINDOW-LEVEL REFERENCE"
    )

    print(
        "=" * 110
    )

    window_path = Path(
        "runs/gru_ablation_window_summary.csv"
    )

    if window_path.exists():

        window = pd.read_csv(
            window_path
        )

        print(
            window.to_string(
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
