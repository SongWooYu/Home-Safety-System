"""Browser review tests: synthetic HTTP events, real Pi5 WebRTC; no MQTT writes.

Default starts a temporary local Flask fixture (requires Flask, paho, Pillow,
Playwright). --base http://192.168.1.10:8000 verifies the deployed module instead.
All event/photo fixtures exist only in the test browser, never the real history.
"""
import argparse
from datetime import datetime, timezone, timedelta
from io import BytesIO
import importlib.util
import json
from pathlib import Path
import threading
from unittest.mock import patch

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def fixture():
    from flask import Flask, send_file
    from werkzeug.serving import make_server
    spec = importlib.util.spec_from_file_location("notice_fixture", ROOT / "pi4/integrations/fall_notice.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = Flask(__name__)
    with patch("paho.mqtt.client.Client"):
        module.install(app)

    @app.get("/")
    def home():
        return '<html><body>Fixture dashboard<script src="/static/fall_notice.js"></script></body></html>'

    @app.get("/static/fall_notice.js")
    def notice_js():
        return send_file(ROOT / "pi4/integrations/fall_notice.js")

    server = make_server("127.0.0.1", 0, app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


def main():
    args = argparse.ArgumentParser()
    args.add_argument("--base")
    base = args.parse_args().base
    server = None
    if not base:
        server, base = fixture()
    now = datetime.now(timezone.utc)
    events = [{"event_id":f"{i:032x}", "camera_id":"dahua", "test":i % 2 == 0,
               "timestamp":(now-timedelta(seconds=i)).isoformat(), "snapshot_available":True,
               "event_type":"fall_confirmed", "sequence":51-i} for i in range(1,51)]
    jpeg = BytesIO()
    Image.new("RGB", (640,360), (50,80,120)).save(jpeg,format="JPEG")
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", headless=True,
                                                args=["--no-sandbox","--disable-dev-shm-usage"])
            context = browser.new_context(viewport={"width":1440,"height":1100})
            context.add_init_script("""window.testPeers=[]; const Original=RTCPeerConnection;
              window.RTCPeerConnection=class extends Original {constructor(...args){super(...args);window.testPeers.push(this);}};""")
            context.route("**/api/fall-history",lambda route:route.fulfill(json={"epoch":"fixture","connected":True,"events":events}))
            context.route("**/api/fall-notices?*",lambda route:route.fulfill(json={"epoch":"fixture","cursor":50,"connected":True,"events":[]}))
            context.route("**/api/fall-notices",lambda route:route.fulfill(json={"epoch":"fixture","cursor":50,"connected":True,"events":[events[0]]}))
            context.route("**/api/fall-notices/*/snapshot.jpg",lambda route:route.fulfill(content_type="image/jpeg",body=jpeg.getvalue()))
            page = context.new_page()
            errors=[]
            page.on("pageerror",lambda error:errors.append(str(error)))
            page.goto(base+"/fall-review?event="+events[0]["event_id"],wait_until="domcontentloaded")
            page.wait_for_function("!document.getElementById('live-video').hidden",timeout=22000)
            page.wait_for_function("!document.getElementById('snapshot').hidden && document.getElementById('snapshot').complete")
            assert page.locator(".event-row").count()==50
            before=page.locator("#live-video").evaluate("v=>v.currentTime")
            page.wait_for_timeout(1600)
            assert page.locator("#live-video").evaluate("v=>v.currentTime")>before+0.5
            remote=page.evaluate("""async()=>{const stats=await testPeers.at(-1).getStats();
              const transport=[...stats.values()].find(s=>s.type==='transport'&&s.selectedCandidatePairId);
              const pair=stats.get(transport.selectedCandidatePairId);
              const candidate=stats.get(pair.remoteCandidateId);
              return {address:candidate.address,port:candidate.port,protocol:candidate.protocol,type:candidate.candidateType};} """)
            assert remote["port"]==8189 and remote["address"]!="192.168.1.10",remote
            print("PASS real direct Pi5 media",remote,flush=True)
            for width in (1440,780,390):
                page.set_viewport_size({"width":width,"height":1100})
                assert page.evaluate("document.documentElement.scrollWidth<=innerWidth"),width
            page.select_option("#filter","test")
            assert page.locator(".event-row").count()==25
            page.locator(".event-row").first.click()
            page.wait_for_function("!document.getElementById('snapshot').hidden")
            assert "수동 시험" in page.locator("#event-title").inner_text()
            assert page.evaluate("testPeers.filter(p=>p.connectionState!=='closed').length")==1
            print("PASS 50 records, test labels, selection shares one live peer, responsive widths",flush=True)
            # Invalidate current status: never leave a stale 'normal' label.
            page.route("**/api/fall-review/current",lambda route:route.fulfill(json={"available":False}))
            page.wait_for_function("document.getElementById('current-state').textContent.includes('확인 불가')",timeout=7000)
            page.goto(base+"/fall-review?event=deleted",wait_until="domcontentloaded")
            page.wait_for_function("document.getElementById('event-title').textContent.includes('기록이 없습니다')")
            assert page.locator("#snapshot").is_hidden()
            print("PASS deleted event and offline AI not replaced with unrelated/normal state",flush=True)
            # Simulate hidden page without relying on headless tab focus behavior.
            page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'))")
            assert page.evaluate("testPeers.every(p=>p.connectionState==='closed')")
            page.evaluate("Object.defineProperty(document,'hidden',{configurable:true,value:false});document.dispatchEvent(new Event('visibilitychange'))")
            page.wait_for_function("!document.getElementById('live-video').hidden",timeout=22000)
            page.evaluate("RTCPeerConnection.prototype.getStats=async()=>new Map([['v',{type:'inbound-rtp',kind:'video',framesDecoded:0}]])")
            page.wait_for_function("document.getElementById('transport').textContent.includes('영상 정지')",timeout=10000)
            print("PASS hidden release, resume, stalled video reconnect",flush=True)
            page.goto(base+"/",wait_until="domcontentloaded")
            page.locator("#home-safety-fall-notice #show-image").click()
            page.wait_for_function("(()=>{const i=document.getElementById('home-safety-fall-notice').shadowRoot.getElementById('fall-image');return i.complete&&i.naturalWidth>0;})()")
            with context.expect_page() as opened:
                page.locator("#home-safety-fall-notice #image-link").click()
            detail=opened.value
            detail.wait_for_load_state("domcontentloaded")
            assert "event="+events[0]["event_id"] in detail.url
            detail.wait_for_function("!document.getElementById('live-video').hidden",timeout=22000)
            print("PASS popup image opens exact event + live WebRTC in new tab",flush=True)
            assert not errors,errors
            context.close();browser.close()
            print("PASS browser validation (synthetic HTTP fixtures; no MQTT alarm emitted)",flush=True)
    finally:
        if server:
            server.shutdown()


if __name__=="__main__":
    main()
