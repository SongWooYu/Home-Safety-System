"""
8주치 가상 생활 데이터 생성
- 혼자 사는 사람의 평일/주말 패턴
- 일부러 넣은 이상 날짜 (43일, 50일)
- room = 'sim_studio' 로 저장 (진짜 데이터와 구분)
"""
import os
import random
import psycopg2
from datetime import datetime, timedelta, timezone

DAYS = 56
ROOM = "sim_studio"
KST = timezone(timedelta(hours=9))
START = datetime(2026, 7, 27, 0, 0, 0, tzinfo=KST)

# ── 생활 패턴 (분 단위) ──
WAKE_WEEKDAY  = 7 * 60          # 07:00
WAKE_WEEKEND  = 8 * 60          # 08:00
LEAVE         = 9 * 60          # 09:00 외출
RETURN        = 18 * 60 + 30    # 18:30 귀가
SLEEP         = 23 * 60 + 30    # 23:30 취침
JITTER        = 30              # ±30분 흔들림

# ── 이상 날짜 ──
ANOMALY_DAYS = {
    42: "no_activity",      # 43일째: 하루 종일 움직임 없음
    49: "night_activity",   # 50일째: 새벽 3시 활동
}

conn = psycopg2.connect(
    host="localhost",
    dbname=os.getenv("POSTGRES_DB"),
    user=os.getenv("POSTGRES_USER"),
    password=os.getenv("POSTGRES_PASSWORD"),
)
conn.autocommit = True
cur = conn.cursor()

rows = []

def add(ts, metric, num=None, s=None):
    rows.append((ts, ROOM, metric, num, s))

def jitter(minutes):
    return minutes + random.randint(-JITTER, JITTER)

def temp_at(minute_of_day, base):
    """하루 온도 곡선: 새벽 최저, 오후 3시 최고"""
    import math
    phase = (minute_of_day - 15 * 60) / (24 * 60) * 2 * math.pi
    return base + 3 * math.cos(phase) + random.uniform(-0.3, 0.3)


for day in range(DAYS):
    date = START + timedelta(days=day)
    weekend = date.weekday() >= 5
    anomaly = ANOMALY_DAYS.get(day)
    base_temp = random.uniform(24, 28)

    wake = jitter(WAKE_WEEKEND if weekend else WAKE_WEEKDAY)
    sleep = jitter(SLEEP)
    leave = jitter(LEAVE)
    ret = jitter(RETURN)
    go_out = (not weekend) or random.random() < 0.3
    nap = weekend and random.random() < 0.3

    aircon_on = False

    for minute in range(0, 24 * 60, 5):
        ts = date + timedelta(minutes=minute)
        t = temp_at(minute, base_temp)

        # ── 활동 여부 ──
        active = False
        if anomaly == "no_activity":
            active = False
        elif anomaly == "night_activity":
            active = (2 * 60 <= minute < 4 * 60) or (wake <= minute < sleep and random.random() < 0.3)
        else:
            if wake <= minute < sleep:
                if go_out and leave <= minute < ret:
                    active = False
                elif nap and 14 * 60 <= minute < 15 * 60:
                    active = False
                else:
                    active = random.random() < 0.35

        add(ts, "motion", s="ON" if active else "OFF")

        # ── 온습도 (30분마다) ──
        if minute % 30 == 0:
            add(ts, "temperature", num=round(t, 1))
            add(ts, "humidity", num=round(random.uniform(45, 65), 0))

        # ── 에어컨 (사람이 있고 27.5도 넘으면 60% 확률로 켬) ──
        if active and t > 27.5 and not aircon_on and random.random() < 0.6:
            rows.append((ts, ROOM, "__cmd_aircon", None, "ON"))
            aircon_on = True
        if aircon_on and t < 25.5:
            rows.append((ts, ROOM, "__cmd_aircon", None, "OFF"))
            aircon_on = False

    if day % 7 == 6:
        print(f"{day + 1}일 생성...")

# ── DB에 넣기 ──
sensor_rows = [(ts, r, m, n, s) for ts, r, m, n, s in rows if not m.startswith("__cmd_")]
cmd_rows = [(ts, r, m.replace("__cmd_", ""), s) for ts, r, m, n, s in rows if m.startswith("__cmd_")]

cur.executemany(
    "INSERT INTO sensor_data (ts, room, metric, num_value, str_value) VALUES (%s, %s, %s, %s, %s)",
    sensor_rows,
)
cur.executemany(
    "INSERT INTO command_log (ts, room, device, value) VALUES (%s, %s, %s, %s)",
    cmd_rows,
)

print(f"완료: 센서 {len(sensor_rows)}줄, 명령 {len(cmd_rows)}줄")
print(f"이상 날짜: 43일째 (활동 없음), 50일째 (새벽 활동)")