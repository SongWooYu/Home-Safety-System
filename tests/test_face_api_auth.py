from __future__ import annotations

import unittest

from smarthome_vision.app import create_app


class FakeWorker:
    face_enrollment = True


class FakePipeline:
    def __init__(self):
        self.config = {"face_recognition": {"admin_token": "delete-secret"}}
        self.workers = {"cam3": FakeWorker(), "webcam": FakeWorker()}
        self.face_registry = object()
        self.face_error = None
        self.enroll_calls = []
        self.deleted = []

    def enroll_face(self, camera_id, name, view):
        self.enroll_calls.append((camera_id, name, view))
        return {
            "id": "person-1",
            "name": name,
            "view": view,
            "views": [view],
            "samples": 5,
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

    def test_enrollment_does_not_require_admin_token(self):
        response = self.client.post(
            "/api/faces/enroll",
            json={"camera_id": "cam3", "name": "홍길동", "view": "front"},
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.pipeline.enroll_calls, [("cam3", "홍길동", "front")])

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

    def test_dashboard_separates_open_enrollment_from_protected_management(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("등록에는 관리 코드 불필요", html)
        self.assertIn("등록자 목록·삭제", html)
        token_input = html.split('id="face-token"', 1)[1].split(">", 1)[0]
        self.assertNotIn("required", token_input)

    def test_dashboard_uses_runtime_temporal_threshold(self):
        response = self.client.get("/")

        html = response.get_data(as_text=True)
        self.assertIn("bestTrack.threshold", html)
        self.assertNotIn("score >= .92", html)

    def test_dashboard_distinguishes_connection_rule_and_gru_states(self):
        response = self.client.get("/")

        html = response.get_data(as_text=True)
        self.assertIn("Pi5 프레임 age", html)
        self.assertIn("RULE 낙상", html)
        self.assertIn("GRU SHADOW 기준 충족", html)
        self.assertIn("MQTT 미전송", html)
        self.assertIn("자세 기하 점수는 낙상 확률이 아니며", html)


if __name__ == "__main__":
    unittest.main()
