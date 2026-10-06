from pathlib import Path
import importlib.util

import pandas as pd


BASE_SCRIPT = Path(
    "scripts/18_train_gru_ablation_bc.py"
)

OUT_ROOT = Path(
    "runs/gru_multiseed"
)

SEEDS = [
    42,
    123,
    2026,
]


CONFIGS = [

    {
        "name": "A_76_inverse",
        "data_root": Path(
            "data/gru_dataset/"
            "v1_actor_disjoint_20f"
        ),
        "weight_mode": "inverse",
    },

    {
        "name": "B_76_sqrt",
        "data_root": Path(
            "data/gru_dataset/"
            "v1_actor_disjoint_20f"
        ),
        "weight_mode": "sqrt",
    },

    {
        "name": "C_125_inverse",
        "data_root": Path(
            "data/gru_dataset/"
            "v2_actor_disjoint_20f_dynamic"
        ),
        "weight_mode": "inverse",
    },

    {
        "name": "D_125_sqrt",
        "data_root": Path(
            "data/gru_dataset/"
            "v2_actor_disjoint_20f_dynamic"
        ),
        "weight_mode": "sqrt",
    },
]


def load_trainer():

    spec = (
        importlib.util
        .spec_from_file_location(
            "ablation18",
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


def main():

    OUT_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )

    trainer = load_trainer()

    device = trainer.get_device()

    print(
        "=" * 110
    )

    print(
        "GRU 4-WAY MULTI-SEED REPRODUCIBILITY"
    )

    print(
        "=" * 110
    )

    print(
        "seeds :",
        SEEDS
    )

    print(
        "device:",
        device
    )

    print(
        "TEST SET: NOT LOADED"
    )

    rows = []

    for seed in SEEDS:

        trainer.SEED = seed

        for config in CONFIGS:

            name = config[
                "name"
            ]

            run_root = (
                OUT_ROOT
                / name
                / f"seed_{seed}"
            )

            cfg = {

                "name":
                    f"{name}_seed_{seed}",

                "data_root":
                    config[
                        "data_root"
                    ],

                "run_root":
                    run_root,

                "weight_mode":
                    config[
                        "weight_mode"
                    ],
            }

            print()
            print(
                "#" * 110
            )

            print(
                f"{name} / seed={seed}"
            )

            print(
                "#" * 110
            )

            result = (
                trainer.train_one(
                    cfg,
                    device,
                )
            )

            row = {
                "model":
                    name,

                "seed":
                    seed,

                **result,
            }

            rows.append(
                row
            )

            pd.DataFrame(
                rows
            ).to_csv(
                OUT_ROOT
                / "all_runs.csv",
                index=False,
            )

    results = pd.DataFrame(
        rows
    )

    metric_columns = [
        "val_accuracy",
        "val_balanced_accuracy",
        "val_macro_f1",
        "normal_f1",
        "falling_precision",
        "falling_recall",
        "falling_f1",
        "fallen_f1",
    ]

    summary_rows = []

    for model, group in (
        results.groupby(
            "model",
            sort=False,
        )
    ):

        row = {
            "model": model,
            "n_seeds": len(group),
        }

        for metric in metric_columns:

            row[
                f"{metric}_mean"
            ] = group[
                metric
            ].mean()

            row[
                f"{metric}_std"
            ] = group[
                metric
            ].std(
                ddof=1
            )

            row[
                f"{metric}_min"
            ] = group[
                metric
            ].min()

            row[
                f"{metric}_max"
            ] = group[
                metric
            ].max()

        summary_rows.append(
            row
        )

    summary = pd.DataFrame(
        summary_rows
    )

    summary = summary.sort_values(
        "val_macro_f1_mean",
        ascending=False,
    )

    summary.to_csv(
        OUT_ROOT
        / "summary_mean_std.csv",
        index=False,
    )

    print()
    print(
        "=" * 110
    )

    print(
        "MULTI-SEED SUMMARY"
    )

    print(
        "=" * 110
    )

    display = [

        "model",

        "val_accuracy_mean",
        "val_accuracy_std",

        "val_balanced_accuracy_mean",
        "val_balanced_accuracy_std",

        "val_macro_f1_mean",
        "val_macro_f1_std",

        "falling_precision_mean",
        "falling_precision_std",

        "falling_recall_mean",
        "falling_recall_std",

        "falling_f1_mean",
        "falling_f1_std",
    ]

    print(
        summary[
            display
        ]
        .to_string(
            index=False,
            float_format=lambda x:
                f"{x:.6f}",
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
