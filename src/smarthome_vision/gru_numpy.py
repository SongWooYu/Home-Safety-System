from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np


LN_EPS = np.float32(1e-5)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(
            lambda: handle.read(1024 * 1024),
            b"",
        ):
            digest.update(block)

    return digest.hexdigest()


def _layer_norm(
    x: np.ndarray,
    weight: np.ndarray,
    bias: np.ndarray,
) -> np.ndarray:

    x = np.asarray(
        x,
        dtype=np.float32,
    )

    mean = np.mean(
        x,
        axis=-1,
        keepdims=True,
        dtype=np.float32,
    )

    centered = (
        x - mean
    ).astype(
        np.float32,
        copy=False,
    )

    variance = np.mean(
        centered * centered,
        axis=-1,
        keepdims=True,
        dtype=np.float32,
    )

    normalized = (
        centered
        / np.sqrt(
            variance + LN_EPS
        )
    )

    return (
        normalized
        * weight
        + bias
    ).astype(
        np.float32,
        copy=False,
    )


def _sigmoid(
    x: np.ndarray,
) -> np.ndarray:

    return (
        np.float32(1.0)
        /
        (
            np.float32(1.0)
            + np.exp(-x)
        )
    ).astype(
        np.float32,
        copy=False,
    )


def _softmax(
    logits: np.ndarray,
) -> np.ndarray:

    logits = np.asarray(
        logits,
        dtype=np.float32,
    )

    shifted = (
        logits
        - np.max(logits)
    )

    exp = np.exp(
        shifted
    ).astype(
        np.float32,
        copy=False,
    )

    return (
        exp
        / np.sum(
            exp,
            dtype=np.float32,
        )
    ).astype(
        np.float32,
        copy=False,
    )


def _softmax_batch(
    logits: np.ndarray,
) -> np.ndarray:
    logits = np.asarray(
        logits,
        dtype=np.float32,
    )
    shifted = logits - np.max(
        logits,
        axis=-1,
        keepdims=True,
    )
    exp = np.exp(shifted).astype(
        np.float32,
        copy=False,
    )
    return (
        exp
        / np.sum(
            exp,
            axis=-1,
            keepdims=True,
            dtype=np.float32,
        )
    ).astype(
        np.float32,
        copy=False,
    )

class NumpyFallGRU:
    def __init__(
        self,
        path: str | Path,
    ):
        self.path = Path(path)

        with np.load(
            self.path,
            allow_pickle=False,
        ) as data:

            self.w = {
                key:
                    np.asarray(
                        data[key],
                        dtype=np.float32,
                    )
                for key in data.files
            }

        self.hidden_size = 128
        self.feature_dim = 76

    def _gru_layer(
        self,
        sequence: np.ndarray,
        layer: int,
    ) -> tuple[
        np.ndarray,
        np.ndarray,
    ]:

        w_ih = self.w[
            f"gru__weight_ih_l{layer}"
        ]

        w_hh = self.w[
            f"gru__weight_hh_l{layer}"
        ]

        b_ih = self.w[
            f"gru__bias_ih_l{layer}"
        ]

        b_hh = self.w[
            f"gru__bias_hh_l{layer}"
        ]

        h = np.zeros(
            self.hidden_size,
            dtype=np.float32,
        )

        outputs = np.empty(
            (
                sequence.shape[0],
                self.hidden_size,
            ),
            dtype=np.float32,
        )

        for index, x in enumerate(
            sequence
        ):

            gi = (
                w_ih @ x
                + b_ih
            ).astype(
                np.float32,
                copy=False,
            )

            gh = (
                w_hh @ h
                + b_hh
            ).astype(
                np.float32,
                copy=False,
            )

            i_r, i_z, i_n = np.split(
                gi,
                3,
            )

            h_r, h_z, h_n = np.split(
                gh,
                3,
            )

            r = _sigmoid(
                i_r + h_r
            )

            z = _sigmoid(
                i_z + h_z
            )

            n = np.tanh(
                i_n
                + r * h_n
            ).astype(
                np.float32,
                copy=False,
            )

            h = (
                (
                    np.float32(1.0)
                    - z
                )
                * n
                + z * h
            ).astype(
                np.float32,
                copy=False,
            )

            outputs[
                index
            ] = h

        return (
            outputs,
            h,
        )

    def logits(
        self,
        sequence: np.ndarray,
    ) -> np.ndarray:

        x = np.asarray(
            sequence,
            dtype=np.float32,
        )

        if x.shape != (
            20,
            self.feature_dim,
        ):
            raise ValueError(
                "Expected sequence "
                f"(20, 76), got "
                f"{x.shape}"
            )

        x = _layer_norm(
            x,
            self.w[
                "input_norm__weight"
            ],
            self.w[
                "input_norm__bias"
            ],
        )

        x, _ = self._gru_layer(
            x,
            0,
        )

        _, h = self._gru_layer(
            x,
            1,
        )

        h = _layer_norm(
            h,
            self.w[
                "head__0__weight"
            ],
            self.w[
                "head__0__bias"
            ],
        )

        h = (
            self.w[
                "head__2__weight"
            ]
            @ h
            + self.w[
                "head__2__bias"
            ]
        ).astype(
            np.float32,
            copy=False,
        )

        h = np.maximum(
            h,
            np.float32(0.0),
        )

        return (
            self.w[
                "head__5__weight"
            ]
            @ h
            + self.w[
                "head__5__bias"
            ]
        ).astype(
            np.float32,
            copy=False,
        )

    def probabilities(
        self,
        sequence: np.ndarray,
    ) -> np.ndarray:

        return _softmax(
            self.logits(
                sequence
            )
        )

    def _gru_layer_batch(
        self,
        sequences: np.ndarray,
        layer: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        w_ih = self.w[f"gru__weight_ih_l{layer}"]
        w_hh = self.w[f"gru__weight_hh_l{layer}"]
        b_ih = self.w[f"gru__bias_ih_l{layer}"]
        b_hh = self.w[f"gru__bias_hh_l{layer}"]

        batch_size, sequence_length, _ = sequences.shape
        h = np.zeros(
            (batch_size, self.hidden_size),
            dtype=np.float32,
        )
        outputs = np.empty(
            (batch_size, sequence_length, self.hidden_size),
            dtype=np.float32,
        )

        for index in range(sequence_length):
            gi = (
                sequences[:, index, :] @ w_ih.T
                + b_ih
            ).astype(np.float32, copy=False)
            gh = (
                h @ w_hh.T
                + b_hh
            ).astype(np.float32, copy=False)

            i_r, i_z, i_n = np.split(gi, 3, axis=1)
            h_r, h_z, h_n = np.split(gh, 3, axis=1)
            r = _sigmoid(i_r + h_r)
            z = _sigmoid(i_z + h_z)
            n = np.tanh(i_n + r * h_n).astype(
                np.float32,
                copy=False,
            )
            h = (
                (np.float32(1.0) - z) * n
                + z * h
            ).astype(np.float32, copy=False)
            outputs[:, index, :] = h

        return outputs, h

    def logits_batch(
        self,
        sequences: np.ndarray,
    ) -> np.ndarray:
        x = np.asarray(sequences, dtype=np.float32)
        if x.ndim != 3 or x.shape[1:] != (20, self.feature_dim):
            raise ValueError(
                "Expected sequences (N, 20, 76), got "
                f"{x.shape}"
            )

        x = _layer_norm(
            x,
            self.w["input_norm__weight"],
            self.w["input_norm__bias"],
        )
        x, _ = self._gru_layer_batch(x, 0)
        _, h = self._gru_layer_batch(x, 1)
        h = _layer_norm(
            h,
            self.w["head__0__weight"],
            self.w["head__0__bias"],
        )
        h = (
            h @ self.w["head__2__weight"].T
            + self.w["head__2__bias"]
        ).astype(np.float32, copy=False)
        h = np.maximum(h, np.float32(0.0))
        return (
            h @ self.w["head__5__weight"].T
            + self.w["head__5__bias"]
        ).astype(np.float32, copy=False)

    def probabilities_batch(
        self,
        sequences: np.ndarray,
    ) -> np.ndarray:
        return _softmax_batch(
            self.logits_batch(sequences)
        )


class NumpyFallEnsemble:
    def __init__(
        self,
        directory: str | Path,
        verify_sha256: bool = True,
    ):
        self.directory = Path(
            directory
        )

        manifest_path = (
            self.directory
            / "manifest.json"
        )

        self.manifest = json.loads(
            manifest_path.read_text(
                encoding="utf-8"
            )
        )

        self.classes = list(
            self.manifest[
                "classes"
            ]
        )

        self.members: list[
            tuple[
                str,
                NumpyFallGRU,
            ]
        ] = []

        for seed in sorted(
            self.manifest[
                "members"
            ],
            key=int,
        ):

            info = self.manifest[
                "members"
            ][seed]

            path = (
                self.directory
                / info["file"]
            )

            if verify_sha256:

                actual = _sha256(
                    path
                )

                expected = info[
                    "sha256"
                ]

                if actual != expected:
                    raise RuntimeError(
                        "SHA256 mismatch: "
                        f"{path}"
                    )

            self.members.append(
                (
                    seed,
                    NumpyFallGRU(
                        path
                    ),
                )
            )

    def predict(
        self,
        sequence: np.ndarray,
    ) -> dict:

        member_probs = []

        for seed, model in (
            self.members
        ):

            member_probs.append(
                (
                    seed,
                    model.probabilities(
                        sequence
                    ),
                )
            )

        stacked = np.stack(
            [
                probs
                for _, probs
                in member_probs
            ],
            axis=0,
        )

        mean_prob = np.mean(
            stacked,
            axis=0,
            dtype=np.float32,
        )

        class_id = int(
            np.argmax(
                mean_prob
            )
        )

        return {
            "class_id":
                class_id,

            "class_name":
                self.classes[
                    class_id
                ],

            "probabilities":
                {
                    name:
                        float(
                            mean_prob[
                                index
                            ]
                        )
                    for index, name
                    in enumerate(
                        self.classes
                    )
                },

            "alert_score":
                float(
                    mean_prob[1]
                    + mean_prob[2]
                ),

            "members":
                {
                    seed: {
                        name:
                            float(
                                probs[
                                    index
                                ]
                            )
                        for index, name
                        in enumerate(
                            self.classes
                        )
                    }
                    for seed, probs
                    in member_probs
                },
        }

    def predict_batch(
        self,
        sequences: np.ndarray,
    ) -> list[dict]:
        sequences = np.asarray(
            sequences,
            dtype=np.float32,
        )
        if sequences.ndim != 3 or sequences.shape[1:] != (20, 76):
            raise ValueError(
                "Expected sequences (N, 20, 76), got "
                f"{sequences.shape}"
            )
        if sequences.shape[0] == 0:
            return []

        member_probs = [
            (seed, model.probabilities_batch(sequences))
            for seed, model in self.members
        ]
        mean_probs = np.mean(
            np.stack(
                [probabilities for _, probabilities in member_probs],
                axis=0,
            ),
            axis=0,
            dtype=np.float32,
        )

        results = []
        for batch_index, mean_prob in enumerate(mean_probs):
            class_id = int(np.argmax(mean_prob))
            results.append(
                {
                    "class_id": class_id,
                    "class_name": self.classes[class_id],
                    "probabilities": {
                        name: float(mean_prob[index])
                        for index, name in enumerate(self.classes)
                    },
                    "alert_score": float(mean_prob[1] + mean_prob[2]),
                    "members": {
                        seed: {
                            name: float(probabilities[batch_index, index])
                            for index, name in enumerate(self.classes)
                        }
                        for seed, probabilities in member_probs
                    },
                }
            )

        return results
