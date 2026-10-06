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
    average_precision_score,
    balanced_accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from torch.utils.data import (
    DataLoader,
    TensorDataset,
)


DATA_ROOT = Path(
    "data/gru_dataset/v2_actor_disjoint_20f_dynamic"
)

RUN_ROOT = Path(
    "runs/gru_binary_v2"
)

INFO_PATH = (
    DATA_ROOT
    / "dataset_info.json"
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


def load_npz(split):

    path = (
        DATA_ROOT
        / f"{split}.npz"
    )

    with np.load(path) as d:

        X = np.asarray(
            d["X"],
            dtype=np.float32,
        )

        y3 = np.asarray(
            d["y"],
            dtype=np.int64,
        )

    if (
        X.ndim != 3
        or len(X) != len(y3)
    ):
        raise RuntimeError(
            f"Bad dataset: {path}"
        )

    if not np.isfinite(
        X
    ).all():

        raise RuntimeError(
            f"Non-finite X: {path}"
        )

    # ---------------------------------------------
    # Binary target
    #
    # 0 normal  -> 0
    # 1 falling -> 1
    # 2 fallen  -> 1
    # ---------------------------------------------

    y = (
        y3 != 0
    ).astype(
        np.float32
    )

    return (
        X,
        y,
        y3,
    )


def make_loader(
    X,
    y,
    shuffle,
):

    ds = TensorDataset(
        torch.from_numpy(X),
        torch.from_numpy(y),
    )

    return DataLoader(
        ds,
        batch_size=BATCH_SIZE,
        shuffle=shuffle,
        num_workers=0,
        drop_last=False,
    )


class AlertGRU(nn.Module):

    def __init__(
        self,
        input_size,
    ):

        super().__init__()

        self.input_norm = nn.LayerNorm(
            input_size
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
                1,
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

        logits = self.head(
            h[-1]
        ).squeeze(
            1
        )

        return logits


def calculate_metrics(
    y_true,
    prob,
    threshold=0.5,
):

    pred = (
        prob >= threshold
    ).astype(
        np.int64
    )

    y_true_int = (
        y_true.astype(
            np.int64
        )
    )

    return {

        "accuracy":
            accuracy_score(
                y_true_int,
                pred,
            ),

        "balanced_accuracy":
            balanced_accuracy_score(
                y_true_int,
                pred,
            ),

        "precision":
            precision_score(
                y_true_int,
                pred,
                zero_division=0,
            ),

        "recall":
            recall_score(
                y_true_int,
                pred,
                zero_division=0,
            ),

        "f1":
            f1_score(
                y_true_int,
                pred,
                zero_division=0,
            ),

        "average_precision":
            average_precision_score(
                y_true_int,
                prob,
            ),

        "roc_auc":
            roc_auc_score(
                y_true_int,
                prob,
            ),
    }


def run_train_epoch(
    model,
    loader,
    criterion,
    optimizer,
    device,
):

    model.train()

    total_loss = 0.0

    total_n = 0

    all_true = []

    all_prob = []


    for xb, yb in loader:

        xb = xb.to(
            device
        )

        yb = yb.to(
            device
        )

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


        prob = torch.sigmoid(
            logits
        )


        all_true.append(
            yb
            .detach()
            .cpu()
            .numpy()
        )

        all_prob.append(
            prob
            .detach()
            .cpu()
            .numpy()
        )


    y_true = np.concatenate(
        all_true
    )

    prob = np.concatenate(
        all_prob
    )


    metrics = calculate_metrics(
        y_true,
        prob,
    )

    metrics[
        "loss"
    ] = (
        total_loss
        / total_n
    )

    return metrics


def evaluate(
    model,
    loader,
    criterion,
    device,
):

    model.eval()

    total_loss = 0.0

    total_n = 0

    all_true = []

    all_prob = []


    with torch.no_grad():

        for xb, yb in loader:

            xb = xb.to(
                device
            )

            yb = yb.to(
                device
            )

            logits = model(
                xb
            )

            loss = criterion(
                logits,
                yb,
            )

            prob = torch.sigmoid(
                logits
            )


            n = yb.size(
                0
            )

            total_loss += (
                loss.item()
                * n
            )

            total_n += n


            all_true.append(
                yb
                .cpu()
                .numpy()
            )

            all_prob.append(
                prob
                .cpu()
                .numpy()
            )


    y_true = np.concatenate(
        all_true
    )

    prob = np.concatenate(
        all_prob
    )


    metrics = calculate_metrics(
        y_true,
        prob,
    )

    metrics[
        "loss"
    ] = (
        total_loss
        / total_n
    )


    return (
        metrics,
        y_true,
        prob,
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


    device = get_device()


    print(
        "=" * 90
    )

    print(
        "BINARY ALERT GRU"
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
        "hidden     :",
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
        "class w    : NONE"
    )

    print(
        "device     :",
        device,
    )


    (
        X_train,
        y_train,
        y3_train,
    ) = load_npz(
        "train"
    )


    (
        X_val,
        y_val,
        y3_val,
    ) = load_npz(
        "val"
    )


    print()
    print(
        "train:",
        X_train.shape,
    )

    print(
        "normal:",
        int(
            np.sum(
                y_train == 0
            )
        ),
    )

    print(
        "alert :",
        int(
            np.sum(
                y_train == 1
            )
        ),
    )


    print()
    print(
        "val:",
        X_val.shape,
    )

    print(
        "normal:",
        int(
            np.sum(
                y_val == 0
            )
        ),
    )

    print(
        "alert :",
        int(
            np.sum(
                y_val == 1
            )
        ),
    )


    train_loader = make_loader(
        X_train,
        y_train,
        True,
    )

    val_loader = make_loader(
        X_val,
        y_val,
        False,
    )


    model = AlertGRU(
        input_size
    ).to(
        device
    )


    # 클래스가 거의 50:50이므로
    # pos_weight를 사용하지 않는다.

    criterion = (
        nn.BCEWithLogitsLoss()
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

    best_ap = -1.0

    best_epoch = 0

    no_improve = 0

    total_start = (
        time.perf_counter()
    )


    for epoch in range(
        1,
        EPOCHS + 1,
    ):

        start = (
            time.perf_counter()
        )


        train_metrics = (
            run_train_epoch(

                model,
                train_loader,
                criterion,
                optimizer,
                device,
            )
        )


        (
            val_metrics,
            _,
            _,
        ) = evaluate(

            model,
            val_loader,
            criterion,
            device,
        )


        val_ap = float(
            val_metrics[
                "average_precision"
            ]
        )


        scheduler.step(
            val_ap
        )


        lr = (
            optimizer
            .param_groups[0][
                "lr"
            ]
        )


        elapsed = (
            time.perf_counter()
            - start
        )


        row = {

            "epoch":
                epoch,

            "lr":
                lr,

            **{
                f"train_{k}":
                    v

                for k, v
                in train_metrics.items()
            },

            **{
                f"val_{k}":
                    v

                for k, v
                in val_metrics.items()
            },

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
            f"{lr:.2e} "

            f"train_loss="
            f"{train_metrics['loss']:.4f} "

            f"train_f1="
            f"{train_metrics['f1']:.4f} "

            f"val_loss="
            f"{val_metrics['loss']:.4f} "

            f"val_precision="
            f"{val_metrics['precision']:.4f} "

            f"val_recall="
            f"{val_metrics['recall']:.4f} "

            f"val_f1="
            f"{val_metrics['f1']:.4f} "

            f"val_AP="
            f"{val_ap:.4f} "

            f"time="
            f"{elapsed:.1f}s"
        )


        if (
            val_ap
            > best_ap
            + 1e-5
        ):

            best_ap = (
                val_ap
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

                    "val_average_precision":
                        best_ap,

                    "input_size":
                        input_size,

                    "hidden_size":
                        HIDDEN_SIZE,

                    "num_layers":
                        NUM_LAYERS,

                    "dropout":
                        DROPOUT,

                    "sequence_length":
                        info[
                            "sequence_length"
                        ],

                    "feature_names":
                        info[
                            "feature_names"
                        ],

                    "target":
                        "binary_alert",

                    "label_definition":
                        {
                            "0":
                                "normal",

                            "1":
                                "falling_or_fallen",
                        },
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
                "without AP improvement"
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
        "BEST BINARY MODEL"
    )

    print(
        "=" * 90
    )

    print(
        "best epoch:",
        best_epoch,
    )

    print(
        "best val AP:",
        f"{best_ap:.6f}",
    )

    print(
        "training time:",
        f"{(time.perf_counter() - total_start) / 60:.1f} min",
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


    (
        metrics,
        y_true,
        prob,
    ) = evaluate(

        model,
        val_loader,
        criterion,
        device,
    )


    pred = (
        prob >= 0.5
    ).astype(
        np.int64
    )


    print()
    print(
        "=" * 90
    )

    print(
        "VALIDATION @ THRESHOLD 0.5"
    )

    print(
        "=" * 90
    )


    for key in [
        "accuracy",
        "balanced_accuracy",
        "precision",
        "recall",
        "f1",
        "average_precision",
        "roc_auc",
    ]:

        print(
            f"{key:20s}: "
            f"{metrics[key]:.6f}"
        )


    print()

    print(
        classification_report(

            y_true.astype(
                np.int64
            ),

            pred,

            labels=[
                0,
                1,
            ],

            target_names=[
                "normal",
                "alert",
            ],

            digits=4,

            zero_division=0,
        )
    )


    cm = confusion_matrix(

        y_true.astype(
            np.int64
        ),

        pred,

        labels=[
            0,
            1,
        ],
    )


    print(
        "confusion matrix:"
    )

    print(
        cm
    )


    meta = pd.read_csv(
        DATA_ROOT
        / "val_meta.csv.gz"
    )


    if len(meta) != len(
        prob
    ):

        raise RuntimeError(
            "val_meta length mismatch"
        )


    out = meta.copy()

    out[
        "y_binary"
    ] = (
        y_true.astype(
            np.int64
        )
    )

    out[
        "prob_alert"
    ] = prob

    out[
        "pred_alert_0p5"
    ] = pred


    out.to_csv(

        RUN_ROOT
        / "val_predictions.csv.gz",

        index=False,

        compression="gzip",
    )


    metrics_out = {
        key:
            float(value)

        for key, value
        in metrics.items()
    }


    metrics_out[
        "best_epoch"
    ] = int(
        best_epoch
    )


    metrics_out[
        "best_val_average_precision"
    ] = float(
        best_ap
    )


    metrics_out[
        "confusion_matrix"
    ] = cm.tolist()


    with (
        RUN_ROOT
        / "metrics.json"
    ).open(
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            metrics_out,
            f,
            ensure_ascii=False,
            indent=2,
        )


    print()
    print(
        "NOTE: TEST SET WAS NOT LOADED."
    )

    print(
        "saved:",
        RUN_ROOT,
    )


if __name__ == "__main__":

    main()
