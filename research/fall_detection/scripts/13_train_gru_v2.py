from pathlib import Path
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


DATA_ROOT = Path(
    "data/gru_dataset/v2_actor_disjoint_20f_dynamic"
)

INFO_PATH = (
    DATA_ROOT
    / "dataset_info.json"
)

RUN_ROOT = Path(
    "runs/gru_v2"
)


SEED = 42

BATCH_SIZE = 512

EPOCHS = 50

LR = 1e-3

WEIGHT_DECAY = 1e-4

HIDDEN = 128

LAYERS = 2

DROPOUT = 0.20

PATIENCE = 8

GRAD_CLIP = 1.0


LABELS = [
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


def load_npz(name):

    path = (
        DATA_ROOT
        / f"{name}.npz"
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


    if (
        len(X) != len(y)
        or X.ndim != 3
        or not np.isfinite(X).all()
    ):

        raise RuntimeError(
            f"Invalid {name} dataset: "
            f"X={X.shape}, "
            f"y={y.shape}"
        )


    return X, y


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
            hidden_size=HIDDEN,
            num_layers=LAYERS,
            batch_first=True,

            dropout=(
                DROPOUT
                if LAYERS > 1
                else 0.0
            ),

            bidirectional=False,
        )


        self.head = nn.Sequential(

            nn.LayerNorm(
                HIDDEN
            ),

            nn.Dropout(
                DROPOUT
            ),

            nn.Linear(
                HIDDEN,
                64,
            ),

            nn.ReLU(),

            nn.Dropout(
                DROPOUT
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

    total_n = 0

    ys = []

    ps = []


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


            total_n += n


            ys.append(
                yb
                .detach()
                .cpu()
                .numpy()
            )


            ps.append(
                logits
                .argmax(
                    dim=1
                )
                .detach()
                .cpu()
                .numpy()
            )


    y_true = np.concatenate(
        ys
    )


    y_pred = np.concatenate(
        ps
    )


    return {

        "loss":
            total_loss
            / total_n,

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


def predict(
    model,
    loader,
    device,
):

    model.eval()


    ys = []

    ps = []

    probs = []


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


            ys.append(
                yb.numpy()
            )


            ps.append(
                prob
                .argmax(
                    dim=1
                )
                .cpu()
                .numpy()
            )


            probs.append(
                prob
                .cpu()
                .numpy()
            )


    return (
        np.concatenate(
            ys
        ),

        np.concatenate(
            ps
        ),

        np.concatenate(
            probs
        ),
    )


def main():

    set_seed(
        SEED
    )


    RUN_ROOT.mkdir(
        parents=True,
        exist_ok=True,
    )


    with INFO_PATH.open(
        "r",
        encoding="utf-8",
    ) as f:

        info = json.load(
            f
        )


    input_size = int(
        info[
            "feature_dim"
        ]
    )


    class_weights = np.asarray(

        [
            info[
                "train_class_weights_sqrt"
            ][
                str(i)
            ]

            for i
            in range(3)
        ],

        dtype=np.float32,
    )


    device = get_device()


    print(
        "=" * 90
    )

    print(
        "GRU V2 DYNAMIC TRAINING"
    )

    print(
        "=" * 90
    )


    print(
        "input size :",
        input_size,
    )

    print(
        "seq length :",
        info[
            "sequence_length"
        ],
    )

    print(
        "batch size :",
        BATCH_SIZE,
    )

    print(
        "hidden size:",
        HIDDEN,
    )

    print(
        "layers     :",
        LAYERS,
    )

    print(
        "dropout    :",
        DROPOUT,
    )

    print(
        "class w    :",
        class_weights,
    )

    print(
        "device     :",
        device,
    )


    X_train, y_train = (
        load_npz(
            "train"
        )
    )


    X_val, y_val = (
        load_npz(
            "val"
        )
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

            lr=LR,

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


    checkpoint_path = (
        RUN_ROOT
        / "best.pt"
    )


    best_f1 = -1.0

    best_epoch = 0

    no_improve = 0

    history = []


    train_start = (
        time.perf_counter()
    )


    for epoch in range(
        1,
        EPOCHS + 1,
    ):

        epoch_start = (
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


        scheduler.step(
            val_metrics[
                "macro_f1"
            ]
        )


        lr_now = (
            optimizer
            .param_groups[0][
                "lr"
            ]
        )


        elapsed = (
            time.perf_counter()
            - epoch_start
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
                val_metrics[
                    "macro_f1"
                ],

            "elapsed_sec":
                elapsed,
        }


        history.append(
            row
        )


        pd.DataFrame(
            history
        ).to_csv(
            RUN_ROOT
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
            f"{val_metrics['macro_f1']:.4f} "

            f"time="
            f"{elapsed:.1f}s"
        )


        if (
            val_metrics[
                "macro_f1"
            ]
            > best_f1
            + 1e-5
        ):

            best_f1 = float(
                val_metrics[
                    "macro_f1"
                ]
            )


            best_epoch = (
                epoch
            )


            no_improve = 0


            torch.save(

                {
                    "model_state":
                        model.state_dict(),

                    "epoch":
                        epoch,

                    "val_macro_f1":
                        best_f1,

                    "input_size":
                        input_size,

                    "hidden_size":
                        HIDDEN,

                    "num_layers":
                        LAYERS,

                    "dropout":
                        DROPOUT,

                    "num_classes":
                        3,

                    "label_names":
                        LABELS,

                    "class_weight_mode":
                        "sqrt_inverse",

                    "class_weights":
                        class_weights.tolist(),

                    "sequence_length":
                        info[
                            "sequence_length"
                        ],

                    "feature_names":
                        info[
                            "feature_names"
                        ],
                },

                checkpoint_path,
            )


            print(
                "  BEST ->",
                checkpoint_path,
            )


        else:

            no_improve += 1


        if (
            no_improve
            >= PATIENCE
        ):

            print(
                "Early stopping: "
                f"{PATIENCE} epochs "
                "without val "
                "macro-F1 improvement"
            )

            break


        if (
            device.type
            == "mps"
        ):

            torch.mps.empty_cache()


    print()
    print(
        "=" * 90
    )

    print(
        "BEST VALIDATION MODEL"
    )

    print(
        "=" * 90
    )


    print(
        "best epoch:",
        best_epoch,
    )


    print(
        "best val macro F1:",
        f"{best_f1:.6f}",
    )


    print(
        "training time:",
        f"{(time.perf_counter() - train_start) / 60:.1f} min",
    )


    checkpoint = (
        torch.load(
            checkpoint_path,
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


    accuracy = float(
        accuracy_score(
            y_true,
            y_pred,
        )
    )


    balanced = float(
        balanced_accuracy_score(
            y_true,
            y_pred,
        )
    )


    macro_f1 = float(
        f1_score(
            y_true,
            y_pred,
            average="macro",
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
                LABELS,

            digits=4,

            zero_division=0,
        )
    )


    report_dict = (
        classification_report(

            y_true,
            y_pred,

            labels=[
                0,
                1,
                2,
            ],

            target_names=
                LABELS,

            output_dict=True,

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


    pd.DataFrame(

        cm,

        index=[
            f"true_{x}"
            for x
            in LABELS
        ],

        columns=[
            f"pred_{x}"
            for x
            in LABELS
        ],

    ).to_csv(
        RUN_ROOT
        / "val_confusion_matrix.csv"
    )


    meta = pd.read_csv(
        DATA_ROOT
        / "val_meta.csv.gz"
    )


    if (
        len(meta)
        != len(y_true)
    ):

        raise RuntimeError(
            "val_meta "
            "length mismatch"
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


    for i, name in enumerate(
        LABELS
    ):

        pred_df[
            f"prob_{name}"
        ] = prob[
            :,
            i,
        ]


    pred_df.to_csv(

        RUN_ROOT
        / "val_predictions.csv.gz",

        index=False,

        compression="gzip",
    )


    metrics = {

        "best_epoch":
            best_epoch,

        "best_val_macro_f1":
            best_f1,

        "val_accuracy":
            accuracy,

        "val_balanced_accuracy":
            balanced,

        "val_macro_f1":
            macro_f1,

        "classification_report":
            report_dict,

        "confusion_matrix":
            cm.tolist(),

        "class_weight_mode":
            "sqrt_inverse",

        "class_weights":
            class_weights.tolist(),
    }


    (
        RUN_ROOT
        / "metrics.json"
    ).write_text(

        json.dumps(
            metrics,
            ensure_ascii=False,
            indent=2,
        ),

        encoding="utf-8",
    )


    print()
    print(
        "=" * 90
    )

    print(
        "VALIDATION RESULT"
    )

    print(
        "=" * 90
    )


    print(
        "accuracy         :",
        f"{accuracy:.6f}",
    )


    print(
        "balanced accuracy:",
        f"{balanced:.6f}",
    )


    print(
        "macro F1         :",
        f"{macro_f1:.6f}",
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


    print()
    print(
        "NOTE: test set was NOT loaded."
    )


    print(
        "saved:",
        RUN_ROOT,
    )


if __name__ == "__main__":

    main()
