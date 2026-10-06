from pathlib import Path
import importlib.util

import numpy as np
import pandas as pd

from sklearn.metrics import (
    average_precision_score,
    roc_auc_score,
    brier_score_loss,
)


BASE_SCRIPT = Path(
    "scripts/20_compare_ablation_event.py"
)

OLD_GRID_ROOT = Path(
    "runs/gru_bd_multiseed_event"
)

OUT_ROOT = Path(
    "runs/gru_bd_score_stability"
)

MODELS = [
    "B_76_sqrt",
    "D_125_sqrt",
]

SEEDS = [
    42,
    123,
    2026,
]


BUDGETS = {
    "FA10": {
        "nonfall_max": 0.10,
        "p95_max": 1.35,
    },

    "FA15": {
        "nonfall_max": 0.15,
        "p95_max": 1.30,
    },

    "FA20": {
        "nonfall_max": 0.20,
        "p95_max": 1.30,
    },
}


def load_script20():

    spec = (
        importlib.util
        .spec_from_file_location(
            "event20",
            BASE_SCRIPT,
        )
    )

    if (
        spec is None
        or spec.loader is None
    ):
        raise RuntimeError(
            f"Could not load {BASE_SCRIPT}"
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


def prediction_path(
    model,
    seed,
):

    return (
        Path("runs/gru_multiseed")
        / model
        / f"seed_{seed}"
        / "val_predictions.csv.gz"
    )


def old_grid_path(
    model,
    seed,
):

    return (
        OLD_GRID_ROOT
        / f"{model}_seed_{seed}_grid.csv"
    )


def load_prediction(
    model,
    seed,
):

    path = prediction_path(
        model,
        seed,
    )

    if not path.exists():

        raise RuntimeError(
            f"Missing: {path}"
        )

    df = pd.read_csv(
        path
    )

    df["alert_score"] = np.clip(
        df["prob_falling"]
        + df["prob_fallen"],
        0.0,
        1.0,
    )

    return df


def ece_binary(
    y_true,
    score,
    bins=15,
):

    edges = np.linspace(
        0.0,
        1.0,
        bins + 1,
    )

    result = 0.0
    total = len(y_true)

    for i in range(bins):

        lo = edges[i]
        hi = edges[i + 1]

        if i == bins - 1:

            mask = (
                (score >= lo)
                &
                (score <= hi)
            )

        else:

            mask = (
                (score >= lo)
                &
                (score < hi)
            )

        n = int(
            mask.sum()
        )

        if n == 0:
            continue

        confidence = float(
            score[mask].mean()
        )

        accuracy = float(
            y_true[mask].mean()
        )

        result += (
            n
            / total
            * abs(
                confidence
                - accuracy
            )
        )

    return float(
        result
    )


def diagnostics(
    model,
    seed,
    df,
):

    y_alert = (
        df["y_true"]
        .to_numpy(
            dtype=np.int64
        )
        != 0
    ).astype(
        np.int64
    )

    score = (
        df["alert_score"]
        .to_numpy(
            dtype=float
        )
    )

    normal = score[
        y_alert == 0
    ]

    alert = score[
        y_alert == 1
    ]

    return {
        "model":
            model,

        "seed":
            seed,

        "roc_auc":
            roc_auc_score(
                y_alert,
                score,
            ),

        "average_precision":
            average_precision_score(
                y_alert,
                score,
            ),

        "brier":
            brier_score_loss(
                y_alert,
                score,
            ),

        "ece15":
            ece_binary(
                y_alert,
                score,
            ),

        "normal_q50":
            np.quantile(
                normal,
                0.50,
            ),

        "normal_q90":
            np.quantile(
                normal,
                0.90,
            ),

        "normal_q95":
            np.quantile(
                normal,
                0.95,
            ),

        "normal_q99":
            np.quantile(
                normal,
                0.99,
            ),

        "alert_q10":
            np.quantile(
                alert,
                0.10,
            ),

        "alert_q50":
            np.quantile(
                alert,
                0.50,
            ),

        "alert_q90":
            np.quantile(
                alert,
                0.90,
            ),
    }


def select_budget(
    grid,
    budget_name,
    cfg,
):

    eligible = grid[
        (
            grid[
                "nonfall_video_false_alarm_rate"
            ]
            <= cfg[
                "nonfall_max"
            ]
        )
        &
        (
            grid[
                "p95_latency_sec"
            ]
            <= cfg[
                "p95_max"
            ]
        )
    ].copy()

    if eligible.empty:

        return {
            "budget":
                budget_name,

            "candidate":
                False,
        }

    best = (
        eligible
        .sort_values(
            [
                "event_recall_by_plus_1s",
                "event_recall_by_end",
                "event_recall_by_plus_2s",
                "nonfall_video_false_alarm_rate",
                "p95_latency_sec",
            ],
            ascending=[
                False,
                False,
                False,
                True,
                True,
            ],
        )
        .iloc[0]
    )

    row = best.to_dict()

    row["budget"] = (
        budget_name
    )

    row["candidate"] = True

    return row


def check_alignment(
    base,
    other,
):

    for column in [
        "scene_id",
        "timestamp",
        "phase",
        "y_true",
    ]:

        if not (
            base[column]
            .reset_index(
                drop=True
            )
            .equals(
                other[column]
                .reset_index(
                    drop=True
                )
            )
        ):

            raise RuntimeError(
                f"Alignment mismatch: "
                f"{column}"
            )


def make_ensemble(
    frames,
):

    base = (
        frames[0]
        .copy()
        .reset_index(
            drop=True
        )
    )

    for other in frames[1:]:

        check_alignment(
            base,
            other,
        )

    for column in [
        "prob_normal",
        "prob_falling",
        "prob_fallen",
    ]:

        values = np.stack(
            [
                x[column]
                .to_numpy(
                    dtype=float
                )
                for x in frames
            ],
            axis=0,
        )

        base[column] = (
            values.mean(
                axis=0
            )
        )

    base[
        "alert_score"
    ] = np.clip(
        base["prob_falling"]
        + base["prob_fallen"],
        0.0,
        1.0,
    )

    return base


def build_ensemble_grid(
    m20,
    evaluator,
    pred,
):

    rows = []

    total = (
        len(m20.THRESHOLDS)
        *
        len(
            m20.CONSECUTIVE_OPTIONS
        )
    )

    counter = 0

    for threshold in (
        m20.THRESHOLDS
    ):

        for consecutive in (
            m20.CONSECUTIVE_OPTIONS
        ):

            counter += 1

            rows.append(
                evaluator.evaluate(
                    pred,
                    threshold,
                    consecutive,
                    "strict",
                )
            )

            if (
                counter % 100 == 0
                or counter == total
            ):

                print(
                    f"    grid "
                    f"{counter:4d}/{total} "
                    f"thr={threshold:.3f} "
                    f"k={consecutive}",
                    flush=True,
                )

    return pd.DataFrame(
        rows
    )


def main():

    OUT_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    m20 = load_script20()

    evaluator = (
        m20.load_corrected_evaluator()
    )

    print(
        "=" * 120
    )

    print(
        "B vs D SCORE-STABILITY "
        "DIAGNOSTIC - FAST VERSION"
    )

    print(
        "=" * 120
    )

    print(
        "Existing per-seed event grids "
        "will be reused."
    )

    print(
        "TEST SET: NOT LOADED"
    )

    diag_rows = []
    budget_rows = []

    loaded = {}

    # ========================================================
    # 1. Per-seed score diagnostics
    #    + reuse Script 22 event grids
    # ========================================================

    for model in MODELS:

        loaded[model] = []

        for seed in SEEDS:

            print(
                f"[LOAD] {model} "
                f"seed={seed}",
                flush=True,
            )

            pred = load_prediction(
                model,
                seed,
            )

            loaded[
                model
            ].append(
                pred
            )

            diag_rows.append(
                diagnostics(
                    model,
                    seed,
                    pred,
                )
            )

            grid_path = (
                old_grid_path(
                    model,
                    seed,
                )
            )

            if not grid_path.exists():

                raise RuntimeError(
                    "Missing existing "
                    f"Script 22 grid: "
                    f"{grid_path}"
                )

            print(
                f"       reuse "
                f"{grid_path}",
                flush=True,
            )

            grid = pd.read_csv(
                grid_path
            )

            for (
                budget_name,
                budget_cfg,
            ) in BUDGETS.items():

                row = select_budget(
                    grid,
                    budget_name,
                    budget_cfg,
                )

                row[
                    "model"
                ] = model

                row[
                    "seed"
                ] = seed

                budget_rows.append(
                    row
                )

    diag_df = pd.DataFrame(
        diag_rows
    )

    budget_df = pd.DataFrame(
        budget_rows
    )

    diag_df.to_csv(
        OUT_ROOT
        / "score_diagnostics.csv",
        index=False,
    )

    budget_df.to_csv(
        OUT_ROOT
        / "fixed_fa_budget_per_seed.csv",
        index=False,
    )

    # ========================================================
    # 2. 3-seed probability ensemble
    # ========================================================

    ensemble_diag_rows = []
    ensemble_profile_rows = []

    for model in MODELS:

        print()
        print(
            "=" * 120
        )

        print(
            f"ENSEMBLE: {model}"
        )

        print(
            "=" * 120
        )

        ensemble = make_ensemble(
            loaded[
                model
            ]
        )

        ensemble_diag_rows.append(
            diagnostics(
                model,
                "ensemble",
                ensemble,
            )
        )

        grid_path = (
            OUT_ROOT
            / (
                f"{model}_"
                "ensemble_strict_grid.csv"
            )
        )

        if grid_path.exists():

            print(
                "  reuse existing "
                "ensemble grid",
                flush=True,
            )

            stable_grid = (
                pd.read_csv(
                    grid_path
                )
            )

        else:

            print(
                "  calculating ensemble "
                "event grid...",
                flush=True,
            )

            grid = (
                build_ensemble_grid(
                    m20,
                    evaluator,
                    ensemble,
                )
            )

            stable_grid = (
                m20
                .add_local_stability(
                    grid
                )
            )

            stable_grid.to_csv(
                grid_path,
                index=False,
            )

        for profile, config in (
            m20.PROFILES.items()
        ):

            best = (
                m20.choose_profile(
                    stable_grid,
                    profile,
                    config,
                )
            )

            if best is None:

                print(
                    f"  {profile:8s}: NONE"
                )

                ensemble_profile_rows.append(
                    {
                        "model":
                            model,

                        "profile":
                            profile,

                        "selection_mode":
                            "NONE",
                    }
                )

            else:

                row = best.to_dict()

                row["model"] = model
                row["profile"] = profile

                ensemble_profile_rows.append(
                    row
                )

                print(
                    f"  {profile:8s}: "
                    f"{row['selection_mode']:9s} "
                    f"thr="
                    f"{row['threshold']:.3f} "
                    f"k="
                    f"{int(row['consecutive'])} "
                    f"end="
                    f"{row['event_recall_by_end']:.4f} "
                    f"+1s="
                    f"{row['event_recall_by_plus_1s']:.4f} "
                    f"nonfall="
                    f"{row['nonfall_video_false_alarm_rate']:.4f}"
                )

    ensemble_diag_df = pd.DataFrame(
        ensemble_diag_rows
    )

    ensemble_profiles_df = pd.DataFrame(
        ensemble_profile_rows
    )

    ensemble_diag_df.to_csv(
        OUT_ROOT
        / "ensemble_score_diagnostics.csv",
        index=False,
    )

    ensemble_profiles_df.to_csv(
        OUT_ROOT
        / "ensemble_profiles.csv",
        index=False,
    )

    # ========================================================
    # Print
    # ========================================================

    print()
    print(
        "=" * 120
    )

    print(
        "PER-SEED SCORE DIAGNOSTICS"
    )

    print(
        "=" * 120
    )

    print(
        diag_df[
            [
                "model",
                "seed",
                "roc_auc",
                "average_precision",
                "brier",
                "ece15",
                "normal_q90",
                "normal_q95",
                "normal_q99",
                "alert_q10",
                "alert_q50",
            ]
        ]
        .to_string(
            index=False,
            float_format=lambda x:
                f"{x:.5f}",
        )
    )

    print()
    print(
        "=" * 120
    )

    print(
        "FIXED FALSE-ALARM BUDGET"
    )

    print(
        "=" * 120
    )

    cols = [
        "model",
        "seed",
        "budget",
        "candidate",
        "threshold",
        "consecutive",
        "event_recall_by_end",
        "event_recall_by_plus_1s",
        "p95_latency_sec",
        "nonfall_video_false_alarm_rate",
    ]

    for col in cols:

        if col not in (
            budget_df.columns
        ):
            budget_df[col] = np.nan

    print(
        budget_df[
            cols
        ]
        .sort_values(
            [
                "budget",
                "model",
                "seed",
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
        "=" * 120
    )

    print(
        "ENSEMBLE SCORE DIAGNOSTICS"
    )

    print(
        "=" * 120
    )

    print(
        ensemble_diag_df.to_string(
            index=False,
            float_format=lambda x:
                f"{x:.5f}",
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
