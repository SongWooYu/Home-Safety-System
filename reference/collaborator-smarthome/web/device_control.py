"""Isolated manual controls for /opt/smarthome/web; no DB migrations."""
import atexit
from pathlib import Path
import threading
import time
import uuid

from flask import abort, jsonify, request, send_from_directory
from control_state import ControlError, Store, manual_command, set_mode
from fall_notice import same_origin


def install(app, store=None, mqtt_client=None):
    if "home_safety_device_control" in app.extensions:
        return
    import paho.mqtt.client as mqtt
    store = store or Store()
    client = mqtt_client or mqtt.Client(client_id="pi4-manual-"+uuid.uuid4().hex[:8])
    app.extensions["home_safety_device_control"] = store
    if mqtt_client is None:
        client.reconnect_delay_set(min_delay=1,max_delay=30)
        client.connect_async("127.0.0.1",1883,60)
        client.loop_start()
        atexit.register(lambda:(client.disconnect(),client.loop_stop()))
    rate_lock = threading.Lock()
    last_request = 0.0

    @app.get("/device-control.js")
    def control_script():
        response = send_from_directory(Path(__file__).resolve().parent,"device_control.js")
        response.headers["Cache-Control"] = "no-store"
        return response

    def authorize():
        nonlocal last_request
        if not same_origin():
            abort(403)
        if request.mimetype != "application/json":
            abort(415)
        if request.content_length is None or request.content_length > 2048:
            abort(413)
        data = request.get_json(silent=True)
        if not isinstance(data,dict):
            raise ControlError("JSON 객체가 필요합니다.",400)
        with rate_lock:
            if time.monotonic()-last_request < 0.25:
                raise ControlError("잠시 후 다시 눌러 주세요.",429)
            last_request = time.monotonic()
        return data

    def publish(topic,value):
        if not client.is_connected():
            raise ControlError("MQTT 연결이 끊겼습니다.")
        info = client.publish(topic,value,qos=1,retain=False)
        if info.rc != 0:
            raise ControlError("MQTT 전송 실패")
        try:
            info.wait_for_publish(timeout=2)
        except (ValueError,RuntimeError) as exc:
            raise ControlError("MQTT 전달 확인 실패. 기기 상태를 확인해 주세요.") from exc
        if not info.is_published():
            raise ControlError("MQTT 전달 확인 시간 초과. 기기 상태를 확인해 주세요.")

    def respond(action):
        try:
            response = jsonify(action())
        except ControlError as exc:
            response = jsonify(ok=False,error=str(exc)); response.status_code = exc.status
        except OSError:
            response = jsonify(ok=False,error="제어 상태를 읽을 수 없습니다.");response.status_code=503
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.route("/api/control-mode",methods=["GET","POST"])
    def control_mode():
        def action():
            if request.method == "GET":
                with store.transaction(write=False) as state:
                    data = Store.public(state)
                    data["ready"] = data["ready"] and client.is_connected()
                    return data
            data = authorize()
            return set_mode(store,data.get("mode"),data.get("revision"))
        return respond(action)

    @app.post("/api/command")
    def control_command():
        def action():
            data = authorize()
            for key in ("room","device","value"):
                if not isinstance(data.get(key),str):
                    raise ControlError("기기/값 문자열이 필요합니다.",400)
            return manual_command(store,data["room"],data["device"],data["value"].upper(),data.get("revision"),publish)
        return respond(action)
