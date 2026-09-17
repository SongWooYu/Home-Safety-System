import time
import paho.mqtt.client as mqtt

# ── 설정값 ──
TEMP_HIGH = 28.0          # 이 온도 넘으면 에어컨 켜기
TEMP_LOW = 25.0           # 이 온도 밑으로 내려가면 에어컨 끄기
BRIGHT_HIGH = 2500        # 이보다 밝으면 커튼 닫기
BRIGHT_LOW = 800          # 이보다 어두우면 커튼 열기
NO_MOTION_SEC = 30        # 이 시간 조용하면 조명 끄기

# ── 방별 상태 기억 ──
state = {}

def get_state(room):
    if room not in state:
        state[room] = {
            "light_on": False,
            "aircon_on": False,
            "curtain_open": True,
            "presence_on": False,
            "last_motion": time.time(),
        }
    return state[room]

client = mqtt.Client()


def command(topic, value):
    client.publish(topic, value)
    print(f"명령: {topic} = {value}")


def on_connect(c, userdata, flags, rc):
    print("자동화 엔진 시작")
    c.subscribe("home/+/motion")
    c.subscribe("home/+/presence")
    c.subscribe("home/+/temperature")
    c.subscribe("home/+/brightness")


def on_message(c, userdata, msg):
    topic = msg.topic
    value = msg.payload.decode()
    parts = topic.split("/")
    room = parts[1]
    metric = parts[2]
    s = get_state(room)

    # ── 규칙 1: 사람 있으면 조명 켜기 ──
    if metric in ("motion", "presence"):
        if metric == "presence":
            s["presence_on"] = (value == "ON")
        if value == "ON":
            s["last_motion"] = time.time()
            if not s["light_on"]:
                command(f"home/{room}/light/set", "ON")
                s["light_on"] = True

    # ── 규칙 2: 온도에 따라 에어컨 ──
    elif metric == "temperature":
        temp = float(value)
        if temp > TEMP_HIGH and not s["aircon_on"]:
            command(f"home/{room}/aircon/set", "ON")
            s["aircon_on"] = True
        elif temp < TEMP_LOW and s["aircon_on"]:
            command(f"home/{room}/aircon/set", "OFF")
            s["aircon_on"] = False

    # ── 규칙 3: 밝기에 따라 커튼 ──
    elif metric == "brightness":
        bright = int(value)
        if bright > BRIGHT_HIGH and s["curtain_open"]:
            command(f"home/{room}/curtain/set", "CLOSE")
            s["curtain_open"] = False
        elif bright < BRIGHT_LOW and not s["curtain_open"]:
            command(f"home/{room}/curtain/set", "OPEN")
            s["curtain_open"] = True


client.on_connect = on_connect
client.on_message = on_message
client.connect("localhost", 1883, 60)
client.loop_start()

# ── 규칙 1-2: 시간 지나면 조명 끄기 (방별) ──
while True:
    time.sleep(10)
    for room, s in state.items():
        if s["light_on"] and not s["presence_on"] \
           and time.time() - s["last_motion"] > NO_MOTION_SEC:
            command(f"home/{room}/light/set", "OFF")
            s["light_on"] = False