"""Quality-gated multi-angle capture, not a timed recording or liveness proof."""
import logging
import threading
import time
import uuid

import numpy as np
from flask import jsonify, request

from .request_origin import same_origin_request

LOG = logging.getLogger(__name__)
VIEWS = ("front", "right", "left")
PROMPTS = {
    "front": "정면의 카메라 렌즈를 바라봐 주세요.",
    "right": "← 거울 화면을 보며 본인 왼쪽으로 고개를 조금 돌려 주세요.",
    "left": "거울 화면을 보며 본인 오른쪽으로 고개를 조금 돌려 주세요 →",
}


class GuidedCapture:
    def __init__(self, required=5):
        self.required = max(5, required)
        self.samples = {view: [] for view in VIEWS}
        self.step = 0
        self.since = None
        self.last_stamp = 0
        self.anchor = None
        self.message = PROMPTS["front"]

    def reject(self, message):
        self.message = message
        self.samples[VIEWS[self.step]].clear()
        self.since = None

    def feed(self, observation, stamp, now):
        if now - stamp > 1.5:
            self.reject("새 카메라 영상을 기다리고 있어요. 연결을 확인해 주세요.")
            return False
        if stamp <= self.last_stamp:
            return False
        self.last_stamp = stamp
        target = VIEWS[self.step]
        if observation.get("error"):
            self.reject(observation["error"])
            return False
        if observation["view"] != target:
            self.reject("아직 요청한 방향이 아니에요. " + PROMPTS[target])
            return False
        feature = observation["feature"]
        if self.anchor is not None and float(np.dot(self.anchor, feature)) < 0.30:
            self.reject("처음과 같은 얼굴인지 확인이 어려워요. 같은 사람이 천천히 돌려 주세요.")
            return False
        if self.anchor is None:
            self.anchor = feature.copy()
        if self.since is None:
            self.since = stamp
        if len(self.samples[target]) < self.required:
            self.samples[target].append(feature)
        self.message = "좋아요. 이 방향을 잠시 유지해 주세요."
        if len(self.samples[target]) < self.required or stamp - self.since < 0.8:
            return False
        if target == "front":
            self.anchor = np.mean(self.samples[target], axis=0)
            self.anchor /= max(float(np.linalg.norm(self.anchor)), 1e-8)
        self.step += 1
        self.since = None
        if self.step == len(VIEWS):
            self.message = "세 방향 확인 완료"
            return True
        self.message = PROMPTS[VIEWS[self.step]]
        return False

    def public(self):
        return {"step": min(self.step, 2), "direction": VIEWS[min(self.step, 2)],
                "display_direction": {"front":"front", "right":"left", "left":"right"}[VIEWS[min(self.step, 2)]],
                "message": self.message, "required": self.required,
                "samples": {view: len(items) for view, items in self.samples.items()},
                "progress": round(100 * sum(map(len, self.samples.values())) / (3 * self.required))}


class EnrollmentManager:
    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.lock = threading.RLock()
        self.session = None

    def start(self, camera_id, name):
        name = " ".join(name.split())
        if not name or len(name) > 40 or any(ord(c) < 32 for c in name):
            raise ValueError("이름은 1~40자로 입력하세요.")
        registry = self.pipeline.face_registry
        worker = self.pipeline.workers.get(camera_id)
        if registry is None or worker is None or not worker.face_enrollment:
            raise ValueError("얼굴 등록이 가능한 카메라를 선택하세요.")
        with self.lock:
            if self.session and self.session["status"] == "capturing":
                raise RuntimeError("이미 얼굴 등록 중입니다. 종료하거나 잠시 기다려 주세요.")
            session = {"id": uuid.uuid4().hex, "status": "capturing", "started": time.monotonic(),
                       "capture": GuidedCapture(registry.enrollment_min_samples_per_view),
                       "stop": threading.Event(), "person": None}
            self.session = session
            threading.Thread(target=self._run, args=(session, worker, registry, name),
                             daemon=True, name="face-enrollment").start()
            return self._public(session)

    def _public(self, session):
        result = session["capture"].public() if "capture" in session else dict(session["result"])
        result.update(id=session["id"], status=session["status"], person=session["person"],
                      remaining_seconds=max(0, round(45 - (time.monotonic() - session["started"]))))
        return result

    def _finish(self, session, status, message=None):
        session["status"] = status
        session["stop"].set()
        if "capture" in session:
            session["result"] = session.pop("capture").public()  # discard biometric samples
        if message:
            session["result"]["message"] = message

    def get(self, session_id, cancel=False):
        with self.lock:
            if self.session is None or self.session["id"] != session_id:
                raise KeyError(session_id)
            if cancel and self.session["status"] == "capturing":
                self._finish(self.session, "cancelled", "등록을 취소했습니다. 저장하지 않았습니다.")
            return self._public(self.session)

    def _run(self, session, worker, registry, name):
        try:
            while not session["stop"].is_set():
                stamp, frame = worker.registration_sample()
                now = time.monotonic()
                # OpenCV inspection outside the session lock; cancellation stays responsive.
                observation = (registry.enrollment_observation(frame)
                               if frame is not None and now - stamp <= 1.5
                               else {"error": "카메라 연결과 얼굴 위치를 확인해 주세요."})
                with self.lock:
                    if session["stop"].is_set():
                        return
                    if now - session["started"] >= 45:
                        self._finish(session, "failed", "45초 안에 세 방향을 확인하지 못했습니다. 저장하지 않았습니다.")
                        return
                    if session["capture"].feed(observation, stamp, now):
                        session["person"] = registry.save_guided_samples(name, session["capture"].samples)
                        self._finish(session, "completed")
                        return
                session["stop"].wait(0.25)
        except Exception:
            LOG.exception("guided enrollment failed")
            with self.lock:
                self._finish(session, "failed", "얼굴 등록 처리에 실패했습니다. 다시 시도해 주세요.")


def register_enrollment_routes(app, pipeline):
    manager = EnrollmentManager(pipeline)

    @app.post("/api/faces/enrollment")
    def begin():
        if not same_origin_request():
            return jsonify(error="다른 사이트에서는 등록할 수 없습니다."), 403
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(error="JSON 객체가 필요합니다."), 400
        try:
            return jsonify(manager.start(str(payload.get("camera_id", "")), str(payload.get("name", "")))), 202
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except RuntimeError as exc:
            return jsonify(error=str(exc)), 409

    @app.route("/api/faces/enrollment/<session_id>", methods=["GET", "DELETE"])
    def progress(session_id):
        if not same_origin_request():
            return jsonify(error="다른 사이트에서는 등록할 수 없습니다."), 403
        try:
            response = jsonify(manager.get(session_id, cancel=request.method == "DELETE"))
            response.headers["Cache-Control"] = "no-store"
            return response
        except KeyError:
            return jsonify(error="등록 세션을 찾을 수 없습니다."), 404
