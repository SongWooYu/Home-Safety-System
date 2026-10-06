from pathlib import Path
import json
import time

import numpy as np
import pandas as pd


SPLIT_CSV = Path(
    "data/splits/actor_split.csv"
)

OUT_ROOT = Path(
    "data/gru_dataset/v2_actor_disjoint_20f_dynamic"
)

SEQ_LEN = 20
WINDOW_STRIDE = 1

KP_CONF_THRESHOLD = 0.25

EPS = 1e-6

JOINT_COUNT = 17


LABEL_NAMES = {
    0: "normal",
    1: "falling",
    2: "fallen",
}


PHASE_TO_LABEL = {
    0: 0,
    1: 0,
    2: 1,
    3: 2,
}


# COCO joints
LEFT_SHOULDER = 5
RIGHT_SHOULDER = 6

LEFT_HIP = 11
RIGHT_HIP = 12


def feature_names():

    names = []

    # ------------------------------------------------
    # 기존 v1
    # 17 joints x 4 = 68
    # ------------------------------------------------

    for j in range(
        JOINT_COUNT
    ):

        names += [
            f"j{j:02d}_x_rel",
            f"j{j:02d}_y_rel",
            f"j{j:02d}_conf",
            f"j{j:02d}_mask",
        ]


    # 기존 global 8

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


    # ------------------------------------------------
    # v2:
    # 관절별 causal velocity
    # 17 x 2 = 34
    # ------------------------------------------------

    for j in range(
        JOINT_COUNT
    ):

        names += [
            f"j{j:02d}_vx_rel",
            f"j{j:02d}_vy_rel",
        ]


    # ------------------------------------------------
    # bbox dynamics = 6
    # ------------------------------------------------

    names += [
        "bbox_vcx",
        "bbox_vcy",
        "bbox_vw",
        "bbox_vh",
        "bbox_vlog_h_over_w",
        "bbox_acy",
    ]


    # ------------------------------------------------
    # posture geometry = 9
    # ------------------------------------------------

    names += [
        "torso_sin",
        "torso_cos",
        "torso_valid",

        "shoulder_sin",
        "shoulder_cos",
        "shoulder_valid",

        "hip_sin",
        "hip_cos",
        "hip_valid",
    ]


    return names


FEATURE_NAMES = (
    feature_names()
)

FEATURE_DIM = len(
    FEATURE_NAMES
)


def load_cache(path):

    with np.load(
        path,
        allow_pickle=False,
    ) as d:

        return {
            key: d[key].copy()
            for key in d.files
        }


def backward_diff(
    values,
    timestamps,
    valid=None,
    clip=None,
):

    values = np.asarray(
        values,
        dtype=np.float32,
    )

    timestamps = np.asarray(
        timestamps,
        dtype=np.float32,
    )


    out = np.zeros_like(
        values,
        dtype=np.float32,
    )


    if len(values) <= 1:
        return out


    dt = (
        timestamps[1:]
        - timestamps[:-1]
    )


    dt = np.maximum(
        dt,
        1e-3,
    )


    shape = (
        len(dt),
        *(
            [1]
            * (
                values.ndim - 1
            )
        ),
    )


    diff = (
        values[1:]
        - values[:-1]
    ) / dt.reshape(
        shape
    )


    if valid is not None:

        valid = np.asarray(
            valid,
            dtype=bool,
        )


        pair_valid = (
            valid[1:]
            & valid[:-1]
        )


        diff = np.where(
            pair_valid,
            diff,
            0.0,
        )


    diff = np.nan_to_num(
        diff,
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    )


    if clip is not None:

        diff = np.clip(
            diff,
            -clip,
            clip,
        )


    out[1:] = diff.astype(
        np.float32
    )


    return out


def orientation(
    p1,
    p2,
    valid,
):

    dx = (
        p2[:, 0]
        - p1[:, 0]
    )

    dy = (
        p2[:, 1]
        - p1[:, 1]
    )


    norm = np.sqrt(
        dx * dx
        + dy * dy
    )


    good = (
        valid
        & np.isfinite(norm)
        & (
            norm > EPS
        )
    )


    sin_value = np.zeros(
        len(p1),
        dtype=np.float32,
    )

    cos_value = np.zeros(
        len(p1),
        dtype=np.float32,
    )


    sin_value[
        good
    ] = (
        dy[
            good
        ]
        / norm[
            good
        ]
    )


    cos_value[
        good
    ] = (
        dx[
            good
        ]
        / norm[
            good
        ]
    )


    return (
        sin_value,
        cos_value,
        good.astype(
            np.float32
        ),
    )


def build_frame_features(
    cache
):

    xy = np.asarray(
        cache[
            "keypoints_xy"
        ],
        dtype=np.float32,
    )


    conf = np.asarray(
        cache[
            "keypoints_conf"
        ],
        dtype=np.float32,
    )


    boxes = np.asarray(
        cache[
            "boxes_xyxy"
        ],
        dtype=np.float32,
    )


    box_conf = np.asarray(
        cache[
            "box_conf"
        ],
        dtype=np.float32,
    )


    valid = np.asarray(
        cache[
            "valid"
        ],
        dtype=np.uint8,
    ).astype(
        bool
    )


    timestamps = np.asarray(
        cache[
            "timestamps"
        ],
        dtype=np.float32,
    )


    n = len(
        valid
    )


    if xy.shape != (
        n,
        JOINT_COUNT,
        2,
    ):

        raise RuntimeError(
            f"Bad keypoint shape: "
            f"{xy.shape}"
        )


    # =================================================
    # bbox
    # =================================================

    finite_box = (
        np.isfinite(
            boxes
        ).all(
            axis=1
        )
    )


    clean_boxes = (
        np.nan_to_num(
            boxes,
            nan=0.0,
            posinf=0.0,
            neginf=0.0,
        )
    )


    x1 = clean_boxes[:, 0]
    y1 = clean_boxes[:, 1]
    x2 = clean_boxes[:, 2]
    y2 = clean_boxes[:, 3]


    bw_raw = (
        x2 - x1
    )

    bh_raw = (
        y2 - y1
    )


    bbox_valid = (
        valid
        & finite_box
        & (
            bw_raw > EPS
        )
        & (
            bh_raw > EPS
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

    bw = np.zeros(
        n,
        dtype=np.float32,
    )

    bh = np.zeros(
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


    bw[
        bbox_valid
    ] = bw_raw[
        bbox_valid
    ]


    bh[
        bbox_valid
    ] = bh_raw[
        bbox_valid
    ]


    log_aspect = np.zeros(
        n,
        dtype=np.float32,
    )


    log_aspect[
        bbox_valid
    ] = np.log(
        (
            bh[
                bbox_valid
            ]
            + EPS
        )
        /
        (
            bw[
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


    # =================================================
    # keypoint mask
    # =================================================

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


    finite_xy = (
        np.isfinite(
            xy
        ).all(
            axis=2
        )
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


    # =================================================
    # bbox-relative pose
    # =================================================

    safe_w = np.where(
        bbox_valid,
        bw,
        1.0,
    )


    safe_h = np.where(
        bbox_valid,
        bh,
        1.0,
    )


    rel_x = (
        xy[:, :, 0]
        - cx[:, None]
    ) / safe_w[:, None]


    rel_y = (
        xy[:, :, 1]
        - cy[:, None]
    ) / safe_h[:, None]


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


    rel_x[
        ~kp_mask
    ] = 0.0


    rel_y[
        ~kp_mask
    ] = 0.0


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
    ).reshape(
        n,
        JOINT_COUNT * 4,
    )


    # =================================================
    # 기존 global features
    # =================================================

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


    globals_v1 = np.column_stack(
        [
            cx,
            cy,
            bw,
            bh,
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


    # =================================================
    # v2 joint velocities
    # causal backward difference
    # =================================================

    rel_xy = np.stack(
        [
            rel_x,
            rel_y,
        ],
        axis=2,
    )


    velocity_valid = np.repeat(
        kp_mask[
            :,
            :,
            None,
        ],
        2,
        axis=2,
    )


    joint_velocity = (
        backward_diff(
            rel_xy,
            timestamps,
            valid=velocity_valid,
            clip=10.0,
        )
    )


    joint_velocity = (
        joint_velocity
        .reshape(
            n,
            JOINT_COUNT * 2,
        )
    )


    # =================================================
    # bbox velocity
    # =================================================

    bbox_valid_2d = (
        bbox_valid[
            :,
            None,
        ]
    )


    bbox_values = np.column_stack(
        [
            cx,
            cy,
            bw,
            bh,
            log_aspect,
        ]
    ).astype(
        np.float32
    )


    bbox_velocity = (
        backward_diff(
            bbox_values,
            timestamps,
            valid=np.repeat(
                bbox_valid_2d,
                5,
                axis=1,
            ),
            clip=5.0,
        )
    )


    bbox_vcx = (
        bbox_velocity[:, 0]
    )

    bbox_vcy = (
        bbox_velocity[:, 1]
    )

    bbox_vw = (
        bbox_velocity[:, 2]
    )

    bbox_vh = (
        bbox_velocity[:, 3]
    )

    bbox_vaspect = (
        bbox_velocity[:, 4]
    )


    velocity_bbox_valid = np.zeros(
        n,
        dtype=bool,
    )


    if n > 1:

        velocity_bbox_valid[1:] = (
            bbox_valid[1:]
            & bbox_valid[:-1]
        )


    bbox_acy = backward_diff(
        bbox_vcy,
        timestamps,
        valid=velocity_bbox_valid,
        clip=20.0,
    )


    bbox_dynamic = np.column_stack(
        [
            bbox_vcx,
            bbox_vcy,
            bbox_vw,
            bbox_vh,
            bbox_vaspect,
            bbox_acy,
        ]
    ).astype(
        np.float32
    )


    # =================================================
    # posture orientation
    # =================================================

    clean_xy = np.nan_to_num(
        xy,
        nan=0.0,
        posinf=0.0,
        neginf=0.0,
    ).astype(
        np.float32
    )


    left_shoulder = clean_xy[
        :,
        LEFT_SHOULDER,
        :
    ]

    right_shoulder = clean_xy[
        :,
        RIGHT_SHOULDER,
        :
    ]


    left_hip = clean_xy[
        :,
        LEFT_HIP,
        :
    ]

    right_hip = clean_xy[
        :,
        RIGHT_HIP,
        :
    ]


    shoulder_mid = (
        left_shoulder
        + right_shoulder
    ) * 0.5


    hip_mid = (
        left_hip
        + right_hip
    ) * 0.5


    shoulder_pair_valid = (
        kp_mask[
            :,
            LEFT_SHOULDER
        ]
        & kp_mask[
            :,
            RIGHT_SHOULDER
        ]
    )


    hip_pair_valid = (
        kp_mask[
            :,
            LEFT_HIP
        ]
        & kp_mask[
            :,
            RIGHT_HIP
        ]
    )


    torso_valid = (
        shoulder_pair_valid
        & hip_pair_valid
    )


    (
        torso_sin,
        torso_cos,
        torso_ok,
    ) = orientation(
        shoulder_mid,
        hip_mid,
        torso_valid,
    )


    (
        shoulder_sin,
        shoulder_cos,
        shoulder_ok,
    ) = orientation(
        left_shoulder,
        right_shoulder,
        shoulder_pair_valid,
    )


    (
        hip_sin,
        hip_cos,
        hip_ok,
    ) = orientation(
        left_hip,
        right_hip,
        hip_pair_valid,
    )


    posture = np.column_stack(
        [
            torso_sin,
            torso_cos,
            torso_ok,

            shoulder_sin,
            shoulder_cos,
            shoulder_ok,

            hip_sin,
            hip_cos,
            hip_ok,
        ]
    ).astype(
        np.float32
    )


    # =================================================
    # Final
    # 76 + 34 + 6 + 9 = 125
    # =================================================

    features = np.concatenate(
        [
            joints,
            globals_v1,
            joint_velocity,
            bbox_dynamic,
            posture,
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
            f"{features.shape} "
            f"expected "
            f"{(n, FEATURE_DIM)}"
        )


    if not np.isfinite(
        features
    ).all():

        raise RuntimeError(
            "Non-finite feature"
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
                0,
                dtype=np.int64,
            ),

            np.empty(
                0,
                dtype=np.int32,
            ),
        )


    ends = np.arange(
        SEQ_LEN - 1,
        n,
        WINDOW_STRIDE,
        dtype=np.int32,
    )


    X = np.stack(
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


    y = np.asarray(
        [
            PHASE_TO_LABEL[
                int(
                    phase[end]
                )
            ]

            for end
            in ends
        ],
        dtype=np.int64,
    )


    return (
        X,
        y,
        ends,
    )


def build_split(
    split_name,
    split_df,
):

    print()
    print("=" * 90)
    print(
        "BUILD",
        split_name.upper(),
    )
    print("=" * 90)


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


        (
            X,
            y,
            ends,
        ) = make_windows(
            features,
            phase,
        )


        if len(X) == 0:

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
        len(X) != len(y)
        or len(meta) != len(y)
    ):

        raise RuntimeError(
            "Length mismatch"
        )


    if not np.isfinite(
        X
    ).all():

        raise RuntimeError(
            "Dataset contains "
            "non-finite value"
        )


    OUT_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )


    out_npz = (
        OUT_ROOT
        / f"{split_name}.npz"
    )


    out_meta = (
        OUT_ROOT
        / f"{split_name}_meta.csv.gz"
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
        "SUMMARY"
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

        print(
            f"{label_id} "
            f"{name:<8}: "
            f"{count:>8} "
            f"({count / len(y):.2%})"
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

    df = pd.read_csv(
        SPLIT_CSV
    )


    print(
        "=" * 90
    )

    print(
        "GRU V2 DYNAMIC DATASET"
    )

    print(
        "=" * 90
    )


    print(
        "sequence length:",
        SEQ_LEN,
    )

    print(
        "stride         :",
        WINDOW_STRIDE,
    )

    print(
        "feature dim    :",
        FEATURE_DIM,
    )

    print(
        "videos         :",
        len(df),
    )


    if FEATURE_DIM != 125:

        raise RuntimeError(
            f"Expected 125 features, "
            f"got {FEATURE_DIM}"
        )


    info = {
        "version":
            "v2_dynamic",

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


        result = build_split(
            split_name,
            part,
        )


        info[
            "splits"
        ].append(
            result
        )


    # ---------------------------------------------
    # inverse class weights
    # ---------------------------------------------

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


    inverse_weights = {}


    sqrt_weights = {}


    for i in range(3):

        count = train_counts[
            str(i)
        ]


        weight = (
            train_total
            / (
                3
                * count
            )
        )


        inverse_weights[
            str(i)
        ] = float(
            weight
        )


        sqrt_weights[
            str(i)
        ] = float(
            np.sqrt(
                weight
            )
        )


    info[
        "train_class_weights_inverse"
    ] = inverse_weights


    info[
        "train_class_weights_sqrt"
    ] = sqrt_weights


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
    print("=" * 90)
    print(
        "DATASET COMPLETE"
    )
    print("=" * 90)


    print(
        "inverse weights:"
    )

    for i in range(3):

        print(
            f"  {i} "
            f"{LABEL_NAMES[i]}: "
            f"{inverse_weights[str(i)]:.4f}"
        )


    print()
    print(
        "sqrt weights:"
    )

    for i in range(3):

        print(
            f"  {i} "
            f"{LABEL_NAMES[i]}: "
            f"{sqrt_weights[str(i)]:.4f}"
        )


    print()
    print(
        "saved:",
        info_path,
    )


if __name__ == "__main__":
    main()
