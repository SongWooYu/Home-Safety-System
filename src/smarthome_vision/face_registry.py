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

    VALID_VIEWS = {"front", "left", "right"}

    def __init__(
        self,
        detector_model: str,
        recognizer_model: str,
        database_path: str,
        match_threshold: float = 0.45,
        detection_width: int = 640,
        min_face_size: int = 70,
        enrollment_min_samples_per_view: int = 3,
        enrollment_yaw_threshold: float = 0.12,
        enrollment_max_yaw: float = 0.65,
        enrollment_min_sharpness: float = 35.0,
    ):
        detector_path = Path(detector_model)
        recognizer_path = Path(recognizer_model)
        if not detector_path.exists() or not recognizer_path.exists():
            raise FileNotFoundError("YuNet/SFace model files are not installed")

        self.database_path = Path(database_path)
        self.match_threshold = match_threshold
        self.detection_width = max(160, detection_width)
        self.min_face_size = max(30, min_face_size)
        self.enrollment_min_samples_per_view = max(
            2, int(enrollment_min_samples_per_view)
        )
        self.enrollment_yaw_threshold = max(
            0.05, float(enrollment_yaw_threshold)
        )
        self.enrollment_max_yaw = max(
            self.enrollment_yaw_threshold + 0.1,
            float(enrollment_max_yaw),
        )
        self.enrollment_min_sharpness = max(
            0.0, float(enrollment_min_sharpness)
        )
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
                    "views": [template["view"] for template in person["templates"]],
                }
                for person in self._people
            ]

    def enroll(self, name: str, frames: list[np.ndarray], view: str = "front") -> dict:
        clean_name = " ".join(str(name).split())
        clean_view = str(view).strip().lower()
        if not clean_name or len(clean_name) > 40 or any(ord(char) < 32 for char in clean_name):
            raise FaceRegistryError("이름은 1~40자로 입력하세요.")
        if clean_view not in self.VALID_VIEWS:
            raise FaceRegistryError("촬영 방향은 정면, 왼쪽, 오른쪽 중 하나여야 합니다.")

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
                    "한 명의 얼굴을 충분히 찾지 못했습니다. 얼굴 방향과 조명을 확인해 다시 등록하세요."
                )

            embedding = np.mean(np.stack(features), axis=0)
            embedding /= max(float(np.linalg.norm(embedding)), 1e-8)
            now = datetime.now(timezone.utc).isoformat()
            template = {
                "view": clean_view,
                "embedding": embedding.astype(float).tolist(),
                "updated_at": now,
            }
            existing = next(
                (person for person in self._people if person["name"].casefold() == clean_name.casefold()),
                None,
            )
            if existing is None:
                existing = {
                    "id": uuid.uuid4().hex[:12],
                    "name": clean_name,
                    "templates": [template],
                    "updated_at": now,
                }
                self._people.append(existing)
            else:
                existing["name"] = clean_name
                existing["templates"] = [
                    item for item in existing["templates"] if item["view"] != clean_view
                ]
                existing["templates"].append(template)
                existing["updated_at"] = now
                existing.pop("embedding", None)
            self._save()
            return {
                "id": existing["id"],
                "name": existing["name"],
                "updated_at": existing["updated_at"],
                "samples": len(features),
                "view": clean_view,
                "views": [item["view"] for item in existing["templates"]],
            }

    def enroll_multi_angle(self, name: str, frames: list[np.ndarray]) -> dict:
        """Enroll front and both yaw directions from one continuous capture.

        YuNet's five landmarks provide a lightweight yaw proxy. This is a
        guided multi-template enrollment, not a 3-D reconstruction or liveness
        proof. Only one clear face is accepted in each sampled frame.
        """
        clean_name = " ".join(str(name).split())
        if (
            not clean_name
            or len(clean_name) > 40
            or any(ord(char) < 32 for char in clean_name)
        ):
            raise FaceRegistryError("이름은 1~40자로 입력하세요.")

        samples: dict[str, list[np.ndarray]] = {
            "front": [],
            "left": [],
            "right": [],
        }
        rejected = {
            "face_count": 0,
            "blur": 0,
            "angle": 0,
            "feature": 0,
        }
        with self._lock:
            for frame in frames:
                faces = self._detect(frame)
                if len(faces) != 1:
                    rejected["face_count"] += 1
                    continue
                face = faces[0]
                yaw = self._face_yaw(face)
                if yaw is None or abs(yaw) > self.enrollment_max_yaw:
                    rejected["angle"] += 1
                    continue
                if self._face_sharpness(frame, face) < self.enrollment_min_sharpness:
                    rejected["blur"] += 1
                    continue
                feature = self._feature(frame, face)
                if feature is None:
                    rejected["feature"] += 1
                    continue
                if abs(yaw) < self.enrollment_yaw_threshold:
                    view = "front"
                elif yaw < 0:
                    view = "left"
                else:
                    view = "right"
                # Bound each mean so a long pause at one angle cannot dominate.
                if len(samples[view]) < 16:
                    samples[view].append(feature)

            missing = [
                view
                for view, features in samples.items()
                if len(features) < self.enrollment_min_samples_per_view
            ]
            if missing:
                labels = {"front": "정면", "left": "한쪽", "right": "반대쪽"}
                counts = ", ".join(
                    f"{labels[view]} {len(samples[view])}장"
                    for view in ("front", "left", "right")
                )
                raise FaceRegistryError(
                    "다각도 특징이 부족합니다. 얼굴을 화면 중앙에 두고 "
                    "정면에서 양쪽으로 천천히 돌려 주세요. " + counts
                )

            return self.save_guided_samples(clean_name, samples, rejected)

    def enrollment_observation(self, frame: np.ndarray) -> dict:
        """Inspect one current frame. Embeddings stay server-side only."""
        with self._lock:
            faces = self._detect(frame)
            if len(faces) != 1:
                return {"error": "한 사람의 얼굴 전체를 카메라 가까이 보여 주세요."}
            face = faces[0]
            x, y, width, height = face[:4]
            h, w = frame.shape[:2]
            if x < 0 or y < 0 or x + width > w or y + height > h:
                return {"error": "얼굴이 잘렸어요. 화면 안쪽으로 이동해 주세요."}
            yaw = self._face_yaw(face)
            if yaw is None or abs(yaw) > self.enrollment_max_yaw:
                return {"error": "너무 옆을 보고 있어요. 정면 쪽으로 조금 돌아와 주세요."}
            if self._face_sharpness(frame, face) < self.enrollment_min_sharpness:
                return {"error": "얼굴이 흐려요. 움직임을 멈추고 조명을 확인해 주세요."}
            feature = self._feature(frame, face)
            if feature is None:
                return {"error": "눈과 코가 잘 보이도록 얼굴을 보여 주세요."}
            view = "front" if abs(yaw) < self.enrollment_yaw_threshold else ("left" if yaw < 0 else "right")
            return {"view": view, "feature": feature}

    def save_guided_samples(self, clean_name: str, samples: dict, rejected=None) -> dict:
        """Commit all three views together; never persist a partial session."""
        if any(len(samples.get(view, [])) < self.enrollment_min_samples_per_view
               for view in self.VALID_VIEWS):
            raise FaceRegistryError("세 방향의 선명한 특징이 모두 필요합니다.")
        with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            templates = []
            for view in ("front", "left", "right"):
                embedding = np.mean(np.stack(samples[view]), axis=0)
                embedding /= max(float(np.linalg.norm(embedding)), 1e-8)
                templates.append(
                    {
                        "view": view,
                        "embedding": embedding.astype(float).tolist(),
                        "updated_at": now,
                    }
                )

            existing = next(
                (
                    person
                    for person in self._people
                    if person["name"].casefold() == clean_name.casefold()
                ),
                None,
            )
            if existing is None:
                existing = {
                    "id": uuid.uuid4().hex[:12],
                    "name": clean_name,
                    "templates": templates,
                    "updated_at": now,
                }
                self._people.append(existing)
            else:
                existing["name"] = clean_name
                existing["templates"] = [
                    item
                    for item in existing["templates"]
                    if item.get("view") not in self.VALID_VIEWS
                ] + templates
                existing["updated_at"] = now
                existing.pop("embedding", None)
            self._save()
            return {
                "id": existing["id"],
                "name": existing["name"],
                "updated_at": now,
                "mode": "guided_multi_angle",
                "views": ["front", "left", "right"],
                "samples": {view: len(value) for view, value in samples.items()},
                "rejected": rejected or {},
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
            templates = [
                (
                    person,
                    np.asarray(template["embedding"], dtype=np.float32),
                )
                for person in self._people
                for template in person["templates"]
            ]
            results: list[dict] = []
            for face in faces[:5]:
                feature = self._feature(frame, face)
                if feature is None:
                    continue
                best_person = None
                best_score = -1.0
                for person, embedding in templates:
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

    @staticmethod
    def _face_yaw(face: np.ndarray) -> float | None:
        # YuNet row: bbox, right eye, left eye, nose, mouth corners, score.
        eye_a_x = float(face[4])
        eye_b_x = float(face[6])
        nose_x = float(face[8])
        eye_span = abs(eye_b_x - eye_a_x)
        if eye_span < 1.0:
            return None
        return (nose_x - (eye_a_x + eye_b_x) * 0.5) / eye_span

    @staticmethod
    def _face_sharpness(frame: np.ndarray, face: np.ndarray) -> float:
        height, width = frame.shape[:2]
        x, y, box_width, box_height = (int(round(value)) for value in face[:4])
        x1, y1 = max(0, x), max(0, y)
        x2, y2 = min(width, x + box_width), min(height, y + box_height)
        if x2 <= x1 or y2 <= y1:
            return 0.0
        gray = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
        return float(cv2.Laplacian(gray, cv2.CV_64F).var())

    def _load(self) -> None:
        if not self.database_path.exists():
            return
        try:
            payload = json.loads(self.database_path.read_text(encoding="utf-8"))
            loaded: list[dict] = []
            for person in payload.get("people", []):
                if not {"id", "name", "updated_at"} <= set(person):
                    continue
                templates = person.get("templates")
                if not isinstance(templates, list) and isinstance(person.get("embedding"), list):
                    templates = [
                        {
                            "view": "legacy",
                            "embedding": person["embedding"],
                            "updated_at": person["updated_at"],
                        }
                    ]
                valid_templates = [
                    template
                    for template in (templates or [])
                    if isinstance(template, dict)
                    and isinstance(template.get("embedding"), list)
                    and isinstance(template.get("view"), str)
                ]
                if valid_templates:
                    loaded.append(
                        {
                            "id": person["id"],
                            "name": person["name"],
                            "updated_at": person["updated_at"],
                            "templates": valid_templates,
                        }
                    )
            self._people = loaded
        except (OSError, ValueError, TypeError):
            self._people = []

    def _save(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 2, "people": self._people}
        temporary = self.database_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        temporary.replace(self.database_path)
