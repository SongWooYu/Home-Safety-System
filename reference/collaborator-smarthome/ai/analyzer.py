"""
생활 패턴 학습 + 이상 감지
사용법: python3 analyzer.py [방이름]   (기본: sim_studio)

학습 결과 → learned_rules 표
이상 날짜 → anomalies 표
"""
import os
import sys
import json
import warnings
import psycopg2
import pandas as pd
import numpy as np

warnings.filterwarnings("ignore", category=UserWarning)

ROOM = sys.argv[1] if len(sys.argv) > 1 else "sim_studio"
LOOKBACK_DAYS = 56          # 최근 며칠 볼지
BIN = "5min"                # 활동 판정 단위

# ── 이상 판정 기준 ──
ACTIVE_HOUR_MIN = 0.15      # 평소 활동률이 이 이상인 시간대만 "활동 시간"으로 봄
QUIET_MEDIUM_H = 2.0        # 활동 시간에 이만큼 조용하면 "주의"
QUIET_HIGH_H = 4.0          # 이만큼 조용하면 "긴급"
NIGHT_START, NIGHT_END = 2, 5   # 새벽 활동 감시 구간
NIGHT_ACTIVE_MIN = 0.25     # 새벽에 이 비율 이상 움직이면 "배회"
DAY_ZSCORE_HIGH = 2.0       # 하루 전체 편차가 이 이상이면 "패턴 이탈"

conn = psycopg2.connect(
    host="localhost",
    dbname=os.getenv("POSTGRES_DB"),
    user=os.getenv("POSTGRES_USER"),
    password=os.getenv("POSTGRES_PASSWORD"),
)
conn.autocommit = True


# ═══════════════════════════════════════════
# 1. 데이터 읽기
# ═══════════════════════════════════════════

def load_motion():
    df = pd.read_sql(
        f"""
        SELECT ts, str_value
        FROM sensor_data
        WHERE room = %s AND metric = 'motion'
          AND ts > now() - interval '{LOOKBACK_DAYS} days'
        ORDER BY ts
        """,
        conn, params=(ROOM,),
    )
    if df.empty:
        return None
    df["ts"] = pd.to_datetime(df["ts"], utc=True).dt.tz_convert("Asia/Seoul")
    df["on"] = (df["str_value"] == "ON").astype(int)
    s = df.set_index("ts")["on"].resample(BIN).max().fillna(0)
    return s


def load_aircon_temps():
    """에어컨 켤 때/끌 때의 온도"""
    cmds = pd.read_sql(
        f"""
        SELECT ts, value FROM command_log
        WHERE room = %s AND device = 'aircon'
          AND ts > now() - interval '{LOOKBACK_DAYS} days'
        ORDER BY ts
        """,
        conn, params=(ROOM,),
    )
    temps = pd.read_sql(
        f"""
        SELECT ts, num_value FROM sensor_data
        WHERE room = %s AND metric = 'temperature'
          AND ts > now() - interval '{LOOKBACK_DAYS} days'
        ORDER BY ts
        """,
        conn, params=(ROOM,),
    )
    if cmds.empty or temps.empty:
        return None, None
    cmds["ts"] = pd.to_datetime(cmds["ts"], utc=True)
    temps["ts"] = pd.to_datetime(temps["ts"], utc=True)
    merged = pd.merge_asof(cmds.sort_values("ts"), temps.sort_values("ts"),
                           on="ts", direction="nearest")
    on_t = merged[merged["value"] == "ON"]["num_value"]
    off_t = merged[merged["value"] == "OFF"]["num_value"]
    return (on_t.mean() if len(on_t) else None,
            off_t.mean() if len(off_t) else None)


# ═══════════════════════════════════════════
# 2. 학습
# ═══════════════════════════════════════════

def learn_baseline(s):
    """요일종류(평일/주말) × 시간대 → 평소 활동률 평균·표준편차"""
    hourly = s.resample("1h").mean()
    df = pd.DataFrame({"ratio": hourly})
    df["hour"] = df.index.hour
    df["weekend"] = (df.index.dayofweek >= 5).astype(int)
    base = df.groupby(["weekend", "hour"])["ratio"].agg(["mean", "std"]).fillna(0)
    base["std"] = base["std"].clip(lower=0.05)
    return base


def learn_sleep_wake(s):
    """하루씩 보고 기상(04시 이후 첫 움직임)·취침(20시 이후 마지막 움직임) 중앙값"""
    wakes, sleeps = [], []
    for day, grp in s.groupby(s.index.date):
        act = grp[grp == 1]
        if act.empty:
            continue
        morning = act[act.index.hour >= 4]
        if not morning.empty:
            t = morning.index[0]
            wakes.append(t.hour + t.minute / 60)
        night = act[act.index.hour >= 20]
        if not night.empty:
            t = night.index[-1]
            sleeps.append(t.hour + t.minute / 60)
    return (float(np.median(wakes)) if wakes else None,
            float(np.median(sleeps)) if sleeps else None)


# ═══════════════════════════════════════════
# 3. 이상 감지
# ═══════════════════════════════════════════

def longest_quiet_in_active_hours(day_s, base_row):
    active_hours = set(base_row[base_row["mean"] >= ACTIVE_HOUR_MIN].index)
    longest = 0
    run = 0
    for ts, v in day_s.items():
        if ts.hour in active_hours and v == 0:
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    return longest * 5 / 60


def detect_anomalies(s, base):
    findings = []
    for day, grp in s.groupby(s.index.date):
        weekend = int(pd.Timestamp(day).dayofweek >= 5)
        base_row = base.loc[weekend]

        # ── (A) 활동 시간에 오래 조용 ──
        quiet_h = longest_quiet_in_active_hours(grp, base_row)
        if quiet_h >= QUIET_HIGH_H:
            findings.append((day, "quiet_high", quiet_h,
                             f"평소 활동 시간에 {quiet_h:.1f}시간 연속 움직임 없음"))
        elif quiet_h >= QUIET_MEDIUM_H:
            findings.append((day, "quiet_medium", quiet_h,
                             f"평소 활동 시간에 {quiet_h:.1f}시간 조용함"))

        # ── (B) 새벽 활동 ──
        night = grp[(grp.index.hour >= NIGHT_START) & (grp.index.hour < NIGHT_END)]
        night_ratio = night.mean() if len(night) else 0
        night_base = base_row.loc[NIGHT_START:NIGHT_END - 1, "mean"].mean()
        if night_ratio >= NIGHT_ACTIVE_MIN and night_base < 0.1:
            findings.append((day, "night_activity", night_ratio,
                             f"새벽 {NIGHT_START}~{NIGHT_END}시 활동 {night_ratio*100:.0f}% (평소 거의 없음)"))

        # ── (C) 하루 전체 패턴 이탈 ──
        hourly = grp.resample("1h").mean()
        zs = []
        for ts, r in hourly.items():
            m = base_row.loc[ts.hour, "mean"]
            sd = base_row.loc[ts.hour, "std"]
            zs.append(abs(r - m) / sd)
        day_z = np.mean(zs)
        if day_z >= DAY_ZSCORE_HIGH:
            findings.append((day, "pattern_deviation", day_z,
                             f"하루 전체가 평소와 다름 (편차 점수 {day_z:.1f})"))
    return findings


# ═══════════════════════════════════════════
# 4. 저장
# ═══════════════════════════════════════════

def save_rule(rule, value, detail=None):
    v = float(value) if value is not None else None
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO learned_rules (room, rule, value, detail)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (room, rule) DO UPDATE
              SET value = EXCLUDED.value, detail = EXCLUDED.detail, learned_at = now()
        """, (ROOM, rule, v, detail))


def save_anomalies(findings):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM anomalies WHERE room = %s", (ROOM,))
        for day, kind, score, desc in findings:
            cur.execute("""
                INSERT INTO anomalies (room, day, kind, score, description)
                VALUES (%s, %s, %s, %s, %s)
            """, (ROOM, day, kind, float(score), desc))


# ═══════════════════════════════════════════
# 5. 실행
# ═══════════════════════════════════════════

def fmt_time(h):
    return f"{int(h):02d}:{int((h % 1) * 60):02d}" if h is not None else "—"


def main():
    print(f"=== {ROOM} 분석 (최근 {LOOKBACK_DAYS}일) ===\n")

    s = load_motion()
    if s is None:
        print("motion 데이터 없음")
        return
    days = len(set(s.index.date))
    print(f"데이터: {len(s)}개 구간, {days}일치\n")

    # ── 학습 ──
    base = learn_baseline(s)
    wake, sleep = learn_sleep_wake(s)
    ac_on, ac_off = load_aircon_temps()

    print("[학습 결과]")
    print(f"  기상 시각 (중앙값): {fmt_time(wake)}")
    print(f"  취침 시각 (중앙값): {fmt_time(sleep)}")
    if ac_on:
        print(f"  에어컨 켜는 온도: {ac_on:.1f}°C / 끄는 온도: {ac_off:.1f}°C")

    print("\n  시간대별 평소 활동률 (평일):")
    wd = base.loc[0]
    line = "  "
    for h in range(24):
        line += f"{h:02d}:{wd.loc[h, 'mean']*100:3.0f}% "
        if h % 6 == 5:
            print(line); line = "  "

    save_rule("wake_time", wake)
    save_rule("sleep_time", sleep)
    if ac_on:
        save_rule("aircon_on_temp", ac_on)
        save_rule("aircon_off_temp", ac_off)
    save_rule("hourly_baseline", None, json.dumps({
        "weekday": wd["mean"].round(3).tolist(),
        "weekend": base.loc[1]["mean"].round(3).tolist(),
    }))

    # ── 이상 감지 ──
    findings = detect_anomalies(s, base)
    save_anomalies(findings)

    print(f"\n[이상 감지] {len(findings)}건")
    for day, kind, score, desc in findings:
        tag = {"quiet_high": "[긴급]", "quiet_medium": "[주의]",
               "night_activity": "[배회]", "pattern_deviation": "[이탈]"}[kind]
        print(f"  {day}  {tag}  {desc}")

    print("\n완료. learned_rules, anomalies 표에 저장됨.")


if __name__ == "__main__":
    main()