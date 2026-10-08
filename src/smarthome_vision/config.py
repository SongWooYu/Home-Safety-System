from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml


ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        return ENV_PATTERN.sub(lambda match: os.getenv(match.group(1), ""), value)
    if isinstance(value, list):
        return [_expand(item) for item in value]
    if isinstance(value, dict):
        return {key: _expand(item) for key, item in value.items()}
    return value


def load_config(path: str | Path) -> dict[str, Any]:
    config_path = Path(path).resolve()
    project_root = config_path.parent.parent
    _load_dotenv(project_root / ".env")

    data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    data = _expand(data)
    data["project_root"] = str(project_root)

    model_path = Path(data["inference"]["model"])
    if not model_path.is_absolute():
        data["inference"]["model"] = str(project_root / model_path)
    fall_config = data.get("fall_detection", {})
    if fall_config.get("enabled", False):
        pose_model_path = Path(fall_config["model"])
        if not pose_model_path.is_absolute():
            fall_config["model"] = str(project_root / pose_model_path)

        temporal_config = fall_config.get(
            "temporal",
            {},
        )

        if temporal_config.get(
            "enabled",
            False,
        ):
            temporal_model_path = Path(
                temporal_config[
                    "model"
                ]
            )

            if not temporal_model_path.is_absolute():
                temporal_config[
                    "model"
                ] = str(
                    project_root
                    / temporal_model_path
                )

            observation_log = temporal_config.get(
                "observation_log",
                {},
            )
            if observation_log.get("path"):
                log_path = Path(observation_log["path"])
                if not log_path.is_absolute():
                    observation_log["path"] = str(project_root / log_path)

    face_config = data.get("face_recognition", {})
    if face_config.get("enabled", False):
        for key in ("detector_model", "recognizer_model", "database"):
            value_path = Path(face_config[key])
            if not value_path.is_absolute():
                face_config[key] = str(project_root / value_path)
    return data

