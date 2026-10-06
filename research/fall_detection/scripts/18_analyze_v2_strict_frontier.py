from pathlib import Path

import numpy as np
import pandas as pd


GRID_PATH = Path(
    "runs/gru_v2_operating_point/grid_all.csv"
)

OUT_ROOT = Path(
    "runs/gru_v2_operating_point/strict_review"
)

OUT_ROOT.mkdir(
    parents=True,
    exist_ok=True,
)


COLS = [
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


def pareto_4d(df):
    """
    4-objective Pareto frontier.

    maximize:
      - recall +1s
      - recall by end

    minimize:
      - nonfall clip false alarm
      - p95 latency
    """

    cost = np.column_stack(
        [
            -df[
                "event_recall_by_plus_1s"
            ].to_numpy(float),

            -df[
                "event_recall_by_end"
            ].to_numpy(float),

            df[
                "nonfall_video_false_alarm_rate"
            ].to_numpy(float),

            df[
                "p95_latency_sec"
            ].to_numpy(float),
        ]
    )

    n = len(df)

    keep = np.ones(
        n,
        dtype=bool,
    )

    eps = 1e-12

    for i in range(n):

        better_or_equal = np.all(
            cost
            <= cost[i] + eps,
            axis=1,
        )

        strictly_better = np.any(
            cost
            < cost[i] - eps,
            axis=1,
        )

        dominated = np.any(
            better_or_equal
            & strictly_better
        )

        keep[i] = not dominated

    return (
        df.loc[keep]
        .copy()
        .sort_values(
            [
                "nonfall_video_false_alarm_rate",
                "event_recall_by_plus_1s",
                "event_recall_by_end",
                "p95_latency_sec",
            ],
            ascending=[
                True,
                False,
                False,
                True,
            ],
        )
        .reset_index(drop=True)
    )


def add_local_stability(df):
    """
    각 operating point 주변:

      threshold +/- 0.02
      consecutive +/- 1

    영역에서 worst-case 성능을 확인한다.

    단일 grid 최고점보다
    parameter 변화에도 안정적인 plateau를 찾기 위함.
    """

    result = df.copy()

    local_min_recall_1s = []
    local_min_recall_end = []

    local_max_nonfall_fa = []
    local_max_p95 = []

    local_count = []

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

        local_count.append(
            len(neighborhood)
        )

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
        "local_count"
    ] = local_count

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


def show(
    title,
    df,
    n=12,
):

    print()
    print("=" * 110)
    print(title)
    print("=" * 110)

    if df.empty:

        print("NO CANDIDATES")
        return

    display_cols = [
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
        df[
            display_cols
        ]
        .head(n)
        .to_string(
            index=False,
            float_format=lambda x: f"{x:.4f}",
        )
    )


def main():

    if not GRID_PATH.exists():

        raise RuntimeError(
            f"Missing: {GRID_PATH}"
        )

    grid = pd.read_csv(
        GRID_PATH
    )

    strict = (
        grid[
            grid["policy"]
            == "strict"
        ]
        .copy()
        .reset_index(drop=True)
    )

    print("=" * 110)
    print("GRU V2 STRICT OPERATING-POINT REVIEW")
    print("=" * 110)

    print(
        "strict rows       :",
        len(strict),
    )

    print(
        "threshold range   :",
        strict["threshold"].min(),
        "~",
        strict["threshold"].max(),
    )

    print(
        "consecutive range :",
        int(
            strict["consecutive"].min()
        ),
        "~",
        int(
            strict["consecutive"].max()
        ),
    )

    # -------------------------------------------------
    # Local robustness
    # -------------------------------------------------

    stable = add_local_stability(
        strict
    )

    stable.to_csv(
        OUT_ROOT
        / "strict_grid_with_stability.csv",
        index=False,
    )

    # -------------------------------------------------
    # 4-D Pareto
    # -------------------------------------------------

    pareto = pareto_4d(
        stable
    )

    pareto.to_csv(
        OUT_ROOT
        / "strict_pareto_4d.csv",
        index=False,
    )

    print(
        "Pareto rows       :",
        len(pareto),
    )

    # -------------------------------------------------
    # SAFETY
    #
    # +1s recall은 95% 이상 유지하되,
    # 기존 v2 TARGET95 수준인
    # p95 <= 1.30 sec guard를 둔다.
    #
    # 그 안에서는 early detection을 우선한다.
    # -------------------------------------------------

    safety = stable[
        (
            stable[
                "event_recall_by_plus_1s"
            ]
            >= 0.95
        )
        &
        (
            stable[
                "p95_latency_sec"
            ]
            <= 1.30
        )
    ].copy()

    safety = safety.sort_values(
        [
            "local_min_recall_by_end",
            "event_recall_by_end",

            "local_min_recall_plus_1s",

            "local_max_nonfall_fa",
            "nonfall_video_false_alarm_rate",

            "local_max_p95_latency",
            "p95_latency_sec",

            "consecutive",
            "threshold",
        ],
        ascending=[
            False,
            False,

            False,

            True,
            True,

            True,
            True,

            True,
            False,
        ],
    )

    safety.to_csv(
        OUT_ROOT
        / "safety_candidates.csv",
        index=False,
    )

    # -------------------------------------------------
    # BALANCED
    #
    # recall +1s >= 93%
    # p95 <= 1.30 s
    #
    # safety보다 false alarm 쪽을 더 본다.
    # -------------------------------------------------

    balanced = stable[
        (
            stable[
                "event_recall_by_plus_1s"
            ]
            >= 0.93
        )
        &
        (
            stable[
                "p95_latency_sec"
            ]
            <= 1.30
        )
    ].copy()

    balanced = balanced.sort_values(
        [
            "local_max_nonfall_fa",
            "nonfall_video_false_alarm_rate",

            "local_min_recall_plus_1s",
            "event_recall_by_plus_1s",

            "local_min_recall_by_end",
            "event_recall_by_end",

            "local_max_p95_latency",
            "p95_latency_sec",
        ],
        ascending=[
            True,
            True,

            False,
            False,

            False,
            False,

            True,
            True,
        ],
    )

    balanced.to_csv(
        OUT_ROOT
        / "balanced_candidates.csv",
        index=False,
    )

    # -------------------------------------------------
    # QUIET
    #
    # nonfall clip FA <= 10%
    # p95 <= 1.35 sec
    #
    # 그 안에서 recall을 최대화.
    # -------------------------------------------------

    quiet = stable[
        (
            stable[
                "nonfall_video_false_alarm_rate"
            ]
            <= 0.10
        )
        &
        (
            stable[
                "p95_latency_sec"
            ]
            <= 1.35
        )
    ].copy()

    quiet = quiet.sort_values(
        [
            "local_min_recall_plus_1s",
            "event_recall_by_plus_1s",

            "local_min_recall_by_end",
            "event_recall_by_end",

            "local_max_nonfall_fa",
            "nonfall_video_false_alarm_rate",

            "local_max_p95_latency",
            "p95_latency_sec",
        ],
        ascending=[
            False,
            False,

            False,
            False,

            True,
            True,

            True,
            True,
        ],
    )

    quiet.to_csv(
        OUT_ROOT
        / "quiet_candidates.csv",
        index=False,
    )

    # -------------------------------------------------
    # Current script-17 selected strict points
    # -------------------------------------------------

    selected_path = (
        Path(
            "runs/gru_v2_operating_point/"
            "selected_profiles.csv"
        )
    )

    if selected_path.exists():

        selected = pd.read_csv(
            selected_path
        )

        selected_strict = selected[
            selected["policy"]
            == "strict"
        ].copy()

        print()
        print("=" * 110)
        print("SCRIPT 17 CURRENT STRICT SELECTION")
        print("=" * 110)

        print(
            selected_strict[
                [
                    "profile",
                    "threshold",
                    "consecutive",
                    "event_recall_by_end",
                    "event_recall_by_plus_1s",
                    "median_latency_sec",
                    "p95_latency_sec",
                    "nonfall_video_false_alarm_rate",
                    "false_alarms_per_hour",
                ]
            ]
            .to_string(
                index=False,
                float_format=lambda x: f"{x:.4f}",
            )
        )

    show(
        "SAFETY CANDIDATES "
        "(+1s >=95%, p95 <=1.30s)",
        safety,
    )

    show(
        "BALANCED CANDIDATES "
        "(+1s >=93%, p95 <=1.30s)",
        balanced,
    )

    show(
        "QUIET CANDIDATES "
        "(nonfall FA <=10%, p95 <=1.35s)",
        quiet,
    )

    show(
        "4-D PARETO FRONTIER",
        pareto,
        n=20,
    )

    print()
    print("=" * 110)
    print("SAVED")
    print("=" * 110)

    for name in [
        "strict_grid_with_stability.csv",
        "strict_pareto_4d.csv",
        "safety_candidates.csv",
        "balanced_candidates.csv",
        "quiet_candidates.csv",
    ]:

        print(
            OUT_ROOT / name
        )


if __name__ == "__main__":
    main()
