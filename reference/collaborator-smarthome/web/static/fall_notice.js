/* Isolated, read-only fall notification. No collaborator globals or CSS. */
(() => {
  "use strict";
  if (document.getElementById("home-safety-fall-notice")) return;
  const host = document.createElement("div");
  host.id = "home-safety-fall-notice";
  const root = host.attachShadow({mode:"open"});
  root.innerHTML = `
    <style>
      :host {all:initial;position:fixed;top:20px;right:20px;z-index:2147483000;pointer-events:none;}
      section {box-sizing:border-box;width:min(360px,calc(100vw - 40px));padding:20px;border:1px solid #ff7b85;border-top:5px solid #ed4355;border-radius:16px;background:#17202e;color:#f9fafb;font:15px/1.5 system-ui,sans-serif;box-shadow:0 16px 45px #0006;pointer-events:auto;animation:arrive .18s ease-out;}
      [hidden] {display:none!important;} h2 {margin:0 35px 12px 0;font-size:21px;} p {margin:6px 0;} small {display:block;color:#c1cbd9;margin-top:14px;font-size:12px;}
      button {position:absolute;right:14px;top:16px;width:32px;height:32px;border:1px solid #8190a7;border-radius:8px;background:transparent;color:white;font-size:22px;cursor:pointer;}
      button:focus-visible {outline:3px solid #a8caff;} @keyframes arrive {from {opacity:0;transform:translateY(-8px);} to {opacity:1;transform:translateY(0);}}
      #show-image {position:static;width:100%;height:auto;font-size:14px;padding:10px;margin-top:12px;}
      #fall-image {display:block;width:100%;max-height:45vh;object-fit:contain;margin-top:12px;border-radius:8px;}
      a {color:#b4d0ff;font:14px/1.5 system-ui,sans-serif;pointer-events:auto;}
      #history-entry {position:fixed;bottom:20px;right:20px;padding:9px 14px;background:#17202e;border:1px solid #8190a7;border-radius:10px;text-decoration:none;box-shadow:0 4px 18px #0003;}
      #review-link {display:block;margin-top:10px;}
      @media(prefers-reduced-motion:reduce) {section {animation:none;}}
    </style>
    <section role="dialog" aria-modal="false" aria-labelledby="fall-title" hidden>
      <button type="button" aria-label="낙상 알림 닫기">×</button>
      <h2 id="fall-title">낙상 감지</h2><div role="status" aria-live="polite"><p id="fall-camera"></p><p id="fall-time"></p></div>
      <button type="button" id="show-image" hidden>발생 당시 캡처 확인</button>
      <a id="image-link" href="/fall-review" target="_blank" rel="noopener" aria-label="이 사건의 사진과 현재 영상을 새 탭에서 확인"><img id="fall-image" alt="낙상 확정 시점 캡처 · 누르면 현재 영상도 확인 (새 탭)" hidden></a>
      <p id="image-status" role="status"></p>
      <a id="review-link" href="/fall-review" target="_blank" rel="noopener">이 사건 · 현재 영상 확인 ↗</a>
      <small>현장 상황을 확인해 주세요.<br>닫기는 알림창만 숨깁니다. 스피커 경보는 해제하지 않습니다.</small>
    </section>
    <a id="history-entry" href="/fall-review" target="_blank" rel="noopener">낙상 기록 · 현재 영상 ↗</a>`;
  document.body.append(host);
  const panel = root.querySelector("section");
  const dismissed = new Set();
  try { JSON.parse(sessionStorage.getItem("home-safety-dismissed-falls") || "[]").forEach(id => dismissed.add(id)); } catch (_) {}
  let current = null, cursor = null, epoch = null;
  function dismiss() {
    if (current) dismissed.add(current);
    while (dismissed.size > 100) dismissed.delete(dismissed.values().next().value);
    try { sessionStorage.setItem("home-safety-dismissed-falls", JSON.stringify([...dismissed])); } catch (_) {}
    panel.hidden = true;
  }
  root.querySelector("button").addEventListener("click", dismiss);
  const picture = root.getElementById("fall-image");
  root.getElementById("show-image").addEventListener("click", () => {
    root.getElementById("image-status").textContent = "Pi5에서 캡처 한 장을 가져옵니다…";
    picture.src = `/api/fall-notices/${encodeURIComponent(current)}/snapshot.jpg`;
    picture.hidden = false;
  });
  picture.onload = () => { root.getElementById("image-status").textContent = "발생 당시 분석 프레임 · 사진을 누르면 새 탭에서 현재 영상 확인"; };
  picture.onerror = () => { picture.hidden = true; root.getElementById("image-status").textContent = "캡처가 만료되었거나 Pi5에 연결할 수 없습니다."; };
  document.addEventListener("pointerdown", event => {
    if (!panel.hidden && !event.composedPath().includes(host)) dismiss();
  }, true);
  document.addEventListener("keydown", event => { if (event.key === "Escape") dismiss(); });
  async function poll() {
    if (document.hidden) { setTimeout(poll, 2000); return; }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 4000);
    try {
      const params = cursor === null ? "" : `?after=${cursor}&epoch=${encodeURIComponent(epoch)}`;
      const response = await fetch(`/api/fall-notices${params}`, {cache:"no-store", signal:controller.signal});
      if (!response.ok) throw new Error("fall notice unavailable");
      const data = await response.json();
      cursor = data.cursor; epoch = data.epoch;
      const events = data.events.filter(event => !dismissed.has(event.event_id));
      if (events.length) {
        const event = events[events.length - 1];
        current = event.event_id;
        for (const id of ["image-link", "review-link"]) root.getElementById(id).href = `/fall-review?event=${encodeURIComponent(current)}`;
        root.getElementById("fall-title").textContent = event.test ? "[시험] 낙상 감지" : "낙상 감지";
        picture.hidden = true; picture.removeAttribute("src");
        root.getElementById("image-status").textContent = event.test ? "AI 판정이 아닌 수동 통신 시험입니다. 시험 경보는 30초 후 자동 해제됩니다." : "";
        root.getElementById("show-image").hidden = !event.snapshot_available;
        root.getElementById("fall-camera").textContent = event.test ? "Dahua 화면으로 Pi5 → Pi4 경보 연결을 시험합니다." : `${event.camera_id === "dahua" ? "Dahua 낙상 카메라" : event.camera_id}에서 낙상이 감지되었습니다.`;
        root.getElementById("fall-time").textContent = new Date(event.timestamp).toLocaleString("ko-KR");
        panel.hidden = false;
      }
    } catch (_) { /* Other dashboard functions must remain independent. */ }
    finally { clearTimeout(timeout); setTimeout(poll, 2000); }
  }
  poll();
})();
