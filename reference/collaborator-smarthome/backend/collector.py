import os
import psycopg2
import paho.mqtt.client as mqtt

conn = psycopg2.connect(
    host=os.getenv("PGHOST", "localhost"),
    dbname=os.getenv("POSTGRES_DB"),
    user=os.getenv("POSTGRES_USER"),
    password=os.getenv("POSTGRES_PASSWORD"),
)
conn.autocommit = True

# 시작할 때 rooms, metrics 표를 읽어서 기억
KNOWN_ROOMS = set()
NUMERIC = set()
with conn.cursor() as cur:
    cur.execute("SELECT id FROM rooms")
    KNOWN_ROOMS = {r[0] for r in cur.fetchall()}
    cur.execute("SELECT id FROM metrics WHERE is_numeric")
    NUMERIC = {r[0] for r in cur.fetchall()}
print("등록된 방:", KNOWN_ROOMS)
print("숫자형 센서:", NUMERIC)


def on_connect(client, userdata, flags, rc):
    print("MQTT connected:", rc)
    client.subscribe("home/#")


def on_message(client, userdata, msg):
    topic = msg.topic
    value = msg.payload.decode()

    if topic.startswith("home/vision/"):
        return

    parts = topic.split("/")
    if len(parts) < 3:
        return
    room = parts[1]

    # 등록 안 된 방은 건너뜀 (죽지 않음)
    if room not in KNOWN_ROOMS:
        print(f"모르는 방, 건너뜀: {topic}")
        return

    try:
        # ── 명령: home/{room}/{device}/set ──
        if topic.endswith("/set"):
            device = parts[2]
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO command_log (room, device, value) VALUES (%s, %s, %s)",
                    (room, device, value),
                )
            print(f"명령 저장: {room}/{device} = {value}")
            return

        # ── 센서: home/{room}/{metric} ──
        metric = parts[2]
        if metric in NUMERIC:
            try:
                num = float(value)
            except ValueError:
                print(f"숫자 아님, 건너뜀: {topic} = {value}")
                return
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO sensor_data (room, metric, num_value) VALUES (%s, %s, %s)",
                    (room, metric, num),
                )
        else:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO sensor_data (room, metric, str_value) VALUES (%s, %s, %s)",
                    (room, metric, value),
                )
        print(f"저장: {room}/{metric} = {value}")

    except Exception as e:
        # DB 에러가 나도 죽지 않고 로그만 남김
        print(f"저장 실패: {topic} = {value} → {e}")


client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message
client.connect("localhost", 1883, 60)
client.loop_forever()