(() => {
  const buttons = [...document.querySelectorAll("[data-fall-stage]")];
  let busy = false, sentId = null;
  buttons.forEach(button => button.addEventListener("click", async () => {
    if (busy) return;
    busy = true; buttons.forEach(b => { b.disabled = true; });
    setText("fall-test-status", "시험 이벤트를 보내고 있습니다…");
    try {
      const data = await requestJSON("/api/fall-test", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({stage:button.dataset.fallStage})});
      sentId = data.event.event_id;
      setText("fall-test-status", `[시험] ${eventLabels[data.event.event_type]} · MQTT 브로커 전달 확인`);
    } catch (error) { setText("fall-test-status", error.message); }
    finally { setTimeout(() => { busy = false; buttons.forEach(b => { b.disabled = false; }); }, 1000); }
  }));
  async function poll() {
    try {
      if (!document.hidden) {
        const data = await requestJSON("/api/fall-test");
        const state = data.pi4_state;
        const stages = {normal:"해제/대기", suspected:"의심", confirmed:"확정", cancelled:"취소"};
        const test = stages[state?.camera_states?.["manual-test"]] || "대기";
        setText("fall-test-received", data.connected
          ? state ? `Pi4 수신 · 시험 ${test} / 전체 ${state.state === "alarm" ? "경보 중" : state.state === "suspected" ? "의심" : "경보 없음"} · ${clock(state.timestamp)}${sentId && state.event_id === sentId ? " · 이번 요청 수신 확인" : " (마지막 수신)"}` : "MQTT 연결됨 · Pi4 자동화 응답 대기"
          : "Pi4 MQTT 연결 끊김 · 수신 상태를 확인할 수 없습니다.");
      }
    } catch (_) { setText("fall-test-received", "Pi4 수신 상태 조회 실패"); }
    setTimeout(poll, 1500);
  }
  poll();
})();
