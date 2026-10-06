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
    "data/gru_dataset/v1_actor_disjoint_20f"
)

INFO_PATH = (
    DATA_ROOT
    / "dataset_info.json"
)

RUN_ROOT = Path(
    "runs/gru_v1"
)


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


def load_npz(path):

    with np.load(path) as d:

        X = np.array(
            d["X"],
            dtype=np.float32,
            copy=True,
        )

        y = np.array(
            d["y"],
            dtype=np.int64,
            copy=True,
        )


    if len(X) != len(y):

        raise RuntimeError(
            f"Length mismatch: "
            f"{path} "
            f"X={len(X)} "
            f"y={len(y)}"
        )


    if X.ndim != 3:

        raise RuntimeError(
            f"Expected X ndim=3, "
            f"got {X.shape}"
        )


    if not np.isfinite(
        X
    ).all():

        raise RuntimeError(
            f"Non-finite values "
            f"in {path}"
        )


    return X, y


def make_loader(
    X,
    y,
    batch_size,
    shuffle,
):

    dataset = TensorDataset(
        torch.from_numpy(X),
        torch.from_numpy(y),
    )


    return DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=shuffle,
        num_workers=0,
        drop_last=False,
    )


class FallGRU(nn.Module):

    def __init__(
        self,
        input_size,
        hidden_size,
        num_layers,
        dropout,
        num_classes,
    ):

        super().__init__()


        self.input_norm = (
            nn.LayerNorm(
                input_size
            )
        )


        self.gru = nn.GRU(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,

            dropout=(
                dropout
                if num_layers > 1
                else 0.0
            ),

            bidirectional=False,
        )


        self.head = nn.Sequential(

            nn.LayerNorm(
                hidden_size
            ),

            nn.Dropout(
                dropout
            ),

            nn.Linear(
                hidden_size,
                64,
            ),

            nn.ReLU(),

            nn.Dropout(
                dropout
            ),

            nn.Linear(
                64,
                num_classes,
            ),
        )


    def forward(self, x):

        x = self.input_norm(
            x
        )


        _, h_n = self.gru(
            x
        )


        last_hidden = h_n[
            -1
        ]


        return self.head(
            last_hidden
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


    if training:
        model.train()
    else:
        model.eval()


    total_loss = 0.0
    total_count = 0

    all_true = []
    all_pred = []


    context = (
        torch.enable_grad()
        if training
        else torch.no_grad()
    )


    with context:

        for X, y in loader:

            X = X.to(
                device
            )

            y = y.to(
                device
            )


            if training:

                optimizer.zero_grad(
                    set_to_none=True
                )


            logits = model(
                X
            )


            loss = criterion(
                logits,
                y,
            )


            if training:

                loss.backward()


                nn.utils.clip_grad_norm_(
                    model.parameters(),
                    GRAD_CLIP,
                )


                optimizer.step()


            batch_size = (
                y.size(0)
            )


            total_loss += (
                loss.item()
                * batch_size
            )


            total_count += (
                batch_size
            )


            pred = (
                logits
                .argmax(
                    dim=1
                )
                .detach()
                .cpu()
                .numpy()
            )


            true = (
                y
                .detach()
                .cpu()
                .numpy()
            )


            all_pred.append(
                pred
            )


            all_true.append(
                true
            )


    y_true = np.concatenate(
        all_true
    )


    y_pred = np.concatenate(
        all_pred
    )


    return {

        "loss":
            total_loss
            / total_count,

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

    all_true = []
    all_pred = []
    all_prob = []


    with torch.no_grad():

        for X, y in loader:

            X = X.to(
                device
            )


            logits = model(
                X
            )


            prob = torch.softmax(
                logits,
                dim=1,
            )


            pred = prob.argmax(
                dim=1
            )


            all_true.append(
                y.numpy()
            )


            all_pred.append(
                pred
                .cpu()
                .numpy()
            )


            all_prob.append(
                prob
                .cpu()
                .numpy()
            )


    return (
        np.concatenate(
            all_true
        ),

        np.concatenate(
            all_pred
        ),

        np.concatenate(
            all_prob
        ),
    )


def save_confusion_matrix(
    y_true,
    y_pred,
    path,
):

    cm = confusion_matrix(
        y_true,
        y_pred,
        labels=[
            0,
            1,
            2,
        ],
    )


    df = pd.DataFrame(
        cm,

        index=[
            f"true_{x}"
            for x
            in LABEL_NAMES
        ],

        columns=[
            f"pred_{x}"
            for x
            in LABEL_NAMES
        ],
    )


    df.to_csv(
        path
    )


    return cm


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
                "train_class_weights"
            ][
                str(i)
            ]

            for i
            in range(
                NUM_CLASSES
            )
        ],

        dtype=np.float32,
    )


    print(
        "=" * 90
    )

    print(
        "GRU BASELINE TRAINING"
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
        HIDDEN_SIZE,
    )

    print(
        "layers     :",
        NUM_LAYERS,
    )

    print(
        "dropout    :",
        DROPOUT,
    )

    print(
        "class w    :",
        class_weights,
    )


    device = get_device()


    print(
        "device     :",
        device,
    )


    print()
    print(
        "Loading train..."
    )


    X_train, y_train = (
        load_npz(
            DATA_ROOT
            / "train.npz"
        )
    )


    print(
        "train:",
        X_train.shape,
        y_train.shape,
    )


    print(
        "Loading val..."
    )


    X_val, y_val = (
        load_npz(
            DATA_ROOT
            / "val.npz"
        )
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
            BATCH_SIZE,
            shuffle=True,
        )
    )


    val_loader = (
        make_loader(
            X_val,
            y_val,
            BATCH_SIZE,
            shuffle=False,
        )
    )


    model = FallGRU(

        input_size=
            input_size,

        hidden_size=
            HIDDEN_SIZE,

        num_layers=
            NUM_LAYERS,

        dropout=
            DROPOUT,

        num_classes=
            NUM_CLASSES,

    ).to(
        device
    )


    weight_tensor = (
        torch.tensor(
            class_weights,
            dtype=torch.float32,
            device=device,
        )
    )


    criterion = (
        nn.CrossEntropyLoss(
            weight=
                weight_tensor
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


    checkpoint_path = (
        RUN_ROOT
        / "best.pt"
    )


    history = []

    best_f1 = -1.0

    best_epoch = 0

    no_improve = 0


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
                optimizer=
                    optimizer,
            )
        )


        val_metrics = (
            run_epoch(
                model,
                val_loader,
                criterion,
                device,
                optimizer=None,
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


        lr = (
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
                lr,

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


        print(
            f"Epoch "
            f"{epoch:02d}/"
            f"{EPOCHS:02d} "
            f"lr={lr:.2e} "
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


        pd.DataFrame(
            history
        ).to_csv(
            RUN_ROOT
            / "history.csv",
            index=False,
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

                    "label_names":
                        LABEL_NAMES,

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
                f"  BEST -> "
                f"{checkpoint_path}"
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


    total_train_sec = (
        time.perf_counter()
        - train_start
    )


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
        f"{total_train_sec / 60:.1f} min",
    )


    checkpoint = torch.load(
        checkpoint_path,
        map_location=device,
        weights_only=False,
    )


    model.load_state_dict(
        checkpoint[
            "model_state"
        ]
    )


    # -------------------------------------------------
    # Test는 best validation model 확정 후
    # 마지막에 딱 한 번만 사용
    # -------------------------------------------------

    print()
    print(
        "Loading untouched test set..."
    )


    X_test, y_test = (
        load_npz(
            DATA_ROOT
            / "test.npz"
        )
    )


    print(
        "test :",
        X_test.shape,
        y_test.shape,
    )


    test_loader = (
        make_loader(
            X_test,
            y_test,
            BATCH_SIZE,
            shuffle=False,
        )
    )


    (
        y_true,
        y_pred,
        prob,
    ) = predict(
        model,
        test_loader,
        device,
    )


    test_accuracy = float(
        accuracy_score(
            y_true,
            y_pred,
        )
    )


    test_balanced_accuracy = float(
        balanced_accuracy_score(
            y_true,
            y_pred,
        )
    )


    test_macro_f1 = float(
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
                LABEL_NAMES,

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
                LABEL_NAMES,

            output_dict=True,

            zero_division=0,
        )
    )


    cm = (
        save_confusion_matrix(
            y_true,
            y_pred,

            RUN_ROOT
            / "test_confusion_matrix.csv",
        )
    )


    meta_path = (
        DATA_ROOT
        / "test_meta.csv.gz"
    )


    meta = pd.read_csv(
        meta_path
    )


    if len(meta) != len(
        y_true
    ):

        raise RuntimeError(
            "test_meta "
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
        LABEL_NAMES
    ):

        pred_df[
            f"prob_{name}"
        ] = prob[
            :,
            i,
        ]


    pred_df.to_csv(
        RUN_ROOT
        / "test_predictions.csv.gz",

        index=False,

        compression="gzip",
    )


    metrics = {

        "best_epoch":
            int(
                best_epoch
            ),

        "best_val_macro_f1":
            float(
                best_f1
            ),

        "test_accuracy":
            test_accuracy,

        "test_balanced_accuracy":
            test_balanced_accuracy,

        "test_macro_f1":
            test_macro_f1,

        "classification_report":
            report_dict,

        "confusion_matrix":
            cm.tolist(),

        "config":
            {

                "seed":
                    SEED,

                "batch_size":
                    BATCH_SIZE,

                "epochs_max":
                    EPOCHS,

                "learning_rate":
                    LEARNING_RATE,

                "weight_decay":
                    WEIGHT_DECAY,

                "hidden_size":
                    HIDDEN_SIZE,

                "num_layers":
                    NUM_LAYERS,

                "dropout":
                    DROPOUT,

                "patience":
                    PATIENCE,

                "grad_clip":
                    GRAD_CLIP,
            },
    }


    with (
        RUN_ROOT
        / "metrics.json"
    ).open(
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            metrics,
            f,
            ensure_ascii=False,
            indent=2,
        )


    print()
    print(
        "=" * 90
    )

    print(
        "TEST RESULT"
    )

    print(
        "=" * 90
    )


    print(
        "accuracy         :",
        f"{test_accuracy:.6f}",
    )


    print(
        "balanced accuracy:",
        f"{test_balanced_accuracy:.6f}",
    )


    print(
        "macro F1         :",
        f"{test_macro_f1:.6f}",
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
        "saved:",
        RUN_ROOT
    )


if __name__ == "__main__":

    main()
