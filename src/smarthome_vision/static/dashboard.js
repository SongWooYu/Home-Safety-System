"use strict";

const $ = id => document.getElementById(id);
const setText = (id, value) => { if ($(id)) $(id).textContent = value; };
const number = value => Number(value || 0).toFixed(1);
const percent = value => `${number(Number(value) * 100)}%`;
const clock = value => new Date(value).toLocaleTimeString("ko-KR", {hour12:false});
let latestStatus = null;
let latestFall = null;
let acknowledgedFall = null;
let lastStatusAt = 0;
let lastEventsAt = 0;
let lastEventSignature = "";
let lastTick = Date.now();
const previousOnline = new Map();
let activeView = "monitor";
$("theme-select").value = window.visionTheme.get();
$("theme-select").addEventListener("change", event => window.visionTheme.set(event.target.value));

async function requestJSON(url, options = {}, timeout = 5000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(url, {...options, cache:"no-store", signal:controller.signal});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `요청 실패 (${response.status})`);
    return data;
  } finally { clearTimeout(timer); }
}

let audioBusy = false;
async function audioRequest(path, payload, message) {
  if (audioBusy) return;
  audioBusy = true;
  $("audio-test").disabled = $("audio-volume-apply").disabled = true;
  setText("audio-status", "Pi4에 명령을 보내고 있습니다…");
  try {
    await requestJSON(path, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(payload)});
    setText("audio-status", message + " · MQTT 전달 확인, 실제 소리는 현장에서 확인해 주세요.");
  } catch (error) { setText("audio-status", error.message); }
  finally {
    setTimeout(() => {
      audioBusy = false;
      $("audio-test").disabled = $("audio-volume-apply").disabled = !latestStatus?.mqtt_connected;
    }, 3000);
  }
}
$("audio-volume").addEventListener("input", event => setText("audio-volume-value", `${event.target.value}%`));
$("audio-test").addEventListener("click", () => audioRequest("/api/audio/test", {}, "음성 1회 재생 명령을 보냈습니다"));
$("audio-volume-apply").addEventListener("click", () => {
  const volume = Number($("audio-volume").value);
  audioRequest("/api/audio/volume", {volume}, `음량 ${volume}% 적용 명령을 보냈습니다`);
});

function stopStream(img) {
  window.visionStreams.stop(img);
}
function connectStream(img) {
  window.visionStreams.start(img);
}
function reconnectStreams() {
  document.querySelectorAll(".stream").forEach(connectStream);
}
$("reconnect").addEventListener("click", reconnectStreams);
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    document.querySelectorAll(".stream").forEach(stopStream);
  } else { reconnectStreams(); }
});
window.addEventListener("pageshow", reconnectStreams);
window.addEventListener("online", reconnectStreams);

function switchView(view) {
  if (!["monitor", "face-enrollment", "event-panel"].includes(view)) view = "monitor";
  if (activeView === "face-enrollment" && view !== activeView && enrollmentId) {
    requestJSON(`/api/faces/enrollment/${enrollmentId}`, {method:"DELETE"}).catch(() => {});
  }
  activeView = view;
  closeExpanded();
  document.querySelectorAll(".tab-panel").forEach(panel => { panel.hidden = panel.id !== view; });
  document.querySelectorAll("[data-monitor-only]").forEach(panel => { panel.hidden = view !== "monitor"; });
  document.querySelectorAll('[role="tab"]').forEach(tab => {
    const selected = tab.getAttribute("aria-controls") === view;
    tab.classList.toggle("selected", selected);
    tab.setAttribute("aria-selected", String(selected));
    tab.tabIndex = selected ? 0 : -1;
  });
  const headings = {
    monitor:["비전 테스트 스테이션", "낙상 판정과 얼굴 인식을 한곳에서 확인하세요."],
    "face-enrollment":["얼굴 등록", "거울 미리보기를 보며 본인 기준 좌우로 고개를 돌려 주세요."],
    "event-panel":["감지 기록", "최근 낙상 의심·확정과 얼굴 인식 이벤트를 확인하세요."]
  };
  setText("page-title", headings[view][0]); setText("page-subtitle", headings[view][1]);
  reconnectStreams();
}
document.querySelectorAll('[role="tab"], [data-view-link]').forEach(link => link.addEventListener("click", event => {
  event.preventDefault(); history.pushState(null, "", link.getAttribute("href"));
  switchView(location.hash.slice(1));
}));
document.querySelector('[role="tablist"]').addEventListener("keydown", event => {
  if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  const index = tabs.indexOf(document.activeElement);
  if (index < 0) return;
  event.preventDefault();
  const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1
    : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
  tabs[next].focus(); tabs[next].click();
});
window.addEventListener("hashchange", () => switchView(location.hash.slice(1)));

function closeExpanded() {
  document.querySelectorAll(".camera-card.expanded").forEach(card => card.classList.remove("expanded"));
  document.body.classList.remove("has-expanded");
  document.querySelectorAll(".expand").forEach(button => {
    button.textContent = "⛶";
    button.setAttribute("aria-expanded", "false");
  });
}
document.querySelectorAll(".expand").forEach(button => button.addEventListener("click", () => {
  const card = $(`camera-${button.dataset.camera}`);
  const wasExpanded = card.classList.contains("expanded");
  closeExpanded();
  if (!wasExpanded) {
    card.classList.add("expanded");
    document.body.classList.add("has-expanded");
    button.textContent = "×";
    button.setAttribute("aria-expanded", "true");
  }
}));
document.addEventListener("keydown", event => { if (event.key === "Escape") closeExpanded(); });

function renderCamera(camera) {
  const id = camera.camera_id;
  if (!$(`online-${id}`)) return;
  const online = Boolean(camera.online);
  setText(`online-${id}`, online ? "연결됨" : "연결 끊김");
  $(`online-${id}`).className = `pill ${online ? "online" : "offline"}`;
  setText(`fps-${id}`, number(camera.capture_fps));
  setText(`buffer-${id}`, `${Math.round(camera.source_buffer_age_ms || 0)} ms`);
  if (camera.face_enabled) {
    const names = [...new Set((camera.recognized_faces || []).filter(f => f.registered).map(f => f.name))];
    if (camera.unknown_faces) names.push(`미등록 ${camera.unknown_faces}명`);
    setText(`people-${id}`, names.join(" · ") || "얼굴을 기다리는 중");
  } else {
    setText(`people-${id}`, camera.person_count ? `사람 ${camera.person_count}명 감지` : "사람 대기");
  }
  if (previousOnline.get(id) === false && online) connectStream($(`stream-${id}`));
  previousOnline.set(id, online);
}

function setAlarm(tone, title, detail, symbol = "◎") {
  $("alarm-banner").dataset.tone = tone;
  setText("alarm-title", title);
  setText("alarm-detail", detail);
  setText("alarm-symbol", symbol);
}

function renderAlarm(data) {
  const camera = data.cameras.find(c => c.pose_enabled);
  const analysis = camera?.analysis;
  const state = camera?.fall_state;
  const isCurrent = lastStatusAt > Date.now() - 4000;
  const validSource = isCurrent && camera?.online && !camera.error && !camera.edgefall_error;
  if (!isCurrent) {
    setAlarm("error", "실시간 상태 연결 끊김", "마지막 표시값을 현재 판정으로 사용하지 마세요. 자동으로 재연결합니다.", "!");
  } else if (!camera?.online) {
    setAlarm("error", "낙상 카메라 연결 확인", "새 영상을 받지 못하고 있습니다.", "!");
  } else if (camera.error || camera.edgefall_error) {
    setAlarm("error", "낙상 분석 오류", camera.edgefall_error || camera.error, "!");
  } else if (state === "confirmed") {
    setAlarm("danger", "낙상이 감지되었습니다", "Dahua에서 낙상을 확정했습니다. 영상 속 사람의 상태를 확인해 주세요.", "!");
  } else if (state === "suspected") {
    setAlarm("warning", "낙상 의심 · 확인 중", "급격한 움직임을 감지했습니다. 자세 변화가 이어지는지 확인하고 있습니다.", "!");
  } else if (state === "recovering") {
    setAlarm("warning", "낙상 후 움직임 확인 중", "현재 회복 동작을 관찰하고 있습니다. 최근 감지 기록을 확인해 주세요.", "↗");
  } else if (analysis?.code === "analyzing") {
    setAlarm("normal", "현재 낙상 경보 없음", "사람의 움직임을 분석하고 있습니다. 낙상을 확정하면 이 영역이 빨간색으로 바뀝니다.", "✓");
  } else {
    setAlarm(analysis?.code === "pose_needed" ? "warning" : "waiting", analysis?.label || "상태 확인 중", analysis?.detail || "분석 상태를 불러오는 중입니다.");
  }
  const badge = $("video-alarm");
  if (badge) {
    badge.hidden = !validSource || !["confirmed", "suspected", "recovering"].includes(state);
    badge.className = `video-alarm ${state === "confirmed" ? "" : "suspected"}`;
    badge.textContent = state === "confirmed" ? "낙상 감지" : state === "recovering" ? "회복 확인 중" : "낙상 의심";
    $("video-dahua").classList.toggle("has-alarm", !badge.hidden);
  }
  const unacknowledged = latestFall && latestFall.event_id !== acknowledgedFall;
  $("last-fall").hidden = !unacknowledged;
  if (unacknowledged) setText("last-fall-text", `${clock(latestFall.timestamp)} · Dahua · 확인할 때까지 이 기록을 유지합니다.`);
  if (analysis) {
    setText("analysis-title", analysis.label);
    setText("analysis-detail", analysis.detail);
    setText("motion-score", analysis.motion_score == null ? "—" : percent(analysis.motion_score));
    setText("motion-score-note", analysis.motion_score == null ? "판정할 관절 데이터 없음" : analysis.code === "collecting" ? "초기 관측 점수" : "최종 경보와 별도");
    setText("decision-label", analysis.decision_label || "판정 확인 중");
    const profileTag = camera?.edgefall_profile?.endsWith("units-separated-v6") ? "v6 · 입력 단위 수정 · " : "";
    setText("decision-gate", profileTag + (analysis.motion_score == null
      ? "확정에는 모델 양성과 동작 조건이 모두 필요합니다."
      : `모델 ${analysis.temporal_positive ? "양성" : "기준 미충족"} · 기준 75% 연속 3회 · 동작 후보 ${analysis.geometry_candidate ? "충족" : "미충족"}`));
    setText("diagnostic-health", camera?.diagnostic_log_error
      ? `기록 오류: ${camera.diagnostic_log_error}`
      : camera?.diagnostic_logging ? `검증 수치 기록 중 · 누락 ${camera.diagnostic_records_dropped || 0}건 · 영상 저장 없음` : "검증 기록 꺼짐");
    $("analysis-dot").style.background = analysis.code === "pose_needed" ? "#bd8b2e" : "#087f70";
  }
  setText("diag-fps", `${number(camera?.pose_effective_fps)} FPS`);
  setText("diag-latency", `${number(camera?.pose_inference_ms)} / ${number(camera?.pose_inference_p95_ms)} ms`);
  setText("diag-keypoints", percent(camera?.pose_visible_keypoint_ratio || 0));
  setText("diag-track", camera?.edgefall_best_track_id == null ? "추적 없음" : `#${camera.edgefall_best_track_id}`);
  setText("diag-frames", analysis?.observed_frames ? `${analysis.observed_frames}프레임` : "—");
}

function renderStatus(data) {
  latestStatus = data;
  lastStatusAt = Date.now();
  $("connection-warning").hidden = true;
  setText("refresh-time", `최근 갱신 ${clock(Date.now())}`);
  setText("registered-count", `${data.registered_people || 0}명 등록`);
  setText("mqtt-label", data.mqtt_connected ? "Pi4 경보 연결됨" : "Pi4 경보 연결 대기");
  setText("mqtt-detail", data.mqtt_connected ? "MQTT 브로커 연결됨" : "이 화면에서 감지는 계속됩니다");
  $("mqtt-dot").classList.toggle("connected", data.mqtt_connected);
  if (!audioBusy) $("audio-test").disabled = $("audio-volume-apply").disabled = !data.mqtt_connected;
  setText("diag-mqtt", `${data.fall_events_publish_mqtt ? "발행 활성" : "발행 비활성"} / ${data.mqtt_connected ? "연결됨" : "연결 끊김"}`);
  setText("diag-mqtt-rejected", String(data.mqtt_rejected_events || 0));
  const view = data.cameras.find(c => c.face_enabled)?.camera_view;
  setText("diag-camera", view ? `${view.sensor_size.join(" × ")} · 최대 화각` : "—");
  data.cameras.forEach(renderCamera);
  renderAlarm(data);
}

const eventLabels = {fall_confirmed:"낙상 확정", fall_suspected:"낙상 의심", fall_cleared:"낙상 상태 해제", person_detected:"사람 감지", person_cleared:"사람 없음"};
function renderEvents(events) {
  // Preserve a short confirmed event even if the live state recovered between polls.
  const fall = events.find(e => e.event_type === "fall_confirmed" && !e.details?.shadow && !e.details?.test);
  if (fall && (!latestFall || Date.parse(fall.timestamp) > Date.parse(latestFall.timestamp))) latestFall = fall;
  const signature = events.map(e => e.event_id).join(",");
  if (signature !== lastEventSignature) {
    lastEventSignature = signature;
    const list = $("event-list");
    list.replaceChildren();
    setText("event-count", `${events.length}건`);
    for (const event of events.slice(0, 24)) {
      const row = document.createElement("div");
      row.className = `event-row ${event.event_type === "fall_confirmed" ? "danger" : event.event_type === "fall_suspected" ? "warning" : ""}`;
      const indicator = document.createElement("span"); indicator.className = "event-indicator";
      const copy = document.createElement("div");
      const title = document.createElement("strong"); title.textContent = (event.details?.test ? "[시험] " : "") + (eventLabels[event.event_type] || event.event_type);
      const detail = document.createElement("small"); detail.textContent = `${event.camera_id === "dahua" ? "Dahua" : "Camera Module 3"}${event.details?.track_id ? ` · 사람 #${event.details.track_id}` : ""}${event.details?.reason === "track_lost" ? " · 추적 소실로 상태 해제" : ""}${event.details?.confirmation_policy ? ` · 모델 ${percent(event.confidence || 0)} · ${event.details.temporal_positive ? "모델 양성" : "모델 미동의"}` : ""}`;
      const time = document.createElement("time"); time.dateTime = event.timestamp; time.textContent = clock(event.timestamp);
      if (event.details?.test) detail.textContent = "수동 MQTT 시험 · AI 판정 아님 · Dahua 현재 화면";
      copy.append(title, detail);
      if (event.details?.snapshot?.id) {
        const link = document.createElement("a"); link.textContent = "캡처 보기 ↗";
        link.href = `/api/events/${encodeURIComponent(event.event_id)}/snapshot.jpg`; link.target = "_blank"; link.rel = "noopener";
        copy.append(link);
      }
      row.append(indicator, copy, time); list.append(row);
    }
    if (!events.length) { const p = document.createElement("p"); p.className = "empty"; p.textContent = "아직 감지 이벤트가 없습니다."; list.append(p); }
  }
  if (latestStatus) renderAlarm(latestStatus);
}
$("ack-fall").addEventListener("click", () => {
  acknowledgedFall = latestFall?.event_id;
  $("last-fall").hidden = true; // Display acknowledgement only; never cancels MQTT alarms.
});

function updateGuide(state) {
  // Raw camera yaw and a mirror preview have opposite horizontal directions.
  const direction = state.display_direction || ({front:"front", right:"left", left:"right"})[state.direction];
  const titles = {front:"정면을 바라봐 주세요", right:"내 오른쪽으로 고개를 돌려 주세요 →", left:"← 내 왼쪽으로 고개를 돌려 주세요"};
  $("enrollment-guide").dataset.direction = direction;
  setText("guide-image-title", titles[direction]);
  setText("guide-title", titles[direction]);
  setText("guide-detail", state.message);
  setText("guide-step", `실제 방향 확인 ${state.step + 1} / 3 · 남은 시간 ${state.remaining_seconds}초`);
  document.querySelectorAll(".guide-steps span").forEach(el => el.classList.toggle("active", Number(el.dataset.step) === state.step));
  const value = state.progress;
  $("guide-progress-fill").style.width = `${value}%`;
  $("guide-progress").setAttribute("aria-valuenow", String(value));
  setText("face-status", `유효 특징: 정면 ${state.samples.front}/${state.required} · 내 왼쪽 ${state.samples.right}/${state.required} · 내 오른쪽 ${state.samples.left}/${state.required}`);
}

let enrollmentId = null;
$("face-cancel").addEventListener("click", async () => {
  if (!enrollmentId) return;
  try { await requestJSON(`/api/faces/enrollment/${enrollmentId}`, {method:"DELETE"}); }
  catch (error) { setText("face-status", error.message); }
});

$("face-form").addEventListener("submit", async event => {
  event.preventDefault();
  const name = $("face-name").value.trim();
  if (!name) { $("face-name").focus(); return; }
  const button = $("face-submit");
  button.disabled = true; $("face-name").disabled = true;
  $("face-cancel").hidden = false;
  button.textContent = "촬영 중…";
  $("face-status").className = "form-status";
  setText("face-status", "위 얼굴 그림과 화살표를 따라 고개를 움직여 주세요.");
  try {
    let state = await requestJSON("/api/faces/enrollment", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({camera_id:$("face-camera").value, name})
    });
    enrollmentId = state.id;
    const deadline = performance.now() + 60000;
    while (state.status === "capturing") {
      updateGuide(state);
      if (performance.now() > deadline) throw new Error("등록 응답 대기 시간이 초과되었습니다.");
      await new Promise(resolve => setTimeout(resolve, 250));
      state = await requestJSON(`/api/faces/enrollment/${enrollmentId}`);
    }
    updateGuide(state);
    if (state.status !== "completed") throw new Error(state.message);
    const person = state.person;
    setText("guide-title", `${person.name}님 등록 완료`);
    setText("guide-step", "등록 완료");
    setText("guide-detail", "이제 고개를 좌우로 움직이며 영상 속 이름이 유지되는지 확인해 보세요.");
    setText("face-status", `정면 ${person.samples.front}장 · 양쪽 ${person.samples.left}/${person.samples.right}장의 특징을 등록했습니다.`);
    $("face-status").className = "form-status success";
  } catch (error) {
    setText("guide-title", "다시 촬영해 주세요");
    setText("guide-step", "등록 실패");
    setText("guide-detail", "아래 이유를 확인하고 다시 시작해 주세요.");
    setText("face-status", error.name === "AbortError" ? "서버 응답 시간이 초과되었습니다. 등록자 목록을 확인한 뒤 다시 시도해 주세요." : error.message);
    $("face-status").className = "form-status error";
  } finally {
    if (enrollmentId) {
      await requestJSON(`/api/faces/enrollment/${enrollmentId}`, {method:"DELETE"}).catch(() => {});
    }
    enrollmentId = null;
    $("face-cancel").hidden = true;
    button.disabled = false; $("face-name").disabled = false;
    button.textContent = "자동 다각도 등록 →";
    $("enrollment-guide").dataset.direction = "front";
  }
});

async function refreshFaces() {
  const token = $("face-token").value.trim();
  if (token) {
    await requestJSON("/api/faces/admin/session", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({token})});
    $("face-token").value = "";
  }
  const data = await requestJSON("/api/faces");
  setText("face-admin-status", `등록자 ${data.people.length}명 · 관리 인증 유지 중`);
  $("face-list").replaceChildren();
  for (const person of data.people) {
    const row = document.createElement("div"); row.className = "face-row";
    const name = document.createElement("span"); name.textContent = person.name;
    const remove = document.createElement("button"); remove.className = "button"; remove.type = "button"; remove.textContent = "삭제";
    remove.addEventListener("click", async () => {
      if (!confirm(`${person.name}님의 얼굴 정보를 삭제할까요?`)) return;
      try { await requestJSON(`/api/faces/${encodeURIComponent(person.id)}`, {method:"DELETE"}); await refreshFaces(); }
      catch (error) { setText("face-admin-status", error.message); }
    });
    row.append(name, remove); $("face-list").append(row);
  }
}
$("face-admin-load").addEventListener("click", () => refreshFaces().catch(error => setText("face-admin-status", error.message)));

async function poll() {
  if (Date.now() - lastTick > 6000 && !document.hidden) reconnectStreams();
  lastTick = Date.now();
  if (!document.hidden) {
    const jobs = [requestJSON("/api/status").then(renderStatus)];
    if (Date.now() - lastEventsAt >= 900) {
      lastEventsAt = Date.now();
      jobs.push(requestJSON("/api/events").then(renderEvents));
    }
    await Promise.allSettled(jobs);
    if (Date.now() - lastStatusAt > 4000) {
      $("connection-warning").hidden = false;
      setText("refresh-time", "연결 재시도 중");
      setText("mqtt-label", "Pi4 연결 상태 미확인");
      setText("mqtt-detail", "Pi5 상태 연결 끊김");
      $("mqtt-dot").classList.remove("connected");
      if (latestStatus) renderAlarm(latestStatus);
    }
  }
  setTimeout(poll, 500);
}
switchView(location.hash.slice(1));
poll();
