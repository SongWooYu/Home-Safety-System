"""Synthetic API responses only: never sends a real command or changes a mode."""
import argparse
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--base",default="http://192.168.1.10:8000")
    base=parser.parse_args().base
    state={"mode":"auto","revision":0,"ready":True,"gas_active":False,"commands":[]}
    sent=[]
    def mode(route):
        if route.request.method=="POST":
            request=route.request.post_data_json
            assert request["revision"]==state["revision"]
            state.update(mode=request["mode"],revision=state["revision"]+1)
        route.fulfill(json=state)
    def command(route):
        assert state["mode"]=="manual"
        sent.append(route.request.post_data_json)
        route.fulfill(json={"ok":True,"control":state})
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path="/usr/bin/chromium",headless=True,args=["--no-sandbox","--disable-dev-shm-usage"])
        page=browser.new_page(viewport={"width":1200,"height":1000})
        page.route("**/api/control-mode",mode);page.route("**/api/command",command)
        page.goto(base,wait_until="domcontentloaded")
        page.add_script_tag(path=str(ROOT/"pi4/integrations/device_control.js"))
        panel=page.locator("#home-safety-device-control")
        page.wait_for_function("document.getElementById('home-safety-device-control').shadowRoot.getElementById('auto').getAttribute('aria-pressed')==='true'")
        assert panel.locator(".buttons button:disabled").count()==12
        panel.locator("#manual").click()
        page.wait_for_function("document.getElementById('home-safety-device-control').shadowRoot.querySelectorAll('.buttons button:disabled').length===0")
        panel.locator(".buttons button").first.click()
        page.wait_for_function("document.getElementById('home-safety-device-control').shadowRoot.getElementById('result').textContent.includes('MQTT 전달 확인')")
        assert len(sent)==1 and sent[0]["room"]=="livingroom" and sent[0]["value"]=="ON"
        state["gas_active"]=True
        page.wait_for_function("document.getElementById('home-safety-device-control').shadowRoot.querySelector('button[data-device=alarm][data-value=OFF]').disabled")
        state["ready"]=False
        page.wait_for_function("document.getElementById('home-safety-device-control').shadowRoot.getElementById('manual').disabled")
        assert panel.locator(".buttons button:disabled").count()==12
        for width in (1200,390):
            page.set_viewport_size({"width":width,"height":1000})
            assert panel.evaluate("e=>e.scrollWidth<=e.clientWidth")
        browser.close()
    print("PASS isolated controls, modes, device request, gas override, offline guard, responsive panel; no real MQTT writes")


if __name__=="__main__":main()
