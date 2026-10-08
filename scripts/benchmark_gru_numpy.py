from __future__ import annotations

import statistics
import time
from pathlib import Path

import numpy as np

from smarthome_vision.gru_numpy import (
    NumpyFallEnsemble,
)


ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)

MODEL = (
    ROOT
    / "models"
    / "fall_gru"
    / "b76_sqrt_ensemble"
    / "numpy"
)

RUNS = 200
WARMUP = 20


def main():

    print(
        "MODEL:",
        MODEL
    )

    ensemble = (
        NumpyFallEnsemble(
            MODEL
        )
    )

    rng = np.random.default_rng(
        20261008
    )

    sequence = rng.normal(
        0.0,
        0.5,
        size=(
            20,
            76,
        ),
    ).astype(
        np.float32
    )

    for _ in range(
        WARMUP
    ):
        ensemble.predict(
            sequence
        )

    times = []

    result = None

    for _ in range(
        RUNS
    ):

        start = (
            time.perf_counter()
        )

        result = (
            ensemble.predict(
                sequence
            )
        )

        times.append(
            (
                time.perf_counter()
                - start
            )
            * 1000.0
        )

    mean_ms = (
        statistics.mean(
            times
        )
    )

    median_ms = (
        statistics.median(
            times
        )
    )

    p95_ms = float(
        np.percentile(
            times,
            95,
        )
    )

    print()
    print(
        f"runs   : {RUNS}"
    )

    print(
        f"mean   : {mean_ms:.3f} ms"
    )

    print(
        f"median : {median_ms:.3f} ms"
    )

    print(
        f"p95    : {p95_ms:.3f} ms"
    )

    print(
        f"FPS eq : "
        f"{1000.0 / mean_ms:.1f}"
    )

    print()
    print(
        "result:"
    )

    print(
        result
    )


if __name__ == "__main__":
    main()
