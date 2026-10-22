/* Independent control panel; collaborator sensor cards/chart stay untouched. */
(() => {
  "use strict";
  if (document.getElementById("home-safety-device-control")) return;
  const host=document.createElement("section");host.id="home-safety-device-control";
  const root=host.attachShadow({mode:"open"});
  root.innerHTML=`<style>
    :host{display:block;margin:24px 0;color:#e8edf7;font:14px/1.5 system-ui,sans-serif}
    .panel{padding:20px;border:1px solid #42516b;border-radius:14px;background:#202b3b}h2{font-size:19px;margin:0 0 12px}.top{display:flex;gap:12px;justify-content:space-between;align-items:center;flex-wrap:wrap}.modes{display:flex;gap:8px}button{border:1px solid #61718c;background:#33445f;color:white;border-radius:8px;padding:10px 15px;cursor:pointer;font:inherit}button[aria-pressed=true]{background:#225ec3;border-color:#8db4ff}button:disabled{opacity:.45;cursor:not-allowed}button:focus-visible{outline:3px solid #b5cfff;outline-offset:2px}.devices{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin-top:16px}.device{padding:14px;background:#152031;border-radius:10px}.device strong{display:block;margin-bottom:12px}.buttons{display:flex;gap:8px}.buttons button{flex:1}.status{min-height:24px;color:#cad6e8}.result{min-height:24px;margin:14px 0 0;color:#b5d3ff}.hint,.last{color:#acbbd1;font-size:12px}.last{min-height:38px;margin:10px 0 0}p{margin:8px 0}
    </style><div class="panel"><div class="top"><h2>시연 · 기기 제어</h2><div class="modes"><button id="auto" type="button">자동 모드</button><button id="manual" type="button">수동 모드</button></div></div><p id="status" class="status" role="status">제어 엔진 확인 중…</p><p class="hint">수동 모드에서는 조명·에어컨·커튼·환풍기의 센서 자동 제어를 멈춥니다. 가스·낙상 안전 경보는 유지됩니다. 센서 측정값은 조작하지 않습니다.</p><div id="devices" class="devices"></div><p id="result" class="result" role="status" aria-live="polite"></p><p class="hint">아래 상태는 마지막 전송 명령이며, 실제 기기의 동작 완료 응답이 아닙니다. 모드는 브라우저를 닫아도 유지되고 Pi4 재부팅 시 자동 모드로 돌아갑니다.</p></div>`;
  const chart=document.getElementById("chartBox");
  if(chart) chart.after(host);else document.body.append(host);
  const $=id=>root.getElementById(id);
  const controls=[
    ["livingroom","light","거실 조명","ON","OFF"],
    ["livingroom","aircon","거실 에어컨","ON","OFF"],
    ["livingroom","curtain","거실 커튼","OPEN","CLOSE"],
    ["bathroom","light","화장실 조명","ON","OFF"],
    ["bathroom","fan","화장실 환풍기","ON","OFF"],
    ["kitchen","alarm","부엌 부저","ON","OFF"]];
  let state=null,busy=false;
  for(const [room,device,title,on,off] of controls){
    const box=document.createElement("div");box.className="device";
    const name=document.createElement("strong");name.textContent=title;box.append(name);
    const buttons=document.createElement("div");buttons.className="buttons";
    for(const value of [on,off]){
      const b=document.createElement("button");b.type="button";b.disabled=true;b.dataset.device=device;b.dataset.value=value;
      b.textContent={ON:"켜기",OFF:"끄기",OPEN:"열기",CLOSE:"닫기"}[value];
      b.onclick=()=>post("/api/command",{room,device,value,revision:state.revision},`${title} ${b.textContent} · MQTT 전달 확인`);
      buttons.append(b);
    }
    const last=document.createElement("p");last.className="last";last.id=`last-${room}-${device}`;
    box.append(buttons,last);$("devices").append(box);
  }
  function render(){
    const ready=state?.ready===true;
    for(const mode of ["auto","manual"]){$(mode).disabled=busy||!ready;$(mode).setAttribute("aria-pressed",String(state?.mode===mode));}
    $("status").textContent=!ready?"제어 엔진 또는 MQTT 연결 확인 필요 · 조작 비활성화":state.mode==="manual"?"수동 모드 · 생활기기 자동 명령 차단 중":"자동 모드 · 센서 규칙으로 제어 중";
    root.querySelectorAll(".buttons button").forEach(b=>{b.disabled=busy||!ready||state.mode!=="manual"||(b.dataset.device==="alarm"&&b.dataset.value==="OFF"&&state.gas_active);});
    for(const [room,device] of controls){
      const c=state?.commands?.find(c=>c.room===room&&c.device===device);
      $(`last-${room}-${device}`).textContent=c?`마지막 명령 ${c.value} · ${c.source==="manual"?"수동":"자동"}\n${new Date(c.at*1000).toLocaleTimeString("ko-KR")}`:"아직 전송한 명령 없음";
    }
    if(state?.gas_active) $("status").textContent+=" · 가스 감지 중: 부저 끄기 차단";
  }
  async function refresh(){
    if(busy)return;
    try{const r=await fetch("/api/control-mode",{cache:"no-store",signal:AbortSignal.timeout(5000)});if(!r.ok)throw Error();state=await r.json();}
    catch(_){state=null;}render();
  }
  async function post(url,data,success){
    if(busy||!state?.ready)return;busy=true;render();$("result").textContent="요청 처리 중…";
    try{const r=await fetch(url,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(data),signal:AbortSignal.timeout(8000)});const result=await r.json();if(!r.ok)throw Error(result.error||"요청 실패");$("result").textContent=success;}
    catch(error){$("result").textContent=`확인 필요: ${error.message}`;}
    finally{busy=false;await refresh();}
  }
  $("auto").onclick=()=>post("/api/control-mode",{mode:"auto",revision:state.revision},"자동 모드로 전환했습니다. 다음 센서 입력부터 규칙을 적용합니다.");
  $("manual").onclick=()=>post("/api/control-mode",{mode:"manual",revision:state.revision},"수동 모드로 전환했습니다. 기기 버튼을 조작할 수 있습니다.");
  async function poll(){if(!document.hidden)await refresh();setTimeout(poll,2500);}poll();
})();
