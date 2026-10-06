from pathlib import Path
import gc
import json
import random
import time

import numpy as np
import pandas as pd
import torch
import torch.nn as nn

from sklearn.metrics import (
    accuracy_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
)

from torch.utils.data import (
    DataLoader,
    TensorDataset,
)


# ============================================================
# Experiment definition
#
# A = 76  + inverse       existing v1
# B = 76  + sqrt inverse  TRAIN HERE
# C = 125 + inverse       TRAIN HERE
# D = 125 + sqrt inverse  existing v2
# ============================================================

EXPERIMENTS = [
    {
        "name": "B_76_sqrt",
        "data_root": Path(
            "data/gru_dataset/v1_actor_disjoint_20f"
        ),
        "run_root": Path(
            "runs/gru_ablation_76_sqrt"
        ),
        "weight_mode": "sqrt",
    },

    {
        "name": "C_125_inverse",
        "data_root": Path(
            "data/gru_dataset/v2_actor_disjoint_20f_dynamic"
        ),
        "run_root": Path(
            "runs/gru_ablation_125_inverse"
        ),
        "weight_mode": "inverse",
    },
]


SEED = 42

BATCH_SIZE = 512

EPOCHS = 50

LEARNING_RATE = 1e-3

WEIGHT_DECAY = 1e-4

HIDDEN_SIZE = 128

NUM_LAYERS = 2

DROPOUT = 0.20

PATIENCE = 8

GRAD_CLIP = 1.0

NUM_CLASSES = 3


LABEL_NAMES = [
    "normal",
    "falling",
    "fallen",
]


def set_seed(seed):

    random.seed(seed)

    np.random.seed(seed)

    torch.manual_seed(seed)


def get_device():

    if (
        torch.backends
        .mps
        .is_available()
    ):
        return torch.device(
            "mps"
        )

    if torch.cuda.is_available():
        return torch.device(
            "cuda"
        )

    return torch.device(
        "cpu"
    )


def load_npz(
    data_root,
    split,
):

    path = (
        data_root
        / f"{split}.npz"
    )

    with np.load(path) as d:

        X = np.asarray(
            d["X"],
            dtype=np.float32,
        )

        y = np.asarray(
            d["y"],
            dtype=np.int64,
        )

    if X.ndim != 3:

        raise RuntimeError(
            f"{path}: "
            f"bad X shape "
            f"{X.shape}"
        )

    if len(X) != len(y):

        raise RuntimeError(
            f"{path}: "
            "length mismatch"
        )

    if not np.isfinite(
        X
    ).all():

        raise RuntimeError(
            f"{path}: "
            "non-finite X"
        )

    return (
        X,
        y,
    )


def calculate_class_weights(
    y,
):

    counts = np.bincount(
        y,
        minlength=NUM_CLASSES,
    ).astype(
        np.float64
    )

    total = counts.sum()

    inverse = (
        total
        /
        (
            NUM_CLASSES
            * counts
        )
    )

    sqrt_inverse = np.sqrt(
        inverse
    )

    return (
        counts,
        inverse.astype(
            np.float32
        ),
        sqrt_inverse.astype(
            np.float32
        ),
    )


def make_loader(
    X,
    y,
    shuffle,
):

    dataset = TensorDataset(
        torch.from_numpy(X),
        torch.from_numpy(y),
    )

    return DataLoader(
        dataset,
        batch_size=BATCH_SIZE,
        shuffle=shuffle,
        num_workers=0,
        drop_last=False,
    )


class FallGRU(nn.Module):

    def __init__(
        self,
        input_size,
    ):

        super().__init__()

        self.input_norm = (
            nn.LayerNorm(
                input_size
            )
        )

        self.gru = nn.GRU(
            input_size=input_size,
            hidden_size=HIDDEN_SIZE,
            num_layers=NUM_LAYERS,
            batch_first=True,

            dropout=(
                DROPOUT
                if NUM_LAYERS > 1
                else 0.0
            ),

            bidirectional=False,
        )

        self.head = nn.Sequential(

            nn.LayerNorm(
                HIDDEN_SIZE
            ),

            nn.Dropout(
                DROPOUT
            ),

            nn.Linear(
                HIDDEN_SIZE,
                64,
            ),

            nn.ReLU(),

            nn.Dropout(
                DROPOUT
            ),

            nn.Linear(
                64,
                NUM_CLASSES,
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


def calculate_metrics(
    y_true,
    y_pred,
):

    return {
        "accuracy":
            accuracy_score(
                y_true,
                y_pred,
            ),

        "balanced_accuracy":
            balanced_accuracy_score(
                y_true,
                y_pred,
            ),

        "macro_f1":
            f1_score(
                y_true,
                y_pred,
                average="macro",
                zero_division=0,
            ),
    }


def run_epoch(
    model,
    loader,
    criterion,
    device,
    optimizer=None,
):

    training = (
        optimizer is not None
    )

    model.train(
        training
    )

    total_loss = 0.0

    total_count = 0

    true_parts = []

    pred_parts = []

    context = (
        torch.enable_grad()
        if training
        else torch.no_grad()
    )

    with context:

        for xb, yb in loader:

            xb = xb.to(
                device
            )

            yb = yb.to(
                device
            )

            if training:

                optimizer.zero_grad(
                    set_to_none=True
                )

            logits = model(
                xb
            )

            loss = criterion(
                logits,
                yb,
            )

            if training:

                loss.backward()

                nn.utils.clip_grad_norm_(
                    model.parameters(),
                    GRAD_CLIP,
                )

                optimizer.step()

            n = yb.size(
                0
            )

            total_loss += (
                loss.item()
                * n
            )

            total_count += n

            true_parts.append(
                yb
                .detach()
                .cpu()
                .numpy()
            )

            pred_parts.append(
                logits
                .argmax(
                    dim=1
                )
                .detach()
                .cpu()
                .numpy()
            )

    y_true = np.concatenate(
        true_parts
    )

    y_pred = np.concatenate(
        pred_parts
    )

    metrics = calculate_metrics(
        y_true,
        y_pred,
    )

    metrics[
        "loss"
    ] = (
        total_loss
        / total_count
    )

    return metrics


def predict(
    model,
    loader,
    device,
):

    model.eval()

    true_parts = []

    prob_parts = []

    with torch.no_grad():

        for xb, yb in loader:

            logits = model(
                xb.to(
                    device
                )
            )

            prob = torch.softmax(
                logits,
                dim=1,
            )

            true_parts.append(
                yb.numpy()
            )

            prob_parts.append(
                prob
                .cpu()
                .numpy()
            )

    y_true = np.concatenate(
        true_parts
    )

    prob = np.concatenate(
        prob_parts
    )

    y_pred = prob.argmax(
        axis=1
    )

    return (
        y_true,
        y_pred,
        prob,
    )


def train_one(
    cfg,
    device,
):

    name = cfg[
        "name"
    ]

    data_root = cfg[
        "data_root"
    ]

    run_root = cfg[
        "run_root"
    ]

    weight_mode = cfg[
        "weight_mode"
    ]

    run_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    set_seed(
        SEED
    )

    print()
    print(
        "=" * 100
    )

    print(
        "ABLATION:",
        name
    )

    print(
        "=" * 100
    )

    print(
        "data root  :",
        data_root,
    )

    print(
        "weight mode:",
        weight_mode,
    )

    print(
        "device     :",
        device,
    )

    X_train, y_train = (
        load_npz(
            data_root,
            "train",
        )
    )

    X_val, y_val = (
        load_npz(
            data_root,
            "val",
        )
    )

    input_size = int(
        X_train.shape[
            2
        ]
    )

    (
        counts,
        inverse_weights,
        sqrt_weights,
    ) = calculate_class_weights(
        y_train
    )

    if (
        weight_mode
        == "inverse"
    ):

        class_weights = (
            inverse_weights
        )

    elif (
        weight_mode
        == "sqrt"
    ):

        class_weights = (
            sqrt_weights
        )

    else:

        raise ValueError(
            weight_mode
        )

    print(
        "train:",
        X_train.shape,
        y_train.shape,
    )

    print(
        "val  :",
        X_val.shape,
        y_val.shape,
    )

    print(
        "class counts:",
        counts.astype(
            int
        ),
    )

    print(
        "weights:",
        class_weights,
    )

    train_loader = (
        make_loader(
            X_train,
            y_train,
            True,
        )
    )

    val_loader = (
        make_loader(
            X_val,
            y_val,
            False,
        )
    )

    model = FallGRU(
        input_size
    ).to(
        device
    )

    criterion = (
        nn.CrossEntropyLoss(

            weight=torch.tensor(
                class_weights,
                dtype=torch.float32,
                device=device,
            )
        )
    )

    optimizer = (
        torch.optim.AdamW(

            model.parameters(),

            lr=
                LEARNING_RATE,

            weight_decay=
                WEIGHT_DECAY,
        )
    )

    scheduler = (
        torch.optim.lr_scheduler
        .ReduceLROnPlateau(

            optimizer,

            mode="max",

            factor=0.5,

            patience=3,

            min_lr=1e-5,
        )
    )

    best_path = (
        run_root
        / "best.pt"
    )

    history = []

    best_f1 = -1.0

    best_epoch = 0

    no_improve = 0

    start_all = (
        time.perf_counter()
    )

    for epoch in range(
        1,
        EPOCHS + 1,
    ):

        start_epoch = (
            time.perf_counter()
        )

        train_metrics = (
            run_epoch(
                model,
                train_loader,
                criterion,
                device,
                optimizer,
            )
        )

        val_metrics = (
            run_epoch(
                model,
                val_loader,
                criterion,
                device,
            )
        )

        val_f1 = float(
            val_metrics[
                "macro_f1"
            ]
        )

        scheduler.step(
            val_f1
        )

        lr_now = (
            optimizer
            .param_groups[0][
                "lr"
            ]
        )

        elapsed = (
            time.perf_counter()
            - start_epoch
        )

        row = {
            "epoch":
                epoch,

            "lr":
                lr_now,

            "train_loss":
                train_metrics[
                    "loss"
                ],

            "train_accuracy":
                train_metrics[
                    "accuracy"
                ],

            "train_balanced_accuracy":
                train_metrics[
                    "balanced_accuracy"
                ],

            "train_macro_f1":
                train_metrics[
                    "macro_f1"
                ],

            "val_loss":
                val_metrics[
                    "loss"
                ],

            "val_accuracy":
                val_metrics[
                    "accuracy"
                ],

            "val_balanced_accuracy":
                val_metrics[
                    "balanced_accuracy"
                ],

            "val_macro_f1":
                val_f1,

            "elapsed_sec":
                elapsed,
        }

        history.append(
            row
        )

        pd.DataFrame(
            history
        ).to_csv(
            run_root
            / "history.csv",
            index=False,
        )

        print(

            f"Epoch "
            f"{epoch:02d}/"
            f"{EPOCHS:02d} "

            f"lr="
            f"{lr_now:.2e} "

            f"train_loss="
            f"{train_metrics['loss']:.4f} "

            f"train_f1="
            f"{train_metrics['macro_f1']:.4f} "

            f"val_loss="
            f"{val_metrics['loss']:.4f} "

            f"val_acc="
            f"{val_metrics['accuracy']:.4f} "

            f"val_bal_acc="
            f"{val_metrics['balanced_accuracy']:.4f} "

            f"val_f1="
            f"{val_f1:.4f} "

            f"time="
            f"{elapsed:.1f}s"
        )

        if (
            val_f1
            > best_f1
            + 1e-5
        ):

            best_f1 = (
                val_f1
            )

            best_epoch = (
                epoch
            )

            no_improve = 0

            torch.save(

                {
                    "model_state":
                        model.state_dict(),

                    "experiment":
                        name,

                    "epoch":
                        epoch,

                    "val_macro_f1":
                        best_f1,

                    "input_size":
                        input_size,

                    "hidden_size":
                        HIDDEN_SIZE,

                    "num_layers":
                        NUM_LAYERS,

                    "dropout":
                        DROPOUT,

                    "num_classes":
                        NUM_CLASSES,

                    "sequence_length":
                        20,

                    "class_weight_mode":
                        weight_mode,

                    "class_weights":
                        class_weights.tolist(),

                    "seed":
                        SEED,
                },

                best_path,
            )

            print(
                "  BEST ->",
                best_path,
            )

        else:

            no_improve += 1

        if (
            no_improve
            >= PATIENCE
        ):

            print(
                "Early stopping:",
                PATIENCE,
                "epochs without "
                "val Macro-F1 improvement"
            )

            break

        if (
            device.type
            == "mps"
        ):

            torch.mps.empty_cache()

    checkpoint = (
        torch.load(
            best_path,
            map_location=device,
            weights_only=False,
        )
    )

    model.load_state_dict(
        checkpoint[
            "model_state"
        ]
    )

    (
        y_true,
        y_pred,
        prob,
    ) = predict(
        model,
        val_loader,
        device,
    )

    metrics = calculate_metrics(
        y_true,
        y_pred,
    )

    report = (
        classification_report(

            y_true,
            y_pred,

            labels=[
                0,
                1,
                2,
            ],

            target_names=
                LABEL_NAMES,

            output_dict=True,

            zero_division=0,
        )
    )

    report_text = (
        classification_report(

            y_true,
            y_pred,

            labels=[
                0,
                1,
                2,
            ],

            target_names=
                LABEL_NAMES,

            digits=4,

            zero_division=0,
        )
    )

    cm = confusion_matrix(
        y_true,
        y_pred,
        labels=[
            0,
            1,
            2,
        ],
    )

    meta = pd.read_csv(
        data_root
        / "val_meta.csv.gz"
    )

    if len(meta) != len(
        y_true
    ):

        raise RuntimeError(
            f"{name}: "
            "val_meta mismatch"
        )

    pred_df = (
        meta.copy()
    )

    pred_df[
        "y_true"
    ] = y_true

    pred_df[
        "y_pred"
    ] = y_pred

    pred_df[
        "prob_normal"
    ] = prob[:, 0]

    pred_df[
        "prob_falling"
    ] = prob[:, 1]

    pred_df[
        "prob_fallen"
    ] = prob[:, 2]

    pred_df[
        "alert_score"
    ] = (
        prob[:, 1]
        + prob[:, 2]
    )

    pred_path = (
        run_root
        / "val_predictions.csv.gz"
    )

    pred_df.to_csv(
        pred_path,
        index=False,
        compression="gzip",
    )

    pd.DataFrame(
        cm,

        index=[
            "true_normal",
            "true_falling",
            "true_fallen",
        ],

        columns=[
            "pred_normal",
            "pred_falling",
            "pred_fallen",
        ],

    ).to_csv(
        run_root
        / "val_confusion_matrix.csv"
    )

    result = {

        "experiment":
            name,

        "input_size":
            input_size,

        "weight_mode":
            weight_mode,

        "class_weights":
            class_weights.tolist(),

        "best_epoch":
            int(
                best_epoch
            ),

        "best_val_macro_f1":
            float(
                best_f1
            ),

        "val_accuracy":
            float(
                metrics[
                    "accuracy"
                ]
            ),

        "val_balanced_accuracy":
            float(
                metrics[
                    "balanced_accuracy"
                ]
            ),

        "val_macro_f1":
            float(
                metrics[
                    "macro_f1"
                ]
            ),

        "normal_f1":
            float(
                report[
                    "normal"
                ][
                    "f1-score"
                ]
            ),

        "falling_precision":
            float(
                report[
                    "falling"
                ][
                    "precision"
                ]
            ),

        "falling_recall":
            float(
                report[
                    "falling"
                ][
                    "recall"
                ]
            ),

        "falling_f1":
            float(
                report[
                    "falling"
                ][
                    "f1-score"
                ]
            ),

        "fallen_f1":
            float(
                report[
                    "fallen"
                ][
                    "f1-score"
                ]
            ),

        "confusion_matrix":
            cm.tolist(),

        "training_time_sec":
            float(
                time.perf_counter()
                - start_all
            ),
    }

    with (
        run_root
        / "metrics.json"
    ).open(
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            result,
            f,
            ensure_ascii=False,
            indent=2,
        )

    print()
    print(
        "=" * 100
    )

    print(
        "RESULT:",
        name
    )

    print(
        "=" * 100
    )

    print(
        "best epoch:",
        best_epoch,
    )

    print(
        "Macro-F1:",
        f"{metrics['macro_f1']:.6f}",
    )

    print(
        "Balanced Accuracy:",
        f"{metrics['balanced_accuracy']:.6f}",
    )

    print()

    print(
        report_text
    )

    print(
        "confusion matrix:"
    )

    print(
        cm
    )

    print(
        "saved:",
        run_root
    )

    result[
        "prediction_path"
    ] = str(
        pred_path
    )

    # 메모리 정리
    del (
        X_train,
        y_train,
        X_val,
        y_val,
        train_loader,
        val_loader,
        model,
    )

    gc.collect()

    if (
        device.type
        == "mps"
    ):

        torch.mps.empty_cache()

    return result


def summarize_existing(
    experiment,
    prediction_path,
    input_size,
    weight_mode,
):

    path = Path(
        prediction_path
    )

    if not path.exists():

        raise RuntimeError(
            f"Missing existing "
            f"prediction: {path}"
        )

    df = pd.read_csv(
        path
    )

    y_true = (
        df[
            "y_true"
        ]
        .to_numpy(
            dtype=np.int64
        )
    )

    y_pred = (
        df[
            "y_pred"
        ]
        .to_numpy(
            dtype=np.int64
        )
    )

    report = (
        classification_report(

            y_true,
            y_pred,

            labels=[
                0,
                1,
                2,
            ],

            target_names=
                LABEL_NAMES,

            output_dict=True,

            zero_division=0,
        )
    )

    return {

        "experiment":
            experiment,

        "input_size":
            input_size,

        "weight_mode":
            weight_mode,

        "val_accuracy":
            float(
                accuracy_score(
                    y_true,
                    y_pred,
                )
            ),

        "val_balanced_accuracy":
            float(
                balanced_accuracy_score(
                    y_true,
                    y_pred,
                )
            ),

        "val_macro_f1":
            float(
                f1_score(
                    y_true,
                    y_pred,
                    average="macro",
                    zero_division=0,
                )
            ),

        "normal_f1":
            float(
                report[
                    "normal"
                ][
                    "f1-score"
                ]
            ),

        "falling_precision":
            float(
                report[
                    "falling"
                ][
                    "precision"
                ]
            ),

        "falling_recall":
            float(
                report[
                    "falling"
                ][
                    "recall"
                ]
            ),

        "falling_f1":
            float(
                report[
                    "falling"
                ][
                    "f1-score"
                ]
            ),

        "fallen_f1":
            float(
                report[
                    "fallen"
                ][
                    "f1-score"
                ]
            ),
    }


def main():

    device = get_device()

    print(
        "=" * 100
    )

    print(
        "4-WAY GRU ABLATION"
    )

    print(
        "=" * 100
    )

    print(
        "A = 76  features + inverse "
        "(existing v1)"
    )

    print(
        "B = 76  features + sqrt "
        "(train)"
    )

    print(
        "C = 125 features + inverse "
        "(train)"
    )

    print(
        "D = 125 features + sqrt "
        "(existing v2)"
    )

    print(
        "device:",
        device
    )

    print(
        "TEST SET: NOT LOADED"
    )

    trained = []

    for cfg in EXPERIMENTS:

        result = train_one(
            cfg,
            device,
        )

        trained.append(
            result
        )

    # ------------------------------------------------
    # A / D 기존 validation prediction과
    # B / C 새 prediction을 동일 방식으로 요약
    # ------------------------------------------------

    rows = []

    rows.append(
        summarize_existing(
            "A_76_inverse",
            (
                "runs/"
                "event_compare_v1_v2_val/"
                "v1_val_predictions.csv.gz"
            ),
            76,
            "inverse",
        )
    )

    rows.append(
        summarize_existing(
            "B_76_sqrt",
            (
                "runs/"
                "gru_ablation_76_sqrt/"
                "val_predictions.csv.gz"
            ),
            76,
            "sqrt",
        )
    )

    rows.append(
        summarize_existing(
            "C_125_inverse",
            (
                "runs/"
                "gru_ablation_125_inverse/"
                "val_predictions.csv.gz"
            ),
            125,
            "inverse",
        )
    )

    rows.append(
        summarize_existing(
            "D_125_sqrt",
            (
                "runs/"
                "event_compare_v1_v2_val/"
                "v2_val_predictions.csv.gz"
            ),
            125,
            "sqrt",
        )
    )

    summary = pd.DataFrame(
        rows
    )

    out_path = Path(
        "runs/gru_ablation_window_summary.csv"
    )

    summary.to_csv(
        out_path,
        index=False,
    )

    print()
    print(
        "=" * 100
    )

    print(
        "FINAL 4-WAY WINDOW ABLATION"
    )

    print(
        "=" * 100
    )

    cols = [
        "experiment",
        "input_size",
        "weight_mode",
        "val_accuracy",
        "val_balanced_accuracy",
        "val_macro_f1",
        "normal_f1",
        "falling_precision",
        "falling_recall",
        "falling_f1",
        "fallen_f1",
    ]

    print(
        summary[
            cols
        ].to_string(
            index=False
        )
    )

    print()
    print(
        "saved:",
        out_path
    )

    print(
        "TEST SET WAS NOT LOADED."
    )


if __name__ == "__main__":
    main()
