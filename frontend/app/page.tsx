// app/page.tsx
import { mockAi, mockControls, mockDevices, mockEvents, mockSensor } from "@/lib/mock";
import type { RiskEvent, RiskLevel } from "@/lib/types";

const riskStyle: Record<RiskLevel, string> = {
  high: "bg-red-500/15 text-red-400 border-red-500/30",
  medium: "bg-amber-500/15 text-amber-400 border-amber-500/30",
  low: "bg-sky-500/15 text-sky-400 border-sky-500/30",
};

const eventLabel: Record<RiskEvent["event_type"], string> = {
  fall_suspected: "낙상 의심",
  no_response_suspected: "무반응 의심",
  abnormal_posture: "비정상 자세",
};

function Metric({ label, value, unit }: { label: string; value: string; unit?: string }) {
  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/50 p-4">
      <p className="text-xs text-zinc-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-zinc-100">
        {value}
        {unit && <span className="ml-1 text-sm font-normal text-zinc-500">{unit}</span>}
      </p>
    </div>
  );
}

export default function Home() {
  const unchecked = mockEvents.filter((e) => !e.acknowledged).length;

  return (
    <main className="min-h-screen bg-zinc-950 p-6 text-zinc-100">
      <header className="mb-6 flex items-baseline justify-between">
        <div>
          <h1 className="text-xl font-semibold">스마트홈 안전 대시보드</h1>
          <p className="text-sm text-zinc-500">마지막 수신 {mockSensor.timestamp}</p>
        </div>
        {unchecked > 0 && (
          <span className="rounded-full border border-red-500/30 bg-red-500/15 px-3 py-1 text-sm text-red-400">
            확인 필요 {unchecked}건
          </span>
        )}
      </header>

      <section className="mb-6 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Metric label="온도" value={mockSensor.temperature.toFixed(1)} unit="°C" />
        <Metric label="습도" value={String(mockSensor.humidity)} unit="%" />
        <Metric label="조도" value={String(mockSensor.light_level)} unit="lux" />
        <Metric label="재실" value={mockSensor.occupancy ? "있음" : "없음"} />
      </section>

      <section className="mb-6 rounded-lg border border-zinc-800 bg-zinc-900/50 p-4">
        <p className="text-xs text-zinc-500">AI 추천 · 신뢰도 {(mockAi.confidence * 100).toFixed(0)}%</p>
        <p className="mt-1 font-medium">{mockAi.recommended_action}</p>
        <p className="mt-1 text-sm text-zinc-500">
          {mockAi.context} — {mockAi.reason}
        </p>
      </section>

      <section className="mb-6">
        <h2 className="mb-2 text-sm font-medium text-zinc-400">위험 이벤트</h2>
        <ul className="space-y-2">
          {mockEvents.map((e) => (
            <li
              key={e.id}
              className="flex items-center justify-between rounded-lg border border-zinc-800 bg-zinc-900/50 p-4"
            >
              <div>
                <div className="flex items-center gap-2">
                  <span className={`rounded border px-2 py-0.5 text-xs ${riskStyle[e.risk_level]}`}>
                    {e.risk_level.toUpperCase()}
                  </span>
                  <span className="font-medium">{eventLabel[e.event_type]}</span>
                </div>
                <p className="mt-1 text-sm text-zinc-500">
                  {e.state_before} → {e.state_after} · {e.duration_sec}초 · {e.timestamp}
                </p>
              </div>
              <span className="text-sm text-zinc-500">
                {e.acknowledged ? "확인됨" : "미확인"}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <div className="grid gap-6 md:grid-cols-2">
        <section>
          <h2 className="mb-2 text-sm font-medium text-zinc-400">장치 연결</h2>
          <ul className="space-y-2">
            {mockDevices.map((d) => (
              <li
                key={d.device_id}
                className="flex items-center justify-between rounded-lg border border-zinc-800 bg-zinc-900/50 px-4 py-3"
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`size-2 rounded-full ${d.online ? "bg-emerald-400" : "bg-zinc-600"}`}
                  />
                  <span className="text-sm">{d.name}</span>
                  <span className="text-xs text-zinc-600">{d.node}</span>
                </div>
                <span className="text-xs text-zinc-500">{d.last_seen}</span>
              </li>
            ))}
          </ul>
        </section>

        <section>
          <h2 className="mb-2 text-sm font-medium text-zinc-400">제어 이력</h2>
          <ul className="space-y-2">
            {mockControls.map((c) => (
              <li
                key={c.id}
                className="flex items-center justify-between rounded-lg border border-zinc-800 bg-zinc-900/50 px-4 py-3"
              >
                <div className="text-sm">
                  <span className="text-zinc-600">{c.source === "ai" ? "AI" : "수동"}</span>{" "}
                  {c.target_device} · {c.command}
                </div>
                <span
                  className={`text-xs ${c.control_result === "success" ? "text-zinc-500" : "text-red-400"}`}
                >
                  {c.control_result === "success" ? "성공" : "실패"}
                </span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </main>
  );
}