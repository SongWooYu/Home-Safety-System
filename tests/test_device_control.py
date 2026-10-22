"""No real MQTT/device commands; isolated tmpfs-store equivalent per test."""
import ast
import shutil
import subprocess
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from flask import Flask

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"pi4/integrations"))
from control_state import ALLOWED, ControlError, Store, manual_command, set_mode
from control_gate import AutomationGate
import device_control


class DeviceControlTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store=Store(self.tmp.name)
        self.client=Mock()
        self.client.is_connected.return_value=True
        self.client.publish.return_value.rc=0
        self.client.publish.return_value.is_published.return_value=True
        self.gate=AutomationGate(self.client,self.store)
        self.states={"livingroom":{"light_on":False},"kitchen":{"alarm_on":False}}
        self.gate.timers(lambda:None,self.states)

    def state(self):
        with self.store.transaction(write=False) as data:
            return Store.public(data)

    def mode(self,value):
        return set_mode(self.store,value,self.state()["revision"])

    def command(self,room="livingroom",device="light",value="ON",publish=None):
        return manual_command(self.store,room,device,value,self.state()["revision"],publish or Mock())

    def test_auto_rejects_manual_and_manual_blocks_sensor_and_timer_commands(self):
        with self.assertRaises(ControlError): self.command()
        handler=Mock()
        self.gate.dispatch(handler,self.states,self.client,None,SimpleNamespace(topic="home/livingroom/motion",payload=b"ON"))
        handler.assert_called_once();handler.reset_mock()
        self.mode("manual")
        self.gate.dispatch(handler,self.states,self.client,None,SimpleNamespace(topic="home/livingroom/motion",payload=b"ON"))
        self.gate.timers(handler,self.states)
        handler.assert_not_called()
        self.client.publish.assert_not_called()
        publish=Mock();self.command(publish=publish)
        publish.assert_called_once_with("home/livingroom/light/set","ON")

    def test_auto_resume_has_manual_command_state_and_curtain_reason(self):
        self.mode("manual")
        self.command()
        self.states["livingroom"]["curtain_reason"]="밤"
        self.command(device="curtain",value="CLOSE")
        self.mode("auto")
        def evaluate():
            self.assertTrue(self.states["livingroom"]["light_on"])
            self.assertFalse(self.states["livingroom"]["curtain_open"])
            self.assertEqual(self.states["livingroom"]["curtain_reason"],"시작")
            self.gate.command("home/livingroom/light/set","OFF")
        self.gate.timers(evaluate,self.states)
        self.client.publish.assert_called_once_with("home/livingroom/light/set","OFF",qos=0,retain=False)

    def test_gas_priority_and_neutral_gas_does_not_cancel_demo(self):
        self.mode("manual")
        handler=Mock()
        for value,expected in [(b"OFF",False),(b"ON",True),(b"ON",True),(b"OFF",True),(b"OFF",False)]:
            handler.reset_mock()
            self.gate.dispatch(handler,self.states,self.client,None,SimpleNamespace(topic="home/kitchen/gas",payload=value))
            self.assertEqual(handler.called,expected)
            if value==b"ON":
                with self.assertRaises(ControlError): self.command("kitchen","alarm","OFF")
        self.command("kitchen","alarm","ON")
        self.command("kitchen","alarm","OFF")

    def test_allowlist_revision_and_engine_freshness(self):
        old=self.state()["revision"]
        self.mode("manual")
        with self.assertRaises(ControlError): set_mode(self.store,"auto",old)
        with self.assertRaises(ControlError): set_mode(self.store,[],0)
        with self.assertRaises(ControlError): self.command(room="arbitrary")
        with self.assertRaises(ControlError): self.command(value="TOGGLE")
        with self.store.transaction() as data: data["engine_at"]=time.monotonic()-30
        self.assertFalse(self.state()["ready"])
        with self.assertRaises(ControlError): self.command()

    def test_command_and_mode_change_are_serialized_across_store_instances(self):
        self.mode("manual");revision=self.state()["revision"]
        entered=threading.Event();release=threading.Event();finished=threading.Event()
        def publish(*args): entered.set();release.wait(2)
        first=threading.Thread(target=lambda:manual_command(self.store,"livingroom","light","ON",revision,publish))
        second=threading.Thread(target=lambda:(set_mode(Store(self.tmp.name),"auto",revision),finished.set()))
        first.start();self.assertTrue(entered.wait(1));second.start()
        self.assertFalse(finished.wait(.1));release.set();first.join(2);second.join(2)
        self.assertTrue(finished.is_set());self.assertEqual(self.state()["mode"],"auto")

    def test_command_history_bounded_and_mqtt_error_not_success(self):
        self.mode("manual")
        for i in range(100): self.command(value="ON" if i%2 else "OFF")
        with self.store.transaction(write=False) as data: self.assertEqual(len(data["commands"]),1)
        with self.assertRaises(RuntimeError): self.command(publish=Mock(side_effect=RuntimeError("mqtt")))

    def app(self):
        app=Flask(__name__)
        device_control.install(app,self.store,self.client)
        return app.test_client()

    def test_http_mode_and_command_ack_no_sensor_fabrication(self):
        client=self.app()
        status=client.get("/api/control-mode")
        self.assertEqual(status.status_code,200)
        result=client.post("/api/control-mode",json={"mode":"manual","revision":status.json["revision"]})
        self.assertEqual(result.status_code,200)
        # New app instance avoids intentionally enforced 250ms click throttle.
        result=self.app().post("/api/command",json={"room":"livingroom","device":"light","value":"ON","revision":result.json["revision"]})
        self.assertEqual(result.status_code,200)
        self.client.publish.assert_called_once_with("home/livingroom/light/set","ON",qos=1,retain=False)
        self.client.publish.return_value.wait_for_publish.assert_called_once_with(timeout=2)
        self.assertIn("실제 기기",result.json["note"])

    def test_http_validation_offline_and_unacknowledged_delivery(self):
        self.mode("manual")
        payload={"room":"livingroom","device":"light","value":"ON","revision":self.state()["revision"]}
        self.assertEqual(self.app().post("/api/command",json=payload,headers={"Origin":"https://evil.example"}).status_code,403)
        self.assertEqual(self.app().post("/api/command",data="ON").status_code,415)
        self.assertEqual(self.app().post("/api/command",json=[]).status_code,400)
        self.assertEqual(self.app().post("/api/command",json=payload|{"room":[]}).status_code,400)
        self.client.is_connected.return_value=False
        self.assertEqual(self.app().post("/api/command",json=payload).status_code,503)
        self.client.publish.assert_not_called()
        self.client.is_connected.return_value=True
        self.client.publish.return_value.is_published.return_value=False
        self.assertEqual(self.app().post("/api/command",json=payload).status_code,503)

    def test_http_cloudflare_proxy_origin_accepted_no_arbitrary_proxy(self):
        self.mode("manual")
        payload={"room":"livingroom","device":"light","value":"ON","revision":self.state()["revision"]}
        headers={"Host":"www.aihous.site","Origin":"https://www.aihous.site","X-Forwarded-Proto":"https"}
        self.assertEqual(self.app().post("/api/command",json=payload,headers=headers,environ_overrides={"REMOTE_ADDR":"192.168.1.20"}).status_code,200)
        self.assertEqual(self.app().post("/api/command",json=payload,headers=headers,environ_overrides={"REMOTE_ADDR":"192.168.1.99"}).status_code,403)

    def test_actual_collaborator_rules_with_minimal_hook_patch(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/"backend"
            target.mkdir()
            source=root/"reference/collaborator-smarthome/backend/automation.py"
            shutil.copy(source,target/"automation.py")
            if "from control_gate import AutomationGate" not in source.read_text():
                subprocess.run(["git","apply","--include=backend/automation.py",
                    str(root/"pi4/integrations/device-control-hooks.patch")],cwd=directory,check=True)
            tree=ast.parse((target/"automation.py").read_text())
        # Execute definitions and mocked MQTT wiring, never the infinite loop.
        tree.body=[node for node in tree.body if not isinstance(node,ast.While)]
        ns={}
        with patch("paho.mqtt.client.Client",return_value=self.client),patch("control_gate.AutomationGate",return_value=self.gate):
            exec(compile(tree,"collaborator_rules_fixture","exec"),ns)
        def sensor(metric,value,room="livingroom"):
            self.client.on_message(self.client,None,SimpleNamespace(topic=f"home/{room}/{metric}",payload=value.encode()))
        sensor("temperature","30")
        self.client.publish.assert_called_with("home/livingroom/aircon/set","ON",qos=0,retain=False)
        self.mode("manual");self.client.publish.reset_mock()
        sensor("temperature","20");sensor("motion","ON")
        self.gate.timers(ns["run_timers"],ns["state"])
        self.client.publish.assert_not_called()
        self.command(device="aircon",value="ON")
        self.mode("auto");sensor("temperature","20")
        self.client.publish.assert_called_with("home/livingroom/aircon/set","OFF",qos=0,retain=False)
        self.mode("manual");self.client.publish.reset_mock()
        sensor("gas","ON","kitchen")
        self.client.publish.assert_called_once_with("home/kitchen/alarm/set","ON",qos=0,retain=False)
        with self.assertRaises(ControlError):self.command("kitchen","alarm","OFF")
        sensor("gas","OFF","kitchen")
        self.client.publish.assert_called_with("home/kitchen/alarm/set","OFF",qos=0,retain=False)
