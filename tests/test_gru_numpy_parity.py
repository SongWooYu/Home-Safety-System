from __future__ import annotations

from pathlib import Path

import numpy as np

try:
    import torch
    from torch import nn
except ModuleNotFoundError:
    torch = None
    nn = None

from smarthome_vision.gru_numpy import (
    NumpyFallGRU,
)


ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)

MODEL_ROOT = (
    ROOT
    / "models"
    / "fall_gru"
    / "b76_sqrt_ensemble"
)

SEEDS = (
    42,
    123,
    2026,
)


class TorchFallGRU(nn.Module if nn is not None else object):
    def __init__(self):
        if nn is None:
            raise RuntimeError("PyTorch is required for parity validation")
        super().__init__()

        self.input_norm = nn.LayerNorm(
            76
        )

        self.gru = nn.GRU(
            input_size=76,
            hidden_size=128,
            num_layers=2,
            batch_first=True,
            dropout=0.2,
            bidirectional=False,
        )

        self.head = nn.Sequential(
            nn.LayerNorm(
                128
            ),
            nn.Dropout(
                0.2
            ),
            nn.Linear(
                128,
                64,
            ),
            nn.ReLU(),
            nn.Dropout(
                0.2
            ),
            nn.Linear(
                64,
                3,
            ),
        )

    def forward(
        self,
        x,
    ):
        x = self.input_norm(
            x
        )

        _, h = self.gru(
            x
        )

        return self.head(
            h[-1]
        )


def main():

    if torch is None:
        print("NUMPY GRU PARITY: SKIP (PyTorch is not installed)")
        return

    rng = np.random.default_rng(
        20261008
    )

    sequences = [
        rng.normal(
            0.0,
            0.5,
            size=(
                20,
                76,
            ),
        ).astype(
            np.float32
        )
        for _ in range(8)
    ]

    overall_max_logits = 0.0
    overall_max_probs = 0.0

    for seed in SEEDS:

        checkpoint = torch.load(
            MODEL_ROOT
            / f"seed_{seed}"
            / "best.pt",
            map_location="cpu",
            weights_only=False,
        )

        torch_model = (
            TorchFallGRU()
        )

        torch_model.load_state_dict(
            checkpoint[
                "model_state"
            ]
        )

        torch_model.eval()

        numpy_model = (
            NumpyFallGRU(
                MODEL_ROOT
                / "numpy"
                / f"seed_{seed}.npz"
            )
        )

        seed_logit_error = 0.0
        seed_prob_error = 0.0

        for sequence in sequences:

            with torch.no_grad():

                torch_logits = (
                    torch_model(
                        torch.from_numpy(
                            sequence
                        ).unsqueeze(0)
                    )
                    .squeeze(0)
                    .cpu()
                    .numpy()
                )

                torch_probs = (
                    torch.softmax(
                        torch.from_numpy(
                            torch_logits
                        ),
                        dim=0,
                    )
                    .numpy()
                )

            numpy_logits = (
                numpy_model.logits(
                    sequence
                )
            )

            numpy_probs = (
                numpy_model.probabilities(
                    sequence
                )
            )

            logit_error = float(
                np.max(
                    np.abs(
                        torch_logits
                        - numpy_logits
                    )
                )
            )

            prob_error = float(
                np.max(
                    np.abs(
                        torch_probs
                        - numpy_probs
                    )
                )
            )

            seed_logit_error = max(
                seed_logit_error,
                logit_error,
            )

            seed_prob_error = max(
                seed_prob_error,
                prob_error,
            )

        overall_max_logits = max(
            overall_max_logits,
            seed_logit_error,
        )

        overall_max_probs = max(
            overall_max_probs,
            seed_prob_error,
        )

        print(
            f"seed {seed}: "
            f"max_logit_error="
            f"{seed_logit_error:.9g} "
            f"max_prob_error="
            f"{seed_prob_error:.9g}"
        )

    print()
    print(
        "overall max logit error:",
        f"{overall_max_logits:.9g}",
    )

    print(
        "overall max prob error :",
        f"{overall_max_probs:.9g}",
    )

    if (
        overall_max_logits
        > 1e-4
        or overall_max_probs
        > 1e-4
    ):
        raise RuntimeError(
            "NumPy GRU parity failed"
        )

    print()
    print(
        "NUMPY GRU PARITY: PASS"
    )


if __name__ == "__main__":
    main()
