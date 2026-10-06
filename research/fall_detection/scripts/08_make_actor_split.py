from pathlib import Path
import random

import numpy as np
import pandas as pd


MANIFEST = Path(
    "data/aihub71641/manifests/val_manifest.csv"
)

CACHE_ROOT = Path(
    "data/pose_cache/val_yolo11n_pose_960_10fps"
)

OUT = Path(
    "data/splits/actor_split.csv"
)

ACTOR_OUT = Path(
    "data/splits/actor_assignments.csv"
)

SEED = 42
TRIALS = 50000

TARGET = {
    "train": 0.70,
    "val": 0.15,
    "test": 0.15,
}

rng = random.Random(SEED)


df = pd.read_csv(MANIFEST)

# C1~C8 중복을 제거해서 실제 독립 사건 기준으로 균형 계산
scenario_df = (
    df.sort_values(
        ["scenario_id", "camera"]
    )
    .drop_duplicates(
        "scenario_id"
    )
    .reset_index(drop=True)
)

actors = sorted(
    scenario_df[
        "actor_id"
    ].unique()
)

classes = sorted(
    scenario_df[
        "fall_class"
    ].unique()
)

print("Actors:", len(actors))
print(actors)

print()
print("Scenarios:", len(scenario_df))

print()
print("Classes:")
print(
    scenario_df[
        "fall_class"
    ].value_counts()
)


# actor별 scenario/class 통계
actor_stats = (
    scenario_df
    .groupby(
        [
            "actor_id",
            "fall_class",
        ]
    )
    .size()
    .unstack(
        fill_value=0
    )
    .reindex(
        columns=classes,
        fill_value=0,
    )
)

actor_totals = (
    actor_stats.sum(axis=1)
)


global_class_ratio = (
    scenario_df[
        "fall_class"
    ]
    .value_counts(
        normalize=True
    )
    .reindex(
        classes,
        fill_value=0,
    )
)


def evaluate(
    train_actors,
    val_actors,
    test_actors,
):
    groups = {
        "train": train_actors,
        "val": val_actors,
        "test": test_actors,
    }

    score = 0.0

    total_scenarios = len(
        scenario_df
    )

    for split, split_actors in groups.items():

        part = scenario_df[
            scenario_df[
                "actor_id"
            ].isin(
                split_actors
            )
        ]

        n = len(part)

        ratio = (
            n / total_scenarios
        )

        # 전체 크기 비율 오차
        score += (
            abs(
                ratio
                - TARGET[split]
            )
            * 4.0
        )

        counts = (
            part[
                "fall_class"
            ]
            .value_counts()
            .reindex(
                classes,
                fill_value=0,
            )
        )

        # 특정 split에 클래스가 하나라도 없으면 큰 패널티
        if (
            counts == 0
        ).any():
            score += 100.0

        if n > 0:

            ratios = (
                counts / n
            )

            # 전체 class 분포와 차이
            score += float(
                np.abs(
                    ratios
                    - global_class_ratio
                ).sum()
            )

    return score


best = None
best_score = float("inf")

actor_count = len(
    actors
)

# actor 수 자체는 17/3/4로 시작하지만
# 실제 scenario 비율을 평가해서 최적 조합을 찾음
train_n = 17
val_n = 3


for _ in range(TRIALS):

    shuffled = actors.copy()

    rng.shuffle(
        shuffled
    )

    train = set(
        shuffled[
            :train_n
        ]
    )

    val = set(
        shuffled[
            train_n:
            train_n + val_n
        ]
    )

    test = set(
        shuffled[
            train_n + val_n:
        ]
    )

    score = evaluate(
        train,
        val,
        test,
    )

    if score < best_score:

        best_score = score

        best = {
            "train": train,
            "val": val,
            "test": test,
        }


if best is None:
    raise RuntimeError(
        "No valid split found"
    )


actor_split = {}

for split, split_actors in best.items():

    for actor in split_actors:

        actor_split[
            actor
        ] = split


df[
    "split"
] = df[
    "actor_id"
].map(
    actor_split
)

scenario_df[
    "split"
] = scenario_df[
    "actor_id"
].map(
    actor_split
)


if df[
    "split"
].isna().any():

    raise RuntimeError(
        "Some videos have no split"
    )


# 모든 cache 존재 확인
def cache_path(row):

    return (
        CACHE_ROOT
        / row[
            "scenario_id"
        ]
        / (
            row[
                "scene_id"
            ]
            + ".npz"
        )
    )


df[
    "cache_path"
] = df.apply(
    cache_path,
    axis=1,
)

missing = [
    p
    for p
    in df[
        "cache_path"
    ]
    if not Path(p).exists()
]

if missing:

    raise RuntimeError(
        f"Missing caches: "
        f"{len(missing)}"
    )


OUT.parent.mkdir(
    parents=True,
    exist_ok=True,
)

df.to_csv(
    OUT,
    index=False,
)


actor_rows = []

for actor in actors:

    actor_rows.append(
        {
            "actor_id":
                actor,

            "split":
                actor_split[
                    actor
                ],

            "scenarios":
                int(
                    actor_totals[
                        actor
                    ]
                ),

            **{
                cls:
                    int(
                        actor_stats.loc[
                            actor,
                            cls,
                        ]
                    )
                for cls
                in classes
            },
        }
    )


actor_df = pd.DataFrame(
    actor_rows
).sort_values(
    [
        "split",
        "actor_id",
    ]
)

actor_df.to_csv(
    ACTOR_OUT,
    index=False,
)


print()
print("=" * 90)
print("BEST SPLIT")
print("=" * 90)

print(
    "score:",
    best_score,
)

for split in [
    "train",
    "val",
    "test",
]:

    split_actors = sorted(
        best[
            split
        ]
    )

    part = scenario_df[
        scenario_df[
            "split"
        ] == split
    ]

    print()
    print(
        split.upper()
    )

    print(
        "actors:",
        len(
            split_actors
        ),
        split_actors,
    )

    print(
        "scenarios:",
        len(part),
        f"({len(part) / len(scenario_df):.1%})",
    )

    print(
        "videos:",
        len(
            df[
                df[
                    "split"
                ] == split
            ]
        ),
    )

    print(
        part[
            "fall_class"
        ].value_counts()
        .reindex(
            classes,
            fill_value=0,
        )
    )


# 누수 검증
train_actors = set(
    df[
        df["split"] == "train"
    ][
        "actor_id"
    ]
)

val_actors = set(
    df[
        df["split"] == "val"
    ][
        "actor_id"
    ]
)

test_actors = set(
    df[
        df["split"] == "test"
    ][
        "actor_id"
    ]
)

assert (
    train_actors
    .isdisjoint(
        val_actors
    )
)

assert (
    train_actors
    .isdisjoint(
        test_actors
    )
)

assert (
    val_actors
    .isdisjoint(
        test_actors
    )
)


scenario_split_count = (
    df.groupby(
        "scenario_id"
    )[
        "split"
    ]
    .nunique()
)

assert (
    scenario_split_count.max()
    == 1
)


print()
print("=" * 90)
print("LEAKAGE CHECK")
print("=" * 90)

print(
    "Actor leakage   : NONE"
)

print(
    "Scenario leakage:",
    "NONE"
)

print()
print(
    "Saved:",
    OUT
)

print(
    "Saved:",
    ACTOR_OUT
)
