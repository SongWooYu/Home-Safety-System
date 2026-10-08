from pathlib import Path
import hashlib
import json

import numpy as np
import torch


PROJECTS = Path.home() / "Projects"

REPO = (
    PROJECTS
    / "Home-Safety-System"
)

SOURCE = (
    REPO
    / "models"
    / "fall_gru"
    / "b76_sqrt_ensemble"
)

DEST = (
    REPO
    / "models"
    / "fall_gru"
    / "b76_sqrt_ensemble"
    / "numpy"
)

SEEDS = (
    42,
    123,
    2026,
)


def sha256(path: Path):

    h = hashlib.sha256()

    with path.open("rb") as f:

        while True:

            block = f.read(
                1024 * 1024
            )

            if not block:
                break

            h.update(
                block
            )

    return h.hexdigest()


def main():

    DEST.mkdir(
        parents=True,
        exist_ok=True,
    )

    manifest = {
        "format":
            "numpy_state_dict_v1",

        "architecture":
            "B_76_sqrt_3seed_ensemble",

        "sequence_length":
            20,

        "sample_fps":
            10,

        "feature_dim":
            76,

        "hidden_size":
            128,

        "num_layers":
            2,

        "classes": [
            "normal",
            "falling",
            "fallen",
        ],

        "members": {},
    }

    for seed in SEEDS:

        source = (
            SOURCE
            / f"seed_{seed}"
            / "best.pt"
        )

        checkpoint = torch.load(
            source,
            map_location="cpu",
            weights_only=False,
        )

        state = checkpoint[
            "model_state"
        ]

        arrays = {}

        for key, tensor in (
            state.items()
        ):

            np_key = (
                key.replace(
                    ".",
                    "__"
                )
            )

            arrays[np_key] = (
                tensor
                .detach()
                .cpu()
                .numpy()
                .astype(
                    np.float32
                )
            )

        dest = (
            DEST
            / f"seed_{seed}.npz"
        )

        np.savez(
            dest,
            **arrays,
        )

        # Exact tensor round-trip check.
        loaded = np.load(
            dest,
            allow_pickle=False,
        )

        max_error = 0.0

        for key, tensor in (
            state.items()
        ):

            np_key = (
                key.replace(
                    ".",
                    "__"
                )
            )

            original = (
                tensor
                .detach()
                .cpu()
                .numpy()
                .astype(
                    np.float32
                )
            )

            error = float(
                np.max(
                    np.abs(
                        original
                        - loaded[np_key]
                    )
                )
            )

            max_error = max(
                max_error,
                error,
            )

        print(
            f"seed {seed}: "
            f"{dest.name} "
            f"max_weight_error="
            f"{max_error:.9g}"
        )

        if max_error != 0.0:
            raise RuntimeError(
                "Weight round-trip "
                "was not exact"
            )

        manifest[
            "members"
        ][str(seed)] = {
            "file":
                dest.name,

            "sha256":
                sha256(dest),

            "epoch":
                checkpoint.get(
                    "epoch"
                ),

            "val_macro_f1":
                checkpoint.get(
                    "val_macro_f1"
                ),

            "keys": {
                key.replace(
                    ".",
                    "__"
                ):
                list(
                    value.shape
                )
                for key, value
                in state.items()
            },
        }

    manifest_path = (
        DEST
        / "manifest.json"
    )

    manifest_path.write_text(
        json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print(
        "saved:",
        DEST
    )


if __name__ == "__main__":
    main()
