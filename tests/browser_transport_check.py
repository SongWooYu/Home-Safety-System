"""Optional live browser check (Playwright + Chromium), never emits alarms.

Run on Pi5: <playwright-python> tests/browser_transport_check.py
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="/usr/bin/chromium", headless=True,
                                            args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(viewport={"width":1440, "height":1100})
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto("http://192.168.1.20:8080", wait_until="domcontentloaded")
        page.wait_for_function("document.querySelectorAll('video:not([hidden])').length === 2", timeout=20000)
        before = page.locator("video").evaluate_all("els=>els.map(v=>v.currentTime)")
        page.wait_for_timeout(2000)
        after = page.locator("video").evaluate_all("els=>els.map(v=>v.currentTime)")
        assert all(b > a + 1 for a,b in zip(before, after)), (before,after)
        print("PASS two WebRTC streams",page.locator("video").evaluate_all("els=>els.map(v=>[v.videoWidth,v.videoHeight])"))
        # Use only local UI fixtures, not detector state or MQTT.
        for width in (1440, 780, 390):
            page.set_viewport_size({"width":width,"height":1000})
            positions = page.evaluate("""() => {
              const result=[];
              for (const [tone,title,detail] of [
                ['normal','현재 낙상 경보 없음','움직임 분석 중'],
                ['danger','낙상이 감지되었습니다','Dahua에서 낙상을 확정했습니다. 영상 속 사람의 상태를 확인해 주세요.'],
                ['warning','관절 확인 필요','몸 전체가 잘 보이지 않습니다. 카메라 구도를 확인해 주세요. '.repeat(8)]]) {
                setAlarm(tone,title,detail);
                document.getElementById('analysis-detail').textContent=detail;
                document.getElementById('decision-gate').textContent=detail;
                result.push([document.getElementById('camera-dahua').getBoundingClientRect().y,
                             document.getElementById('audio-test-panel').getBoundingClientRect().y]);
              }
              return result;
            }""")
            assert all(position == positions[0] for position in positions), (width, positions)
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
        print("PASS fixed status layout at desktop/tablet/mobile")
        page.set_viewport_size({"width":1440,"height":1100})
        page.select_option("#stream-mode","overlay")
        page.wait_for_timeout(1500)
        assert page.locator("video").count() == 0
        assert page.locator("#stream-dahua").evaluate("el=>!el.hidden && el.naturalWidth > 1")
        print("PASS explicit overlay MJPEG")
        page.route("**/api/webrtc/**", lambda route: route.fulfill(status=503,json={"error":"forced test"}))
        page.select_option("#stream-mode","auto")
        page.wait_for_function("Array.from(document.querySelectorAll('.transport-label')).every(e=>e.textContent.startsWith('MJPEG'))")
        assert page.locator("video").count() == 0
        print("PASS WebRTC failure -> MJPEG")
        page.unroute("**/api/webrtc/**")
        page.locator("#reconnect").click()
        page.wait_for_function("document.querySelectorAll('video:not([hidden])').length === 2", timeout=20000)
        # A connected peer with no newly decoded frames must also fall back.
        page.evaluate("RTCPeerConnection.prototype.getStats = async () => new Map([['video',{type:'inbound-rtp',kind:'video',framesDecoded:0}]])")
        page.wait_for_function("Array.from(document.querySelectorAll('.transport-label')).every(e=>e.textContent.includes('영상 정지'))",timeout=12000)
        print("PASS stalled video -> MJPEG")
        for _ in range(3):
            page.locator("#tab-face-enrollment").click()
            assert page.locator("#stream-enrollment").get_attribute("src").startswith("/stream/cam3?overlay=false")
            assert page.locator("video").count() == 0
            page.locator("#tab-event-panel").click()
            assert page.locator("video").count() == 0
            assert page.locator('.stream[data-streaming="true"]').count() == 0
        print("PASS hidden tab resources released; enrollment stays mirrored MJPEG")
        assert not errors, errors
        context.close()
        browser.close()
        print("PASS browser validation; no alarms emitted")


if __name__ == "__main__":
    main()
