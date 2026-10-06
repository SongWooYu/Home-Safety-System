from pathlib import Path
import json
import time

import numpy as np
import pandas as pd


SPLIT_CSV = Path("data/splits/actor_split.csv")

OUT_ROOT = Path(
    "data/gru_dataset/v1_actor_disjoint_20f"
)

SEQ_LEN = 20
WINDOW_STRIDE = 1
KP_CONF_THRESHOLD = 0.25
EPS = 1e-6

LABEL_NAMES = {
    0: "normal",
    1: "falling",
    2: "fallen",
}

# 07_extract_pose_cache.py에서 저장한 phase
#
# 0 = 비낙상 영상
# 1 = 낙상 영상의 fall_start 이전
# 2 = fall_start ~ fall_end
# 3 = fall_end 이후
#
# GRU target:
# 0 = Normal
# 1 = Falling
# 2 = Fallen
PHASE_TO_LABEL = {
    0: 0,
    1: 0,
    2: 1,
    3: 2,
}


def feature_names():
    names = []

    # COCO 17 keypoints
    # joint별:
    # x_rel, y_rel, confidence, mask
    #
    # 17 * 4 = 68
    for j in range(17):
        names += [
            f"j{j:02d}_x_rel",
            f"j{j:02d}_y_rel",
            f"j{j:02d}_conf",
            f"j{j:02d}_mask",
        ]

    # Global 8 features
    names += [
        "bbox_cx",
        "bbox_cy",
        "bbox_w",
        "bbox_h",
        "bbox_log_h_over_w",
        "bbox_conf",
        "frame_valid",
        "keypoint_visible_ratio",
    ]

    return names


FEATURE_NAMES = feature_names()
FEATURE_DIM = len(FEATURE_NAMES)


def load_cache(path):
    with np.load(
        path,
        allow_pickle=False,
    ) as d:

        return {
            k: d[k].copy()
            for k in d.files
        }


def build_frame_features(cache):

    xy = np.asarray(
        cache["keypoints_xy"],
        dtype=np.float32,
    )

    conf = np.asarray(
        cache["keypoints_conf"],
        dtype=np.float32,
    )

    boxes = np.asarray(
        cache["boxes_xyxy"],
        dtype=np.float32,
    )

    box_conf = np.asarray(
        cache["box_conf"],
        dtype=np.float32,
    )

    valid = np.asarray(
        cache["valid"],
        dtype=np.uint8,
    ).astype(bool)

    n = len(valid)

    if xy.shape != (
        n,
        17,
        2,
    ):
        raise ValueError(
            f"Unexpected keypoints shape: "
            f"{xy.shape}"
        )

    if conf.shape != (
        n,
        17,
    ):
        raise ValueError(
            f"Unexpected keypoint confidence "
            f"shape: {conf.shape}"
        )

    if boxes.shape != (
        n,
        4,
    ):
        raise ValueError(
            f"Unexpected box shape: "
            f"{boxes.shape}"
        )


    # -------------------------------------------------
    # Bounding box
    # -------------------------------------------------

    finite_box = np.isfinite(
        boxes
    ).all(
        axis=1
    )

    clean_boxes = np.nan_to_num(
        boxes,
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )

    x1, y1, x2, y2 = (
        clean_boxes.T
    )

    bw = (
        x2 - x1
    )

    bh = (
        y2 - y1
    )

    bbox_valid = (
        valid
        & finite_box
        & (
            bw > EPS
        )
        & (
            bh > EPS
        )
    )


    cx = np.zeros(
        n,
        dtype=np.float32,
    )

    cy = np.zeros(
        n,
        dtype=np.float32,
    )

    width = np.zeros(
        n,
        dtype=np.float32,
    )

    height = np.zeros(
        n,
        dtype=np.float32,
    )


    cx[
        bbox_valid
    ] = (
        x1[
            bbox_valid
        ]
        + x2[
            bbox_valid
        ]
    ) * 0.5


    cy[
        bbox_valid
    ] = (
        y1[
            bbox_valid
        ]
        + y2[
            bbox_valid
        ]
    ) * 0.5


    width[
        bbox_valid
    ] = bw[
        bbox_valid
    ]

    height[
        bbox_valid
    ] = bh[
        bbox_valid
    ]


    # -------------------------------------------------
    # Keypoint confidence
    # -------------------------------------------------

    conf = np.nan_to_num(
        conf,
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )

    conf = np.clip(
        conf,
        0.0,
        1.0,
    ).astype(
        np.float32
    )


    finite_xy = np.isfinite(
        xy
    ).all(
        axis=2
    )


    kp_mask = (
        finite_xy
        & (
            conf
            >= KP_CONF_THRESHOLD
        )
        & bbox_valid[
            :,
            None,
        ]
    )


    # -------------------------------------------------
    # Keypoint 좌표를 bbox 중심/크기로 정규화
    #
    # full-frame 위치 차이를 줄이고
    # 자세 자체에 집중하도록 한다.
    # -------------------------------------------------

    safe_w = np.where(
        bbox_valid,
        width,
        1.0,
    )

    safe_h = np.where(
        bbox_valid,
        height,
        1.0,
    )


    rel_x = (
        xy[
            :,
            :,
            0,
        ]
        - cx[
            :,
            None,
        ]
    ) / safe_w[
        :,
        None,
    ]


    rel_y = (
        xy[
            :,
            :,
            1,
        ]
        - cy[
            :,
            None,
        ]
    ) / safe_h[
        :,
        None,
    ]


    rel_x = np.nan_to_num(
        rel_x,
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )

    rel_y = np.nan_to_num(
        rel_y,
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )


    rel_x = np.clip(
        rel_x,
        -2.0,
        2.0,
    )

    rel_y = np.clip(
        rel_y,
        -2.0,
        2.0,
    )


    # 신뢰도가 낮은 관절은 좌표를 사용하지 않는다.
    # 대신 confidence와 mask 자체를 GRU에 전달한다.

    rel_x[
        ~kp_mask
    ] = 0.0

    rel_y[
        ~kp_mask
    ] = 0.0


    # shape:
    # N x 17 x 4
    joints = np.stack(
        [
            rel_x,
            rel_y,
            conf,
            kp_mask.astype(
                np.float32
            ),
        ],
        axis=2,
    )

    # shape:
    # N x 68
    joints = joints.reshape(
        n,
        68,
    )


    # -------------------------------------------------
    # Global bbox features
    # -------------------------------------------------

    log_aspect = np.zeros(
        n,
        dtype=np.float32,
    )

    log_aspect[
        bbox_valid
    ] = np.log(
        (
            height[
                bbox_valid
            ]
            + EPS
        )
        /
        (
            width[
                bbox_valid
            ]
            + EPS
        )
    )

    log_aspect = np.clip(
        log_aspect,
        -3.0,
        3.0,
    ).astype(
        np.float32
    )


    box_conf = np.nan_to_num(
        box_conf,
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )

    box_conf = np.clip(
        box_conf,
        0.0,
        1.0,
    ).astype(
        np.float32
    )


    visible_ratio = (
        kp_mask.mean(
            axis=1
        )
        .astype(
            np.float32
        )
    )


    global_features = np.column_stack(
        [
            cx,
            cy,
            width,
            height,
            log_aspect,
            box_conf,
            bbox_valid.astype(
                np.float32
            ),
            visible_ratio,
        ]
    ).astype(
        np.float32
    )


    # 68 + 8 = 76
    features = np.concatenate(
        [
            joints,
            global_features,
        ],
        axis=1,
    ).astype(
        np.float32
    )


    if features.shape != (
        n,
        FEATURE_DIM,
    ):
        raise RuntimeError(
            f"Feature shape mismatch: "
            f"{features.shape}, "
            f"expected "
            f"{(n, FEATURE_DIM)}"
        )


    if not np.isfinite(
        features
    ).all():
        raise RuntimeError(
            "Non-finite feature detected"
        )


    return features


def make_windows(
    features,
    phase,
):

    n = len(
        features
    )

    if n < SEQ_LEN:

        return (
            np.empty(
                (
                    0,
                    SEQ_LEN,
                    FEATURE_DIM,
                ),
                dtype=np.float32,
            ),

            np.empty(
                (0,),
                dtype=np.int64,
            ),

            np.empty(
                (0,),
                dtype=np.int32,
            ),
        )


    # causal window
    #
    # 예:
    # end=19
    # frames 0..19
    #
    # 미래 프레임은 절대 사용하지 않음

    ends = np.arange(
        SEQ_LEN - 1,
        n,
        WINDOW_STRIDE,
        dtype=np.int32,
    )


    windows = np.stack(
        [
            features[
                end
                - SEQ_LEN
                + 1:
                end
                + 1
            ]
            for end
            in ends
        ],
        axis=0,
    ).astype(
        np.float32
    )


    endpoint_phase = (
        phase[
            ends
        ]
    )


    labels = np.asarray(
        [
            PHASE_TO_LABEL[
                int(p)
            ]
            for p
            in endpoint_phase
        ],
        dtype=np.int64,
    )


    return (
        windows,
        labels,
        ends,
    )


def build_split(
    split_name,
    split_df,
):

    print()
    print(
        "=" * 90
    )

    print(
        "BUILD",
        split_name.upper(),
    )

    print(
        "=" * 90
    )


    x_parts = []
    y_parts = []
    meta_parts = []


    started = (
        time.perf_counter()
    )

    total = len(
        split_df
    )


    for i, (_, row) in enumerate(
        split_df.iterrows(),
        start=1,
    ):

        cache_path = Path(
            row[
                "cache_path"
            ]
        )


        cache = load_cache(
            cache_path
        )


        features = (
            build_frame_features(
                cache
            )
        )


        phase = np.asarray(
            cache[
                "phase"
            ],
            dtype=np.uint8,
        )


        X, y, ends = (
            make_windows(
                features,
                phase,
            )
        )


        if len(X) == 0:

            print(
                f"[{i:04d}/"
                f"{total:04d}] "
                f"SKIP short "
                f"{row['scene_id']}"
            )

            continue


        frame_ids = np.asarray(
            cache[
                "frame_ids"
            ],
            dtype=np.int32,
        )


        timestamps = np.asarray(
            cache[
                "timestamps"
            ],
            dtype=np.float32,
        )


        x_parts.append(
            X
        )

        y_parts.append(
            y
        )


        meta_parts.append(
            pd.DataFrame(
                {
                    "split":
                        split_name,

                    "scene_id":
                        row[
                            "scene_id"
                        ],

                    "scenario_id":
                        row[
                            "scenario_id"
                        ],

                    "actor_id":
                        row[
                            "actor_id"
                        ],

                    "fall_class":
                        row[
                            "fall_class"
                        ],

                    "camera":
                        int(
                            row[
                                "camera"
                            ]
                        ),

                    "window_end_index":
                        ends,

                    "source_frame_id":
                        frame_ids[
                            ends
                        ],

                    "timestamp":
                        timestamps[
                            ends
                        ],

                    "phase":
                        phase[
                            ends
                        ],

                    "label":
                        y,
                }
            )
        )


        if (
            i <= 5
            or i % 100 == 0
            or i == total
        ):

            print(
                f"[{i:04d}/"
                f"{total:04d}] "
                f"{row['scene_id']} "
                f"frames="
                f"{len(features)} "
                f"windows="
                f"{len(X)}"
            )


    if not x_parts:

        raise RuntimeError(
            f"No windows generated "
            f"for {split_name}"
        )


    X = np.concatenate(
        x_parts,
        axis=0,
    )

    y = np.concatenate(
        y_parts,
        axis=0,
    )

    meta = pd.concat(
        meta_parts,
        ignore_index=True,
    )


    if (
        len(X)
        != len(y)
        or len(meta)
        != len(y)
    ):
        raise RuntimeError(
            f"{split_name}: "
            f"length mismatch"
        )


    if not np.isfinite(
        X
    ).all():

        raise RuntimeError(
            f"{split_name}: "
            f"X contains "
            f"non-finite values"
        )


    out_npz = (
        OUT_ROOT
        / f"{split_name}.npz"
    )


    out_meta = (
        OUT_ROOT
        / (
            f"{split_name}"
            f"_meta.csv.gz"
        )
    )


    print()
    print(
        "Saving:",
        out_npz,
    )


    np.savez_compressed(
        out_npz,
        X=X,
        y=y,
    )


    meta.to_csv(
        out_meta,
        index=False,
        compression="gzip",
    )


    counts = np.bincount(
        y,
        minlength=3,
    )


    print()
    print(
        split_name.upper(),
        "SUMMARY",
    )


    print(
        "shape:",
        X.shape,
    )


    print(
        "dtype:",
        X.dtype,
    )


    for label_id, name in (
        LABEL_NAMES.items()
    ):

        count = int(
            counts[
                label_id
            ]
        )

        ratio = (
            count
            / len(y)
        )

        print(
            f"{label_id} "
            f"{name:<8}: "
            f"{count:>8} "
            f"({ratio:.2%})"
        )


    print(
        "elapsed:",
        f"{time.perf_counter() - started:.1f}s",
    )


    return {
        "split":
            split_name,

        "videos":
            int(
                total
            ),

        "windows":
            int(
                len(y)
            ),

        "shape":
            list(
                X.shape
            ),

        "class_counts":
            {
                str(i):
                    int(
                        counts[i]
                    )
                for i
                in range(3)
            },
    }


def main():

    OUT_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )


    df = pd.read_csv(
        SPLIT_CSV
    )


    required = {
        "scene_id",
        "scenario_id",
        "actor_id",
        "fall_class",
        "camera",
        "split",
        "cache_path",
    }


    missing = (
        required
        - set(
            df.columns
        )
    )


    if missing:

        raise RuntimeError(
            f"Missing columns: "
            f"{sorted(missing)}"
        )


    print(
        "=" * 90
    )

    print(
        "GRU DATASET BUILD"
    )

    print(
        "=" * 90
    )


    print(
        "sequence length:",
        SEQ_LEN,
    )

    print(
        "window stride  :",
        WINDOW_STRIDE,
    )

    print(
        "kp conf        :",
        KP_CONF_THRESHOLD,
    )

    print(
        "feature dim    :",
        FEATURE_DIM,
    )

    print(
        "videos         :",
        len(df),
    )


    print()

    print(
        df[
            "split"
        ].value_counts()
    )


    info = {
        "sequence_length":
            SEQ_LEN,

        "window_stride":
            WINDOW_STRIDE,

        "keypoint_conf_threshold":
            KP_CONF_THRESHOLD,

        "feature_dim":
            FEATURE_DIM,

        "feature_names":
            FEATURE_NAMES,

        "labels":
            {
                str(k): v
                for k, v
                in LABEL_NAMES.items()
            },

        "label_definition":
            {
                "0":
                    "normal = non-fall frames plus pre-fall frames",

                "1":
                    "falling = endpoint inside fall_start_frame..fall_end_frame",

                "2":
                    "fallen = endpoint after fall_end_frame in a fall clip",
            },

        "window_definition":
            (
                "20-frame causal window; "
                "target is determined only "
                "by the final frame"
            ),

        "splits":
            [],
    }


    for split_name in (
        "train",
        "val",
        "test",
    ):

        part = (
            df[
                df[
                    "split"
                ] == split_name
            ]
            .sort_values(
                [
                    "scenario_id",
                    "camera",
                ]
            )
            .reset_index(
                drop=True
            )
        )


        info[
            "splits"
        ].append(
            build_split(
                split_name,
                part,
            )
        )


    # -------------------------------------------------
    # Train class weights
    #
    # CrossEntropyLoss(weight=...)
    # 에서 바로 사용할 값
    # -------------------------------------------------

    train_counts = (
        info[
            "splits"
        ][0][
            "class_counts"
        ]
    )


    train_total = sum(
        train_counts.values()
    )


    weights = {}


    for label_id in range(
        3
    ):

        count = train_counts[
            str(
                label_id
            )
        ]

        weights[
            str(
                label_id
            )
        ] = (
            train_total
            /
            (
                3
                * count
            )
            if count
            else 0.0
        )


    info[
        "train_class_weights"
    ] = weights


    info_path = (
        OUT_ROOT
        / "dataset_info.json"
    )


    with info_path.open(
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            info,
            f,
            ensure_ascii=False,
            indent=2,
        )


    print()
    print(
        "=" * 90
    )

    print(
        "DATASET COMPLETE"
    )

    print(
        "=" * 90
    )


    print(
        "class weights:"
    )


    for (
        label_id,
        weight,
    ) in weights.items():

        print(
            f"  {label_id} "
            f"{LABEL_NAMES[int(label_id)]}: "
            f"{weight:.4f}"
        )


    print()

    print(
        "saved:",
        info_path,
    )


if __name__ == "__main__":
    main()
