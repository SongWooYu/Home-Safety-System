"""Small guard around collaborator rules; sensor thresholds remain unchanged."""
from contextlib import contextmanager
import time

from control_state import AUTOMATIC, ControlError, Store


class AutomationGate:
    def __init__(self, client, store=None):
        self.client = client
        self.store = store or Store()
        self.current = None

    def sync_commands(self, states, data):
        # Manual commands are fed back into the legacy engine's own flags so
        # auto resume does not incorrectly assume the pre-demo device state.
        flags = {"light":"light_on","aircon":"aircon_on","fan":"fan_on",
                 "alarm":"alarm_on","curtain":"curtain_open"}
        for (room,device), values in AUTOMATIC.items():
            command = data["commands"].get(f"{room}/{device}")
            if not command or room not in states:
                continue
            key = "entrance_light_on" if room == "entrance" and device == "light" else flags[device]
            states[room][key] = command["value"] in {"ON","OPEN"}
            if device == "curtain" and command.get("source") == "manual":
                states[room]["curtain_reason"] = "시작"

    @contextmanager
    def cycle(self, states, message=None):
        with self.store.transaction() as data:
            self.current = data
            try:
                data.update(engine_at=time.monotonic(),engine_connected=self.client.is_connected())
                self.sync_commands(states,data)
                gas = message is not None and message.topic == "home/kitchen/gas"
                previous_gas = data.get("gas_active",False)
                if gas and message.payload in {b"ON",b"OFF"}:
                    data["gas_active"] = message.payload == b"ON"
                if data["mode"] == "manual" and message is not None:
                    self.observe_paused(states,message)
                # Repeated safe gas readings must not immediately cancel a
                # manually demonstrated buzzer. Real gas ON/clear takes priority.
                yield data["mode"] == "auto" or (gas and (previous_gas or data["gas_active"]))
            finally:
                self.current = None

    @staticmethod
    def observe_paused(states, message):
        # Edge-triggered presence/door OFF messages must not be lost while
        # automatic outputs are paused, otherwise auto resume uses stale flags.
        parts = message.topic.split("/")
        if len(parts) != 3 or parts[0] != "home" or parts[1] not in states:
            return
        state, metric = states[parts[1]], parts[2]
        value = message.payload
        if metric in {"motion","presence"} and value in {b"ON",b"OFF"}:
            if metric == "presence":
                state["presence_on"] = value == b"ON"
            if value == b"ON":
                state["last_motion"] = time.time()
        elif metric == "door" and value in {b"OPEN",b"CLOSED",b"CLOSE"}:
            if value != b"OPEN" and state.get("door_open"):
                state["door_closed_at"] = time.time()
            state["door_open"] = value == b"OPEN"

    def command(self, topic, value):
        parts = topic.split("/")
        if len(parts) != 4 or parts[0] != "home" or parts[3] != "set":
            raise ControlError("잘못된 자동 명령")
        room,device = parts[1:3]
        if (room,device) not in AUTOMATIC or value not in AUTOMATIC[(room,device)]:
            raise ControlError("허용되지 않은 자동 명령")
        if self.current is None or (self.current["mode"] != "auto" and device != "alarm"):
            raise ControlError("수동 모드에서 자동 명령 차단")
        # Called from MQTT callback: do not wait for an ACK on that same loop.
        result = self.client.publish(topic,value,qos=0,retain=False)
        if result.rc != 0:
            raise ControlError("자동 명령 MQTT 전송 실패")
        Store.record(self.current,room,device,value,"auto")
        print(f"명령: {topic} = {value}",flush=True)

    def dispatch(self, handler, states, c, userdata, message):
        try:
            with self.cycle(states,message) as enabled:
                if enabled:
                    handler(c,userdata,message)
        except (ControlError,OSError) as exc:
            print(f"제어 보류: {exc}",flush=True)

    def timers(self, handler, states):
        try:
            with self.cycle(states) as enabled:
                if enabled:
                    handler()
        except (ControlError,OSError) as exc:
            print(f"타이머 제어 보류: {exc}",flush=True)
