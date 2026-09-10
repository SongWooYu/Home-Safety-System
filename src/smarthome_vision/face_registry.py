from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np


class FaceRegistryError(ValueError):
    pass


class FaceRegistry:
    """Local YuNet + SFace registry that stores embeddings, not face photos."""

    def __init__(
        self,
        detector_model: str,
        recognizer_model: str,
        database_path: str,
        match_threshold: float = 0.45,
        detection_width: int = 640,
        min_face_size: int = 70,
    ):
        detector_path = Path(detector_model)
        recognizer_path = Path(recognizer_model)
        if not detector_path.exists() or not recognizer_path.exists():
            raise FileNotFoundError("YuNet/SFace model files are not installed")

        self.database_path = Path(database_path)
        self.match_threshold = match_threshold
        self.detection_width = max(160, detection_width)
        self.min_face_size = max(30, min_face_size)
        self._lock = threading.RLock()
        self._detector = cv2.FaceDetectorYN_create(
            str(detector_path),
            "",
            (320, 320),
            0.8,
            0.3,
            100,
        )
        self._recognizer = cv2.FaceRecognizerSF_create(str(recognizer_path), "")
        self._people: list[dict] = []
        self._load()

    def list_people(self) -> list[dict]:
        with self._lock:
            return [
                {
                    "id": person["id"],
                    "name": person["name"],
                    "updated_at": person["updated_at"],
                }
                for person in self._people
            ]

    def enroll(self, name: str, frames: list[np.ndarray]) -> dict:
        clean_name = " ".join(str(name).split())
        if not clean_name or len(clean_name) > 40 or any(ord(char) < 32 for char in clean_name):
            raise FaceRegistryError("이름은 1~40자로 입력하세요.")

        features: list[np.ndarray] = []
        with self._lock:
            for frame in frames:
                faces = self._detect(frame)
                if len(faces) != 1:
                    continue
                feature = self._feature(frame, faces[0])
                if feature is not None:
                    features.append(feature)

            if len(features) < 3:
                raise FaceRegistryError(
                    "한 명의 얼굴을 충분히 찾지 못했습니다. 카메라를 정면으로 보고 다시 등록하세요."
                )

            embedding = np.mean(np.stack(features), axis=0)
            embedding /= max(float(np.linalg.norm(embedding)), 1e-8)
            now = datetime.now(timezone.utc).isoformat()
            existing = next(
                (person for person in self._people if person["name"].casefold() == clean_name.casefold()),
                None,
            )
            if existing is None:
                existing = {
                    "id": uuid.uuid4().hex[:12],
                    "name": clean_name,
                    "embedding": embedding.astype(float).tolist(),
                    "updated_at": now,
                }
                self._people.append(existing)
            else:
                existing["name"] = clean_name
                existing["embedding"] = embedding.astype(float).tolist()
                existing["updated_at"] = now
            self._save()
            return {
                "id": existing["id"],
                "name": existing["name"],
                "updated_at": existing["updated_at"],
                "samples": len(features),
            }

    def delete(self, person_id: str) -> bool:
        with self._lock:
            original_count = len(self._people)
            self._people = [person for person in self._people if person["id"] != person_id]
            if len(self._people) == original_count:
                return False
            self._save()
            return True

    def identify(self, frame: np.ndarray) -> list[dict]:
        with self._lock:
            faces = self._detect(frame)
            people = [
                (
                    person,
                    np.asarray(person["embedding"], dtype=np.float32),
                )
                for person in self._people
            ]
            results: list[dict] = []
            for face in faces[:5]:
                feature = self._feature(frame, face)
                if feature is None:
                    continue
                best_person = None
                best_score = -1.0
                for person, embedding in people:
                    score = float(np.dot(feature, embedding))
                    if score > best_score:
                        best_score = score
                        best_person = person
                registered = best_person is not None and best_score >= self.match_threshold
                x, y, width, height = (int(round(value)) for value in face[:4])
                results.append(
                    {
                        "box": [x, y, x + width, y + height],
                        "name": best_person["name"] if registered else "미등록",
                        "registered": registered,
                        "similarity": round(max(0.0, best_score), 3),
                    }
                )
            return results

    def _detect(self, frame: np.ndarray) -> list[np.ndarray]:
        height, width = frame.shape[:2]
        scale = min(1.0, self.detection_width / max(1, width))
        if scale < 1.0:
            resized = cv2.resize(
                frame,
                (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
                interpolation=cv2.INTER_AREA,
            )
        else:
            resized = frame
        resized_height, resized_width = resized.shape[:2]
        self._detector.setInputSize((resized_width, resized_height))
        _, detected = self._detector.detect(resized)
        if detected is None:
            return []

        scale_x = width / resized_width
        scale_y = height / resized_height
        faces: list[np.ndarray] = []
        for raw_face in detected:
            face = raw_face.astype(np.float32).copy()
            face[[0, 2, 4, 6, 8, 10, 12]] *= scale_x
            face[[1, 3, 5, 7, 9, 11, 13]] *= scale_y
            if face[2] < self.min_face_size or face[3] < self.min_face_size:
                continue
            faces.append(face)
        faces.sort(key=lambda face: float(face[2] * face[3]), reverse=True)
        return faces

    def _feature(self, frame: np.ndarray, face: np.ndarray) -> np.ndarray | None:
        try:
            aligned = self._recognizer.alignCrop(frame, face)
            feature = self._recognizer.feature(aligned).reshape(-1).astype(np.float32)
        except cv2.error:
            return None
        norm = float(np.linalg.norm(feature))
        if norm <= 1e-8:
            return None
        return feature / norm

    def _load(self) -> None:
        if not self.database_path.exists():
            return
        try:
            payload = json.loads(self.database_path.read_text(encoding="utf-8"))
            people = payload.get("people", [])
            self._people = [
                person
                for person in people
                if {"id", "name", "embedding", "updated_at"} <= set(person)
            ]
        except (OSError, ValueError, TypeError):
            self._people = []

    def _save(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "people": self._people}
        temporary = self.database_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(self.database_path)
