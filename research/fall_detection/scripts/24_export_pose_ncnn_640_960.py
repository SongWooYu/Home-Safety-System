from pathlib import Path
import shutil

import yaml
from ultralytics import YOLO


ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)

MODEL = (
    ROOT
    / "models"
    / "yolo11n-pose.pt"
)

SIZES = (
    640,
    960,
)


def export_one(size: int):

    print()
    print("=" * 72)
    print(
        f"EXPORT YOLO11n-Pose "
        f"NCNN imgsz={size}"
    )
    print("=" * 72)

    if not MODEL.exists():
        raise FileNotFoundError(
            MODEL
        )

    model = YOLO(
        str(MODEL)
    )

    exported = Path(
        model.export(
            format="ncnn",
            imgsz=size,
            batch=1,
            half=False,
            device="cpu",
        )
    ).resolve()

    if not exported.exists():
        raise RuntimeError(
            f"Export directory "
            f"not found: {exported}"
        )

    dest = (
        ROOT
        / "models"
        / (
            f"yolo11n-pose_"
            f"{size}_ncnn_model"
        )
    )

    if dest.exists():
        shutil.rmtree(
            dest
        )

    shutil.move(
        str(exported),
        str(dest),
    )

    metadata_path = (
        dest
        / "metadata.yaml"
    )

    metadata = yaml.safe_load(
        metadata_path.read_text(
            encoding="utf-8"
        )
    )

    imgsz = metadata.get(
        "imgsz"
    )

    print(
        "source model :",
        MODEL
    )

    print(
        "saved        :",
        dest
    )

    print(
        "metadata imgsz:",
        imgsz
    )

    if imgsz != [
        size,
        size,
    ]:
        raise RuntimeError(
            "Unexpected metadata "
            f"imgsz={imgsz}"
        )

    required = (
        "model.ncnn.param",
        "model.ncnn.bin",
        "metadata.yaml",
    )

    for name in required:

        path = (
            dest
            / name
        )

        if not path.exists():
            raise RuntimeError(
                f"Missing export file: "
                f"{path}"
            )

    print(
        "export OK"
    )


def main():

    print(
        "ROOT :",
        ROOT
    )

    print(
        "MODEL:",
        MODEL
    )

    for size in SIZES:
        export_one(
            size
        )

    print()
    print("=" * 72)
    print("ALL EXPORTS COMPLETE")
    print("=" * 72)


if __name__ == "__main__":
    main()
