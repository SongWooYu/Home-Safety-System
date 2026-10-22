/* Read-only incident review. One direct Pi5 peer; no video proxy or canvas. */
(() => {
  "use strict";
  const $ = id => document.getElementById(id);
  const date = value => new Date(value).toLocaleString("ko-KR", {hour12:false});
  let records = [], selected = new URLSearchParams(location.search).get("event"), signature = "", imageKey = "", imageRequest = null, imageURL = null;
  function selectEvent(id) {
    selected = id;
    const url = new URL(location.href);
    if (id) url.searchParams.set("event", id); else url.searchParams.delete("event");
    history.replaceState(null, "", url);
    renderList(); renderSelected();
  }
  function renderSelected() {
    const event = records.find(item => item.event_id === selected);
    const key = event ? `${event.event_id}:${event.snapshot_available}` : `missing:${selected}`;
    if (key === imageKey) return;
    imageKey = key;
    if (imageRequest) imageRequest.abort();
    if (imageURL) URL.revokeObjectURL(imageURL);
    imageURL = null;
    const image = $("snapshot");
    image.onload = image.onerror = null; image.hidden = true; image.removeAttribute("src");
    $("snapshot-message").hidden = false;
    if (!event) {
      $("event-title").textContent = selected ? "선택한 기록이 없습니다" : "기록을 선택해 주세요";
      $("event-time").textContent = "오래된 기록은 50건 초과 또는 웹 서비스 재시작으로 삭제될 수 있습니다.";
      $("snapshot-message").textContent = selected ? "삭제된 사건을 다른 사건의 사진으로 대체하지 않습니다." : "아래 사건 목록에서 확인할 기록을 선택하세요.";
      $("event-detail").textContent = "오른쪽 영상은 현재 상황을 별도로 보여줍니다.";
      return;
    }
    $("event-title").textContent = event.test ? "[수동 시험] 낙상 경보 전달" : "낙상 감지 · 확정";
    $("event-time").textContent = date(event.timestamp);
    $("event-detail").textContent = event.test ? "AI 낙상 판정이 아닌 수동 통신 시험입니다. 사진은 시험 시점의 분석 프레임입니다." : `${event.camera_id} · 낙상 확정 판정 시점의 분석 프레임입니다.`;
    $("snapshot-message").textContent = event.snapshot_available ? "발생 당시 캡처를 가져옵니다…" : "당시 캡처가 없거나 보관 기간이 만료되었습니다. 사건 시각은 목록에서 확인할 수 있습니다.";
    if (!event.snapshot_available) return;
    // Only one bounded image request/blob: cancel on selection change and
    // never put an older image under the newly selected event's timestamp.
    const controller = new AbortController(); imageRequest = controller;
    const timer = setTimeout(()=>controller.abort(),5000);
    (async()=>{
      try {
        const response = await fetch(`/api/fall-notices/${encodeURIComponent(event.event_id)}/snapshot.jpg`,{cache:"no-store",signal:controller.signal});
        if (!response.ok) throw Error();
        const blob = await response.blob();
        if (imageKey !== key || controller.signal.aborted) return;
        if (blob.size > 512000 || !blob.type.startsWith("image/jpeg")) throw Error();
        imageURL = URL.createObjectURL(blob); image.src = imageURL;
        await image.decode();
        if (imageKey !== key || controller.signal.aborted) return;
        image.hidden = false; $("snapshot-message").hidden = true;
      } catch (_) {
        if (imageKey === key && imageRequest === controller) $("snapshot-message").textContent = "캡처 만료·Pi5 재시작·연결 오류로 사진을 불러올 수 없습니다. 현재 영상과는 별개입니다.";
      } finally { clearTimeout(timer); }
    })();
  }
  function renderList() {
    const filter = $("filter").value;
    const visible = records.filter(e => filter === "all" || (filter === "test" ? e.test : !e.test));
    const fragment = document.createDocumentFragment();
    for (const event of visible) {
      const button = document.createElement("button"); button.className = "event-row"; button.type = "button";
      button.setAttribute("aria-pressed", String(event.event_id === selected));
      const time = document.createElement("time"); time.dateTime = event.timestamp; time.textContent = date(event.timestamp);
      const title = document.createElement("span"); title.textContent = event.test ? "[수동 시험] 낙상 확정 전송" : `${event.camera_id} · 낙상 확정`;
      const info = document.createElement("small"); info.textContent = event.snapshot_available ? "캡처 확인" : "사진 없음 / 만료";
      button.append(time,title,info); button.addEventListener("click", () => selectEvent(event.event_id)); fragment.append(button);
    }
    $("history-list").replaceChildren(fragment); $("history-empty").hidden = visible.length !== 0;
    $("count").textContent = `${records.length} / 50`;
  }
  $("filter").addEventListener("change", renderList);
  async function pollHistory() {
    if (!document.hidden) {
      try {
        const response = await fetch("/api/fall-history", {cache:"no-store",signal:AbortSignal.timeout(4000)});
        if (!response.ok) throw Error();
        const data = await response.json();
        $("history-status").textContent = data.connected ? "MQTT 연결 · 새 확정 사건을 자동으로 갱신합니다." : "MQTT 연결 끊김 · 보관된 기록이며 새 사건 수신은 확인할 수 없습니다.";
        const next = JSON.stringify([data.epoch, data.events]);
        if (next !== signature) {
          signature = next; records = data.events.slice(0,50);
          if (!selected && records.length) selectEvent(records[0].event_id);
          else { renderList(); renderSelected(); }
        }
      } catch (_) { $("history-status").textContent = "Pi4 기록 갱신 실패 · 마지막 조회 결과입니다."; }
    }
    setTimeout(pollHistory,3000);
  }
  async function pollCurrent() {
    if (!document.hidden) {
      try {
        const response = await fetch("/api/fall-review/current", {cache:"no-store",signal:AbortSignal.timeout(4000)});
        if (!response.ok) throw Error();
        const data = await response.json();
        if (!data.available) throw Error();
        const states = {confirmed:"현재 낙상 경보",suspected:"현재 낙상 의심",normal:"현재 확정 경보 없음"};
        $("current-state").textContent = states[data.fall_state] || "현재 판정 확인 필요";
        $("current-state").dataset.state = data.fall_state;
        $("current-detail").textContent = `${data.person_count ?? "?"}명 · ${data.analysis_label || ""} · ${data.analysis_detail || ""}`;
        $("current-time").textContent = `${date(data.checked_at)} 확인 · Pi5 분석 상태 (과거 사건의 해제 여부가 아닙니다)`;
      } catch (_) {
        $("current-state").textContent = "현재 AI 상태 확인 불가"; $("current-state").dataset.state = "unknown";
        $("current-detail").textContent = "Pi5 또는 카메라 연결을 확인해 주세요. 연결 실패를 정상 상태로 표시하지 않습니다.";
        $("current-time").textContent = "현재 영상의 연결 상태와 AI 분석 상태는 별도로 확인합니다.";
      }
    }
    setTimeout(pollCurrent,2500);
  }

  const video = $("live-video");
  let active = null, retry = null, retryDelay = 2000, gone = false;
  function removeSession(url) {
    if (url) fetch(url,{method:"DELETE",keepalive:true,signal:AbortSignal.timeout(10000)}).catch(()=>{});
  }
  function closePeer() {
    clearTimeout(retry); retry = null;
    const old = active; active = null;
    if (old) { clearTimeout(old.deadline); clearInterval(old.monitor); old.pc.close(); removeSession(old.session); }
    video.pause(); video.srcObject = null; video.hidden = true; $("video-message").hidden = false;
  }
  function fail(peer, message) {
    if (active !== peer) return;
    closePeer(); $("transport").textContent = message;
    $("video-message").textContent = "Pi5 직접 연결 실패. 같은 LAN 또는 Tailscale 연결을 확인하세요. Pi4 영상 중계로 전환하지 않습니다.";
    if (!document.hidden && !gone) { retry = setTimeout(connect,retryDelay); retryDelay = Math.min(30000,retryDelay*2); }
  }
  async function connect() {
    closePeer(); if (document.hidden || gone) return;
    $("transport").textContent = "Pi5 WebRTC 직접 연결 중…"; $("video-message").textContent = "연결 중…";
    if (!window.RTCPeerConnection) { $("transport").textContent = "이 브라우저는 WebRTC를 지원하지 않습니다."; return; }
    const pc = new RTCPeerConnection();
    const peer = {pc, session:null, frames:-1, advanced:performance.now(),monitor:null,deadline:null}; active = peer;
    peer.deadline = setTimeout(()=>fail(peer,"연결 시간 초과 · 자동 재시도"),14000);
    pc.ontrack = event => { if (active === peer) { video.srcObject = event.streams[0] || new MediaStream([event.track]); video.play().catch(()=>{}); } };
    pc.onconnectionstatechange = () => { if (pc.connectionState === "failed") fail(peer,"영상 연결 끊김 · 자동 재시도"); };
    try {
      pc.addTransceiver("video",{direction:"recvonly"});
      await pc.setLocalDescription(await pc.createOffer());
      await new Promise(resolve=>{
        if (pc.iceGatheringState === "complete") return resolve();
        const timer = setTimeout(done,2000);
        function done() { clearTimeout(timer); pc.removeEventListener("icegatheringstatechange",change); resolve(); }
        function change() { if (pc.iceGatheringState === "complete") done(); }
        pc.addEventListener("icegatheringstatechange",change);
      });
      if (active !== peer) return;
      const response = await fetch("/api/fall-review/whep",{method:"POST",headers:{"Content-Type":"application/sdp"},body:pc.localDescription.sdp,signal:AbortSignal.timeout(10000)});
      const location = response.headers.get("Location");
      if (location && /^\/api\/fall-review\/whep\/[a-zA-Z0-9_-]{1,80}$/.test(location)) peer.session = location;
      if (active !== peer) { removeSession(peer.session); return; }
      if (!response.ok || !peer.session) throw Error("signaling");
      await pc.setRemoteDescription({type:"answer",sdp:await response.text()});
      if (active !== peer) return;
      // Check decoded-frame progress, not just ICE connected or video autoplay.
      peer.monitor = setInterval(async()=>{
        if (active !== peer) return;
        try {
          const stats = await pc.getStats();
          if (active !== peer) return;
          for (const stat of stats.values()) {
            if (stat.type === "inbound-rtp" && (stat.kind === "video" || stat.mediaType === "video")) {
              if ((stat.framesDecoded || 0) > Math.max(peer.frames,0)) {
                peer.frames = stat.framesDecoded; peer.advanced = performance.now();
                clearTimeout(peer.deadline); retryDelay = 2000;
                video.hidden = false; $("video-message").hidden = true;
                $("transport").textContent = "WebRTC 수신 중 · Pi5 직접 연결 · 원본 영상";
              }
            }
          }
          if (peer.frames > 0 && performance.now()-peer.advanced > 6000) fail(peer,"영상 정지 감지 · 자동 재연결");
        } catch (_) { fail(peer,"영상 상태 확인 실패 · 자동 재연결"); }
      },1500);
    } catch (_) { fail(peer,"WebRTC 연결 실패 · 자동 재시도"); }
  }
  $("reconnect").addEventListener("click",()=>{retryDelay=2000;connect();});
  document.addEventListener("visibilitychange",()=>{
    if (document.hidden) { closePeer(); $("transport").textContent = "백그라운드 · 영상 연결 해제"; }
    else connect();
  });
  window.addEventListener("pagehide",()=>{gone=true;closePeer();});
  window.addEventListener("pageshow",event=>{if (event.persisted) {gone=false;connect();}});
  renderSelected(); pollHistory(); pollCurrent(); connect();
})();
