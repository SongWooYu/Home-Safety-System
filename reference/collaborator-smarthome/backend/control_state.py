"""Bounded Pi4 control state shared by web/automation under one process lock.

Deployed beside both web/device_control.py and backend/control_gate.py.
/run is tmpfs: no sensor-rate SD writes and no PostgreSQL schema changes.
"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import time

ALLOWED = {
    ("livingroom", "light"): ("ON", "OFF"),
    ("livingroom", "aircon"): ("ON", "OFF"),
    ("livingroom", "curtain"): ("OPEN", "CLOSE"),
    ("bathroom", "light"): ("ON", "OFF"),
    ("bathroom", "fan"): ("ON", "OFF"),
    ("kitchen", "alarm"): ("ON", "OFF"),
}
AUTOMATIC = dict(ALLOWED) | {("entrance", "light"): ("ON", "OFF")}


class ControlError(Exception):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


class Store:
    def __init__(self, directory="/run/smarthome-control"):
        self.directory = Path(directory)

    @contextmanager
    def transaction(self, write=True):
        # Directory is provisioned/owned by systemd, never mkdir an arbitrary
        # caller-selected path in the HTTP handler.
        try:
            lock = (self.directory / "state.lock").open("a")
        except OSError as exc:
            raise ControlError("제어 엔진이 준비되지 않았습니다.") from exc
        try:
            deadline = time.monotonic() + 3
            while True:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        raise ControlError("다른 제어 요청 처리 중입니다. 다시 시도해 주세요.")
                    time.sleep(0.02)
            path = self.directory / "state.json"
            try:
                with path.open() as source:
                    raw = source.read(32769)
                if len(raw) > 32768:
                    raise ValueError("oversized state")
                data = json.loads(raw)
                if (not isinstance(data, dict) or data.get("mode") not in {"auto", "manual"}
                        or type(data.get("revision")) is not int
                        or not isinstance(data.get("commands"), dict)):
                    raise ValueError("invalid state")
            except FileNotFoundError:
                data = {"mode":"auto", "revision":0, "updated_at":time.time(),
                        "commands":{}, "gas_active":False, "engine_at":0, "engine_connected":False}
            except (ValueError, TypeError, OSError) as exc:
                raise ControlError("제어 상태 파일 오류: 자동/수동 명령을 보류합니다.") from exc
            yield data
            if write:
                encoded = json.dumps(data,ensure_ascii=False)
                if len(encoded.encode()) > 32768:
                    raise ControlError("제어 상태 크기 초과")
                temporary = self.directory / "state.tmp"
                with temporary.open("w") as target:
                    target.write(encoded)
                os.replace(temporary, path)
        finally:
            lock.close()

    @staticmethod
    def ready(data):
        return data.get("engine_connected") is True and 0 <= time.monotonic()-data.get("engine_at",0) <= 15

    @staticmethod
    def public(data):
        return {"mode":data["mode"], "revision":data["revision"], "ready":Store.ready(data),
                "updated_at":data["updated_at"], "gas_active":data.get("gas_active",False),
                "commands":[dict(room=room,device=device,**data["commands"][f"{room}/{device}"])
                            for room,device in ALLOWED if f"{room}/{device}" in data["commands"]]}

    @staticmethod
    def require_ready(data, revision):
        if not Store.ready(data):
            raise ControlError("자동화 엔진 또는 MQTT 연결을 확인해 주세요.")
        if type(revision) is not int or revision != data["revision"]:
            raise ControlError("다른 화면에서 모드가 변경되었습니다. 새 상태를 확인해 주세요.",409)

    @staticmethod
    def record(data, room, device, value, source):
        data["commands"][f"{room}/{device}"] = {"value":value, "source":source, "at":time.time()}


def set_mode(store, mode, revision):
    if not isinstance(mode,str) or mode not in {"auto", "manual"}:
        raise ControlError("auto 또는 manual만 허용합니다.",400)
    with store.transaction() as data:
        Store.require_ready(data,revision)
        if data["mode"] != mode:
            data.update(mode=mode,revision=data["revision"]+1,updated_at=time.time())
        return Store.public(data)


def manual_command(store, room, device, value, revision, publish):
    if (room,device) not in ALLOWED or value not in ALLOWED[(room,device)]:
        raise ControlError("허용되지 않은 기기 또는 값입니다.",400)
    with store.transaction() as data:
        Store.require_ready(data,revision)
        if data["mode"] != "manual":
            raise ControlError("수동 모드로 전환한 뒤 조작해 주세요.",409)
        if (room,device,value) == ("kitchen","alarm","OFF") and data.get("gas_active"):
            raise ControlError("실제 가스 감지 중에는 부저를 끌 수 없습니다.",409)
        topic = f"home/{room}/{device}/set"
        publish(topic,value)  # Same lock as automatic decisions: no mode race.
        Store.record(data,room,device,value,"manual")
        return {"ok":True,"topic":topic,"value":value,"control":Store.public(data),
                "note":"MQTT 전달 확인입니다. 실제 기기 동작 확인은 별도입니다."}
