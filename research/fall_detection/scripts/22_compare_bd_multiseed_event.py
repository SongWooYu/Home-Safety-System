from pathlib import Path
import importlib.util

import pandas as pd


BASE_SCRIPT = Path(
    "scripts/20_compare_ablation_event.py"
)

OUT_ROOT = Path(
    "runs/gru_bd_multiseed_event"
)

SEEDS = [
    42,
    123,
    2026,
]

MODELS = [
    "B_76_sqrt",
    "D_125_sqrt",
]


# Frozen development operating points for D.
#
# These were selected BEFORE this multi-seed
# event evaluation and must not be re-tuned here.
D_FROZEN = {
    "safety": (
        0.680,
        6,
    ),
    "balanced": (
        0.920,
        4,
    ),
    "quiet": (
        0.930,
        5,
    ),
}


def load_script20():

    if not BASE_SCRIPT.exists():

        raise RuntimeError(
            f"Missing: {BASE_SCRIPT}"
        )

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
            "Could not load script 20"
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


def build_grid(
    m20,
    evaluator,
    pred,
):

    rows = []

    total = (
        len(m20.THRESHOLDS)
        *
        len(m20.CONSECUTIVE_OPTIONS)
    )

    counter = 0

    for threshold in m20.THRESHOLDS:

        for consecutive in (
            m20.CONSECUTIVE_OPTIONS
        ):

            counter += 1

            metrics = evaluator.evaluate(
                pred,
                threshold,
                consecutive,
                "strict",
            )

            rows.append(
                metrics
            )

            if (
                counter % 250 == 0
                or counter == total
            ):

                print(
                    f"  [{counter:04d}/"
                    f"{total:04d}] "
                    f"thr={threshold:.3f} "
                    f"k={consecutive}"
                )

    grid = pd.DataFrame(
        rows
    )

    return m20.add_local_stability(
        grid
    )


def check_constraints(
    metrics,
    constraints,
):

    for name, value in (
        constraints.items()
    ):

        if name.endswith("_min"):

            column = name[:-4]

            if (
                metrics[column]
                < value
            ):
                return False

        elif name.endswith("_max"):

            column = name[:-4]

            if (
                metrics[column]
                > value
            ):
                return False

    return True


def main():

    OUT_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    m20 = load_script20()

    evaluator = (
        m20.load_corrected_evaluator()
    )

    selected_rows = []

    frozen_rows = []

    print(
        "=" * 120
    )

    print(
        "B vs D MULTI-SEED STRICT EVENT REPRODUCIBILITY"
    )

    print(
        "=" * 120
    )

    print(
        "seeds:",
        SEEDS
    )

    print(
        "TEST SET: NOT LOADED"
    )

    for model in MODELS:

        for seed in SEEDS:

            print()
            print(
                "=" * 120
            )

            print(
                f"{model} / seed={seed}"
            )

            print(
                "=" * 120
            )

            path = prediction_path(
                model,
                seed,
            )

            if not path.exists():

                raise RuntimeError(
                    f"Missing: {path}"
                )

            pred = (
                evaluator.load_predictions(
                    f"{model}_seed_{seed}",
                    path,
                )
            )

            print(
                "rows  :",
                len(pred),
            )

            print(
                "scenes:",
                pred[
                    "scene_id"
                ].nunique(),
            )

            grid = build_grid(
                m20,
                evaluator,
                pred,
            )

            grid.insert(
                0,
                "seed",
                seed,
            )

            grid.insert(
                0,
                "model",
                model,
            )

            grid.to_csv(
                OUT_ROOT
                / (
                    f"{model}_"
                    f"seed_{seed}_grid.csv"
                ),
                index=False,
            )

            # ----------------------------------------
            # Re-optimized capability analysis
            #
            # This is NOT a deployment threshold.
            # It asks whether each trained model has
            # a robust operating region.
            # ----------------------------------------

            for profile, config in (
                m20.PROFILES.items()
            ):

                best = m20.choose_profile(
                    grid,
                    profile,
                    config,
                )

                if best is None:

                    selected_rows.append(
                        {
                            "model":
                                model,

                            "seed":
                                seed,

                            "profile":
                                profile,

                            "selection_mode":
                                "NONE",
                        }
                    )

                    print(
                        f"{profile:8s}: "
                        "NONE"
                    )

                    continue

                row = best.to_dict()

                row[
                    "model"
                ] = model

                row[
                    "seed"
                ] = seed

                row[
                    "profile"
                ] = profile

                selected_rows.append(
                    row
                )

                print(
                    f"{profile:8s}: "
                    f"{row['selection_mode']:9s} "
                    f"thr={row['threshold']:.3f} "
                    f"k={int(row['consecutive'])} "
                    f"end="
                    f"{row['event_recall_by_end']:.4f} "
                    f"+1s="
                    f"{row['event_recall_by_plus_1s']:.4f} "
                    f"p95="
                    f"{row['p95_latency_sec']:.4f} "
                    f"nonfall="
                    f"{row['nonfall_video_false_alarm_rate']:.4f}"
                )

            # ----------------------------------------
            # Frozen D operating-point transfer
            # ----------------------------------------

            if model == "D_125_sqrt":

                for profile, (
                    threshold,
                    consecutive,
                ) in D_FROZEN.items():

                    metrics = (
                        evaluator.evaluate(
                            pred,
                            threshold,
                            consecutive,
                            "strict",
                        )
                    )

                    core_pass = (
                        check_constraints(
                            metrics,
                            m20.PROFILES[
                                profile
                            ][
                                "core"
                            ],
                        )
                    )

                    frozen_rows.append(
                        {
                            "seed":
                                seed,

                            "profile":
                                profile,

                            "threshold":
                                threshold,

                            "consecutive":
                                consecutive,

                            "core_pass":
                                core_pass,

                            **metrics,
                        }
                    )

    selected = pd.DataFrame(
        selected_rows
    )

    selected.to_csv(
        OUT_ROOT
        / "per_seed_profile_selection.csv",
        index=False,
    )

    frozen = pd.DataFrame(
        frozen_rows
    )

    frozen.to_csv(
        OUT_ROOT
        / "d_frozen_operating_points.csv",
        index=False,
    )

    print()
    print(
        "=" * 120
    )

    print(
        "ROBUST PROFILE PASS SUMMARY"
    )

    print(
        "=" * 120
    )

    pass_rows = []

    for model in MODELS:

        for profile in (
            m20.PROFILES.keys()
        ):

            part = selected[
                (
                    selected["model"]
                    == model
                )
                &
                (
                    selected["profile"]
                    == profile
                )
            ]

            robust_count = int(
                (
                    part[
                        "selection_mode"
                    ]
                    == "ROBUST"
                ).sum()
            )

            core_only_count = int(
                (
                    part[
                        "selection_mode"
                    ]
                    == "CORE_ONLY"
                ).sum()
            )

            none_count = int(
                (
                    part[
                        "selection_mode"
                    ]
                    == "NONE"
                ).sum()
            )

            pass_rows.append(
                {
                    "model":
                        model,

                    "profile":
                        profile,

                    "robust":
                        robust_count,

                    "core_only":
                        core_only_count,

                    "none":
                        none_count,
                }
            )

    pass_summary = pd.DataFrame(
        pass_rows
    )

    print(
        pass_summary.to_string(
            index=False
        )
    )

    pass_summary.to_csv(
        OUT_ROOT
        / "profile_pass_summary.csv",
        index=False,
    )

    print()
    print(
        "=" * 120
    )

    print(
        "D FROZEN OPERATING POINTS"
    )

    print(
        "=" * 120
    )

    cols = [
        "seed",
        "profile",
        "threshold",
        "consecutive",
        "core_pass",
        "event_recall_by_end",
        "event_recall_by_plus_1s",
        "event_recall_by_plus_2s",
        "median_latency_sec",
        "p95_latency_sec",
        "nonfall_video_false_alarm_rate",
        "prefall_false_alarm_video_rate",
        "false_alarms_per_hour",
    ]

    print(
        frozen[
            cols
        ]
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
