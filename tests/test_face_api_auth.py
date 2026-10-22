from __future__ import annotations

import unittest

from smarthome_vision.app import create_app


class FakeWorker:
    face_enrollment = True


class FakePipeline:
    def __init__(self):
        from smarthome_vision.events import EventBus
        self.event_bus = EventBus({})
        self.config = {"face_recognition": {"admin_token": "delete-secret"}}
        self.workers = {"cam3": FakeWorker()}
        self.face_registry = object()
        self.face_error = None
        self.enroll_calls = []
        self.auto_enroll_calls = []
        self.deleted = []
        self.stream_calls = []

    def add_stream_client(self, camera_id, overlay):
        self.stream_calls.append(("add", camera_id, overlay))

    def remove_stream_client(self, camera_id, overlay):
        self.stream_calls.append(("remove", camera_id, overlay))

    def camera_jpeg(self, camera_id, overlay=True):
        self.stream_calls.append(("jpeg", camera_id, overlay))
        return b"jpeg-data"

    def enroll_face(self, camera_id, name, view):
        self.enroll_calls.append((camera_id, name, view))
        return {
            "id": "person-1",
            "name": name,
            "view": view,
            "views": [view],
            "samples": 5,
        }

    def enroll_face_auto(self, camera_id, name):
        self.auto_enroll_calls.append((camera_id, name))
        return {
            "id": "person-1",
            "name": name,
            "mode": "guided_multi_angle",
            "views": ["front", "left", "right"],
            "samples": {"front": 4, "left": 3, "right": 3},
        }

    def registered_faces(self):
        return [{"id": "person-1", "name": "홍길동", "views": ["front"]}]

    def delete_face(self, person_id):
        self.deleted.append(person_id)
        return True


class FaceApiAuthorizationTest(unittest.TestCase):
    def setUp(self):
        self.pipeline = FakePipeline()
        self.client = create_app(self.pipeline).test_client()

    def test_clean_stream_registers_and_releases_a_clean_client(self):
        response = self.client.get(
            "/stream/cam3?overlay=false&fps=30",
            buffered=False,
        )
        first_chunk = next(response.response)
        response.close()

        self.assertIn(b"jpeg-data", first_chunk)
        self.assertEqual(
            self.pipeline.stream_calls,
            [
                ("add", "cam3", False),
                ("jpeg", "cam3", False),
                ("remove", "cam3", False),
            ],
        )

    def test_overlay_stream_is_the_default(self):
        response = self.client.get("/stream/cam3?fps=30", buffered=False)
        next(response.response)
        response.close()

        self.assertEqual(self.pipeline.stream_calls[0], ("add", "cam3", True))
        self.assertEqual(self.pipeline.stream_calls[-1], ("remove", "cam3", True))

    def test_enrollment_does_not_require_admin_token(self):
        response = self.client.post(
            "/api/faces/enroll",
            json={"camera_id": "cam3", "name": "홍길동", "view": "front"},
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.pipeline.enroll_calls, [("cam3", "홍길동", "front")])

        automatic = self.client.post(
            "/api/faces/enroll/auto",
            json={"camera_id": "cam3", "name": "홍길동"},
        )
        self.assertEqual(automatic.status_code, 201)
        self.assertEqual(self.pipeline.auto_enroll_calls, [("cam3", "홍길동")])

    def test_face_list_and_delete_still_require_admin_token(self):
        self.assertEqual(self.client.get("/api/faces").status_code, 401)
        self.assertEqual(self.client.delete("/api/faces/person-1").status_code, 401)

        headers = {"X-Face-Admin-Token": "delete-secret"}
        self.assertEqual(self.client.get("/api/faces", headers=headers).status_code, 200)
        self.assertEqual(
            self.client.delete("/api/faces/person-1", headers=headers).status_code,
            200,
        )
        self.assertEqual(self.pipeline.deleted, ["person-1"])

    def test_face_admin_key_becomes_persistent_http_only_session(self):
        denied = self.client.post(
            "/api/faces/admin/session",
            json={"token": "wrong"},
        )
        accepted = self.client.post(
            "/api/faces/admin/session",
            json={"token": "delete-secret"},
        )

        self.assertEqual(denied.status_code, 401)
        self.assertEqual(accepted.status_code, 200)
        self.assertIn("HttpOnly", accepted.headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", accepted.headers["Set-Cookie"])
        self.assertEqual(self.client.get("/api/faces").status_code, 200)

    def test_dashboard_separates_open_enrollment_from_protected_management(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("등록에는 관리 코드 불필요", html)
        self.assertIn("등록자 목록·삭제", html)
        self.assertIn("한 번 인증하면 30일 기억", html)
        self.assertNotIn("faceAdminToken", html)
        token_input = html.split('id="face-token"', 1)[1].split(">", 1)[0]
        self.assertNotIn("required", token_input)

    def test_dashboard_uses_guided_multi_angle_enrollment(self):
        response = self.client.get("/")

        html = response.get_data(as_text=True)
        self.assertIn("자동 다각도 등록", html)
        with self.client.get("/static/dashboard.js") as response:
            script = response.get_data(as_text=True)
        self.assertIn("/api/faces/enrollment", script)
        self.assertNotIn("const guideTimer", script)
        self.assertNotIn('id="face-view"', html)

    def test_dashboard_shows_hailo_edgefall_as_the_only_operational_path(self):
        response = self.client.get("/")

        html = response.get_data(as_text=True)
        self.assertIn("Hailo YOLOv8s-Pose + EdgeFall", html)
        self.assertNotIn("Rule Detector", html)
        self.assertNotIn("Temporal GRU", html)
        self.assertIn('id="alarm-banner"', html)
        self.assertIn('id="last-fall"', html)
        with self.client.get("/static/dashboard.css") as response:
            self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
    unittest.main()
