from pathlib import Path

import numpy as np
import pandas as pd


OUT_ROOT = Path(
    "runs/event_compare_corrected"
)

PREDICTIONS = {
    "v1": Path(
        "runs/event_compare_v1_v2_val/"
        "v1_val_predictions.csv.gz"
    ),

    "v2": Path(
        "runs/event_compare_v1_v2_val/"
        "v2_val_predictions.csv.gz"
    ),

    "binary": Path(
        "runs/gru_binary_v2/"
        "val_predictions.csv.gz"
    ),
}


THRESHOLDS = sorted(
    set(
        [
            round(x, 2)
            for x in np.arange(
                0.10,
                0.951,
                0.05,
            )
        ]
        +
        [
            0.96,
            0.97,
            0.98,
            0.985,
            0.99,
            0.995,
            0.999,
        ]
    )
)


CONSECUTIVE_OPTIONS = list(
    range(
        1,
        11,
    )
)


RELEASE_FRAMES = 3

EARLY_SEC = 0.5

TARGET_RECALL = 0.95

LOW_FA_CLIP_LIMIT = 0.10


def load_predictions(
    model_name,
    path,
):

    if not path.exists():

        raise RuntimeError(
            f"Missing prediction file: "
            f"{path}"
        )


    df = pd.read_csv(
        path
    )


    required = {
        "scene_id",
        "scenario_id",
        "actor_id",
        "fall_class",
        "camera",
        "timestamp",
        "phase",
    }


    missing = (
        required
        - set(
            df.columns
        )
    )


    if missing:

        raise RuntimeError(
            f"{model_name}: "
            f"missing columns "
            f"{sorted(missing)}"
        )


    if model_name in {
        "v1",
        "v2",
    }:

        if (
            "alert_score"
            not in df.columns
        ):

            if not {
                "prob_falling",
                "prob_fallen",
            }.issubset(
                df.columns
            ):

                raise RuntimeError(
                    f"{model_name}: "
                    "missing alert "
                    "probabilities"
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


    elif (
        model_name
        == "binary"
    ):

        if (
            "prob_alert"
            not in df.columns
        ):

            raise RuntimeError(
                "binary: "
                "prob_alert missing"
            )


        df[
            "alert_score"
        ] = df[
            "prob_alert"
        ]


    df[
        "alert_score"
    ] = np.clip(
        df[
            "alert_score"
        ].astype(
            float
        ),
        0.0,
        1.0,
    )


    return df


def estimate_dt(
    scene,
):

    times = np.sort(
        scene[
            "timestamp"
        ]
        .astype(
            float
        )
        .unique()
    )


    if len(times) < 2:

        return 0.1


    delta = np.diff(
        times
    )


    delta = delta[
        delta > 0
    ]


    if len(delta) == 0:

        return 0.1


    return float(
        np.median(
            delta
        )
    )


def build_alarm_intervals(
    scene,
    threshold,
    consecutive,
):

    scene = (
        scene
        .sort_values(
            "timestamp"
        )
        .reset_index(
            drop=True
        )
    )


    times = (
        scene[
            "timestamp"
        ]
        .to_numpy(
            dtype=float
        )
    )


    scores = (
        scene[
            "alert_score"
        ]
        .to_numpy(
            dtype=float
        )
    )


    if len(times) == 0:

        return []


    dt = estimate_dt(
        scene
    )


    active = False

    high_run = 0

    low_run = 0

    alarm_start = None

    intervals = []


    for t, score in zip(
        times,
        scores,
    ):

        # -----------------------------------------
        # Alarm OFF
        # -----------------------------------------

        if not active:

            if (
                score
                >= threshold
            ):

                high_run += 1

            else:

                high_run = 0


            if (
                high_run
                >= consecutive
            ):

                # 실제 경보가 발생하는 시점은
                # consecutive 조건을 만족한
                # 현재 frame 시점
                alarm_start = float(
                    t
                )

                active = True

                high_run = 0

                low_run = 0


        # -----------------------------------------
        # Alarm ON
        # -----------------------------------------

        else:

            if (
                score
                < threshold
            ):

                low_run += 1

            else:

                low_run = 0


            if (
                low_run
                >= RELEASE_FRAMES
            ):

                intervals.append(
                    (
                        float(
                            alarm_start
                        ),
                        float(
                            t
                        ),
                    )
                )


                active = False

                alarm_start = None

                high_run = 0

                low_run = 0


    # 영상 끝까지 ON
    if active:

        intervals.append(
            (
                float(
                    alarm_start
                ),

                float(
                    times[-1]
                    + dt
                ),
            )
        )


    return intervals


def first_detection_overlap(
    intervals,
    allowed_start,
    deadline,
):

    candidates = []


    for (
        alarm_start,
        alarm_end,
    ) in intervals:

        # -----------------------------------------
        # 핵심 수정
        #
        # alarm interval과 event detection window가
        # 서로 겹치면 검출로 인정한다.
        #
        # alarm이 fall_start 전에 이미 켜져 있어도
        # fall_start까지 지속되면 detection이다.
        # -----------------------------------------

        overlaps = (
            alarm_end
            >= allowed_start
            and alarm_start
            <= deadline
        )


        if not overlaps:

            continue


        detection_time = max(
            alarm_start,
            allowed_start,
        )


        if (
            detection_time
            <= deadline
        ):

            candidates.append(
                detection_time
            )


    if not candidates:

        return np.nan


    return float(
        min(
            candidates
        )
    )


def evaluate(
    pred,
    threshold,
    consecutive,
    policy,
):

    if policy == "strict":

        early_sec = 0.0

    elif policy == "early_0p5s":

        early_sec = (
            EARLY_SEC
        )

    else:

        raise ValueError(
            policy
        )


    fall_videos = 0

    detected_end = 0

    detected_plus_1 = 0

    detected_plus_2 = 0


    latencies = []


    false_alarm_count = 0

    negative_seconds = 0.0


    nonfall_videos = 0

    nonfall_with_fa = 0


    fall_with_prefall_fa = 0


    for (
        scene_id,
        scene,
    ) in pred.groupby(
        "scene_id",
        sort=False,
    ):

        scene = (
            scene
            .sort_values(
                "timestamp"
            )
            .reset_index(
                drop=True
            )
        )


        dt = estimate_dt(
            scene
        )


        intervals = (
            build_alarm_intervals(
                scene,
                threshold,
                consecutive,
            )
        )


        is_fall = (
            int(
                scene[
                    "phase"
                ].max()
            )
            >= 2
        )


        # =========================================
        # NON-FALL
        # =========================================

        if not is_fall:

            nonfall_videos += 1


            first_time = float(
                scene[
                    "timestamp"
                ].min()
            )


            last_time = float(
                scene[
                    "timestamp"
                ].max()
            )


            negative_seconds += (
                last_time
                - first_time
                + dt
            )


            fa = len(
                intervals
            )


            false_alarm_count += (
                fa
            )


            nonfall_with_fa += int(
                fa > 0
            )


            continue


        # =========================================
        # FALL
        # =========================================

        fall_videos += 1


        falling = scene[
            scene[
                "phase"
            ] == 2
        ]


        if falling.empty:

            raise RuntimeError(
                f"{scene_id}: "
                "no phase=2"
            )


        fall_start = float(
            falling[
                "timestamp"
            ].min()
        )


        fall_end = float(
            falling[
                "timestamp"
            ].max()
        )


        allowed_start = (
            fall_start
            - early_sec
        )


        first_eval_time = float(
            scene[
                "timestamp"
            ].min()
        )


        negative_seconds += max(
            0.0,
            allowed_start
            - first_eval_time,
        )


        # -----------------------------------------
        # allowed_start 이전에 시작한 alarm은
        # false alarm으로 계산한다.
        #
        # 단, 그 alarm이 실제 fall까지 계속 유지되면
        # event detection으로도 인정할 수 있다.
        # -----------------------------------------

        prefall_intervals = [

            interval

            for interval
            in intervals

            if (
                interval[0]
                < allowed_start
            )
        ]


        false_alarm_count += len(
            prefall_intervals
        )


        fall_with_prefall_fa += int(
            len(
                prefall_intervals
            )
            > 0
        )


        t_end = (
            first_detection_overlap(
                intervals,
                allowed_start,
                fall_end,
            )
        )


        t_plus_1 = (
            first_detection_overlap(
                intervals,
                allowed_start,
                fall_end + 1.0,
            )
        )


        t_plus_2 = (
            first_detection_overlap(
                intervals,
                allowed_start,
                fall_end + 2.0,
            )
        )


        by_end = (
            not np.isnan(
                t_end
            )
        )


        by_plus_1 = (
            not np.isnan(
                t_plus_1
            )
        )


        by_plus_2 = (
            not np.isnan(
                t_plus_2
            )
        )


        detected_end += int(
            by_end
        )


        detected_plus_1 += int(
            by_plus_1
        )


        detected_plus_2 += int(
            by_plus_2
        )


        if by_plus_1:

            latencies.append(
                t_plus_1
                - fall_start
            )


    if fall_videos == 0:

        raise RuntimeError(
            "No fall videos"
        )


    negative_hours = (
        negative_seconds
        / 3600.0
    )


    return {

        "policy":
            policy,

        "threshold":
            float(
                threshold
            ),

        "consecutive":
            int(
                consecutive
            ),

        "fall_videos":
            int(
                fall_videos
            ),

        "event_recall_by_end":
            detected_end
            / fall_videos,

        "event_recall_by_plus_1s":
            detected_plus_1
            / fall_videos,

        "event_recall_by_plus_2s":
            detected_plus_2
            / fall_videos,

        "median_latency_sec":
            (
                float(
                    np.median(
                        latencies
                    )
                )
                if latencies
                else np.nan
            ),

        "p95_latency_sec":
            (
                float(
                    np.percentile(
                        latencies,
                        95,
                    )
                )
                if latencies
                else np.nan
            ),

        "false_alarm_count":
            int(
                false_alarm_count
            ),

        "negative_exposure_hours":
            float(
                negative_hours
            ),

        "false_alarms_per_hour":
            (
                false_alarm_count
                / negative_hours
                if negative_hours > 0
                else np.nan
            ),

        "nonfall_videos":
            int(
                nonfall_videos
            ),

        "nonfall_video_false_alarm_rate":
            (
                nonfall_with_fa
                / nonfall_videos
                if nonfall_videos
                else np.nan
            ),

        "prefall_false_alarm_video_rate":
            (
                fall_with_prefall_fa
                / fall_videos
            ),
    }


def select_target95(
    grid,
):

    eligible = grid[
        grid[
            "event_recall_by_plus_1s"
        ]
        >= TARGET_RECALL
    ].copy()


    if not eligible.empty:

        best = (
            eligible
            .sort_values(
                [
                    "nonfall_video_false_alarm_rate",
                    "prefall_false_alarm_video_rate",
                    "false_alarms_per_hour",
                    "median_latency_sec",
                    "event_recall_by_end",
                    "threshold",
                ],

                ascending=[
                    True,
                    True,
                    True,
                    True,
                    False,
                    False,
                ],
            )
            .iloc[0]
        )


        return (
            best,
            "target_met",
        )


    best = (
        grid
        .sort_values(
            [
                "event_recall_by_plus_1s",
                "nonfall_video_false_alarm_rate",
                "false_alarms_per_hour",
                "median_latency_sec",
            ],

            ascending=[
                False,
                True,
                True,
                True,
            ],
        )
        .iloc[0]
    )


    return (
        best,
        "target_not_met",
    )


def select_low_fa(
    grid,
):

    eligible = grid[
        grid[
            "nonfall_video_false_alarm_rate"
        ]
        <= LOW_FA_CLIP_LIMIT
    ].copy()


    if eligible.empty:

        minimum = grid[
            "nonfall_video_false_alarm_rate"
        ].min()


        eligible = grid[
            grid[
                "nonfall_video_false_alarm_rate"
            ]
            == minimum
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
                "false_alarms_per_hour",
                "median_latency_sec",
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


def print_row(
    title,
    row,
    mode,
):

    print()
    print(
        title,
        "/",
        mode,
    )

    print(
        "  threshold             :",
        f"{row['threshold']:.3f}",
    )

    print(
        "  consecutive           :",
        int(
            row[
                "consecutive"
            ]
        ),
    )

    print(
        "  recall end            :",
        f"{row['event_recall_by_end']:.4f}",
    )

    print(
        "  recall +1s            :",
        f"{row['event_recall_by_plus_1s']:.4f}",
    )

    print(
        "  recall +2s            :",
        f"{row['event_recall_by_plus_2s']:.4f}",
    )

    print(
        "  median latency        :",
        f"{row['median_latency_sec']:.4f}s",
    )

    print(
        "  p95 latency           :",
        f"{row['p95_latency_sec']:.4f}s",
    )

    print(
        "  false alarms/hour     :",
        f"{row['false_alarms_per_hour']:.4f}",
    )

    print(
        "  nonfall clip FA rate  :",
        f"{row['nonfall_video_false_alarm_rate']:.4f}",
    )

    print(
        "  prefall FA video rate :",
        f"{row['prefall_false_alarm_video_rate']:.4f}",
    )


def main():

    OUT_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )


    print(
        "=" * 100
    )

    print(
        "CORRECTED VALIDATION EVENT COMPARISON"
    )

    print(
        "=" * 100
    )

    print(
        "models              : "
        "v1 / v2 / binary"
    )

    print(
        "target recall +1s  :",
        TARGET_RECALL,
    )

    print(
        "low-FA clip limit  :",
        LOW_FA_CLIP_LIMIT,
    )

    print(
        "release frames     :",
        RELEASE_FRAMES,
    )

    print(
        "test set           : "
        "NOT LOADED"
    )


    all_grid = []

    summary = []


    for (
        model_name,
        path,
    ) in PREDICTIONS.items():

        print()
        print(
            "=" * 100
        )

        print(
            "MODEL:",
            model_name.upper()
        )

        print(
            "=" * 100
        )


        pred = (
            load_predictions(
                model_name,
                path,
            )
        )


        print(
            "rows:",
            len(pred),
        )

        print(
            "scenes:",
            pred[
                "scene_id"
            ].nunique(),
        )


        for policy in [
            "strict",
            "early_0p5s",
        ]:

            rows = []


            for threshold in (
                THRESHOLDS
            ):

                for consecutive in (
                    CONSECUTIVE_OPTIONS
                ):

                    metrics = evaluate(
                        pred,
                        threshold,
                        consecutive,
                        policy,
                    )


                    row = {
                        "model":
                            model_name,

                        **metrics,
                    }


                    rows.append(
                        row
                    )

                    all_grid.append(
                        row
                    )


            grid = pd.DataFrame(
                rows
            )


            (
                target_best,
                target_mode,
            ) = select_target95(
                grid
            )


            (
                lowfa_best,
                lowfa_mode,
            ) = select_low_fa(
                grid
            )


            print()
            print(
                "-" * 100
            )

            print(
                model_name.upper(),
                "/",
                policy,
            )

            print(
                "-" * 100
            )


            print_row(
                "TARGET95",
                target_best,
                target_mode,
            )


            print_row(
                "LOW_FA",
                lowfa_best,
                lowfa_mode,
            )


            for (
                selection_name,
                selected,
                mode,
            ) in [

                (
                    "target95",
                    target_best,
                    target_mode,
                ),

                (
                    "low_fa",
                    lowfa_best,
                    lowfa_mode,
                ),
            ]:

                summary.append(
                    {
                        "model":
                            model_name,

                        "policy":
                            policy,

                        "selection":
                            selection_name,

                        "mode":
                            mode,

                        **{
                            key:
                                selected[
                                    key
                                ]

                            for key
                            in selected.index
                        },
                    }
                )


    grid_df = pd.DataFrame(
        all_grid
    )


    summary_df = pd.DataFrame(
        summary
    )


    grid_df.to_csv(
        OUT_ROOT
        / "grid_all.csv",
        index=False,
    )


    summary_df.to_csv(
        OUT_ROOT
        / "summary.csv",
        index=False,
    )


    print()
    print(
        "=" * 100
    )

    print(
        "FINAL SUMMARY"
    )

    print(
        "=" * 100
    )


    cols = [
        "model",
        "policy",
        "selection",
        "mode",
        "threshold",
        "consecutive",
        "event_recall_by_end",
        "event_recall_by_plus_1s",
        "event_recall_by_plus_2s",
        "median_latency_sec",
        "false_alarms_per_hour",
        "nonfall_video_false_alarm_rate",
        "prefall_false_alarm_video_rate",
    ]


    print(
        summary_df[
            cols
        ]
        .sort_values(
            [
                "policy",
                "selection",
                "model",
            ]
        )
        .to_string(
            index=False
        )
    )


    print()
    print(
        "saved:",
        OUT_ROOT,
    )

    print(
        "TEST SET WAS NOT LOADED."
    )


if __name__ == "__main__":
    main()
