import time
import paho.mqtt.client as mqtt

# ===== 기준값 =====
TEMP_HIGH = 28.0      # 넘으면 에어컨 ON
TEMP_LOW = 25.0       # 내려가면 에어컨 OFF
HUMI_HIGH = 70.0      # 넘으면 환풍기 ON
HUMI_LOW = 60.0       # 내려가면 환풍기 OFF
NO_MOTION_SEC = 30    # 이 시간 동안 움직임 없으면 조명 OFF
DOOR_LIGHT_SEC = 30   # 문 닫힌 뒤 이 시간 지나면 현관 조명 OFF

# 커튼: 3구간 (밤 닫기 / 적당하면 열기 / 직사광 닫기)
NIGHT_CLOSE = 800
NIGHT_OPEN  = 1200
SUN_CLOSE   = 3200
SUN_OPEN    = 2800

# ===== 규칙을 적용할 방 =====
LIGHT_ROOMS = {"livingroom", "bathroom"}
AIRCON_ROOMS = {"livingroom"}
FAN_ROOMS = {"bathroom"}
CURTAIN_ROOMS = {"livingroom"}

LOG_BRIGHTNESS = False   # 조도 기준 맞출 때만 True

MQTT_PORT = 1883

state = {}

def get_state(room):
    if room not in state:
        state[room] = {
            "light_on": False,
            "aircon_on": False,
            "fan_on": False,
            "alarm_on": False,
            "curtain_open": True,
            "curtain_reason": "시작",
            "presence_on": False,
            "last_motion": time.time(),
            "door_open": False,
            "door_closed_at": 0,
            "entrance_light_on": False,
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
    c.subscribe("home/+/humidity")
    c.subscribe("home/+/brightness")
    c.subscribe("home/+/gas")
    c.subscribe("home/+/door")


def handle_curtain(room, s, bright):
    """조도에 따라 커튼을 여닫는다. 3구간 방식."""
    if s["curtain_open"]:
        if bright < NIGHT_CLOSE:
            command(f"home/{room}/curtain/set", "CLOSE")
            s["curtain_open"] = False
            s["curtain_reason"] = "밤"
            print(f"  → 어두워짐 (조도 {bright}), 사생활 보호로 닫음")
        elif bright > SUN_CLOSE:
            command(f"home/{room}/curtain/set", "CLOSE")
            s["curtain_open"] = False
            s["curtain_reason"] = "직사광"
            print(f"  → 너무 밝음 (조도 {bright}), 눈부심 차단으로 닫음")
    else:
        if s["curtain_reason"] == "밤" and bright > NIGHT_OPEN:
            command(f"home/{room}/curtain/set", "OPEN")
            s["curtain_open"] = True
            print(f"  → 밝아짐 (조도 {bright}), 아침이라 열음")
        elif s["curtain_reason"] == "직사광" and bright < SUN_OPEN:
            command(f"home/{room}/curtain/set", "OPEN")
            s["curtain_open"] = True
            print(f"  → 햇빛 누그러짐 (조도 {bright}), 다시 열음")
        elif s["curtain_reason"] == "시작":
            if NIGHT_OPEN <= bright <= SUN_OPEN:
                command(f"home/{room}/curtain/set", "OPEN")
                s["curtain_open"] = True
                print(f"  → 적당한 밝기 (조도 {bright}), 열음")


def on_message(c, userdata, msg):
    topic = msg.topic
    value = msg.payload.decode()
    parts = topic.split("/")
    if len(parts) < 3:
        return
    room = parts[1]
    metric = parts[2]
    s = get_state(room)

    try:
        # 1) 움직임 → 조명 (거실·화장실만)
        if metric in ("motion", "presence"):
            if metric == "presence":
                s["presence_on"] = (value == "ON")
            if value == "ON":
                s["last_motion"] = time.time()
                if room in LIGHT_ROOMS and not s["light_on"]:
                    command(f"home/{room}/light/set", "ON")
                    s["light_on"] = True

        # 2) 온도 → 에어컨 (거실만)
        elif metric == "temperature":
            if room not in AIRCON_ROOMS:
                return
            temp = float(value)
            if temp > TEMP_HIGH and not s["aircon_on"]:
                command(f"home/{room}/aircon/set", "ON")
                s["aircon_on"] = True
            elif temp < TEMP_LOW and s["aircon_on"]:
                command(f"home/{room}/aircon/set", "OFF")
                s["aircon_on"] = False

        # 3) 습도 → 환풍기 (화장실만)
        elif metric == "humidity":
            if room not in FAN_ROOMS:
                return
            humi = float(value)
            if humi > HUMI_HIGH and not s["fan_on"]:
                command(f"home/{room}/fan/set", "ON")
                s["fan_on"] = True
            elif humi < HUMI_LOW and s["fan_on"]:
                command(f"home/{room}/fan/set", "OFF")
                s["fan_on"] = False

        # 4) 밝기 → 커튼 (거실만)
        elif metric == "brightness":
            if room not in CURTAIN_ROOMS:
                return
            bright = int(float(value))
            if LOG_BRIGHTNESS:
                상태 = "열림" if s["curtain_open"] else f"닫힘({s['curtain_reason']})"
                print(f"조도 {bright} (커튼 {상태})")
            handle_curtain(room, s, bright)

        # 5) 가스 → 부저 경보 (부엌)
        elif metric == "gas":
            if value == "ON" and not s["alarm_on"]:
                command(f"home/{room}/alarm/set", "ON")
                s["alarm_on"] = True
                print("  → 가스 감지! 경보 울림")
            elif value == "OFF" and s["alarm_on"]:
                command(f"home/{room}/alarm/set", "OFF")
                s["alarm_on"] = False
                print("  → 가스 정상, 경보 해제")

        # 6) 문 → 현관 조명
        elif metric == "door":
            if value == "OPEN":
                s["door_open"] = True
                if not s["entrance_light_on"]:
                    command(f"home/{room}/light/set", "ON")
                    s["entrance_light_on"] = True
                    print("  → 문 열림, 현관 조명 켬")
            else:
                if s["door_open"]:
                    s["door_closed_at"] = time.time()
                s["door_open"] = False

    except Exception as e:
        print(f"처리 실패, 건너뜀: {topic} = {value} → {e}")


client.on_connect = on_connect
client.on_message = on_message
client.connect("localhost", MQTT_PORT, 60)
client.loop_start()

while True:
    time.sleep(5)
    now = time.time()
    for room, s in list(state.items()):
        if s["light_on"] and not s["presence_on"] \
           and now - s["last_motion"] > NO_MOTION_SEC:
            command(f"home/{room}/light/set", "OFF")
            s["light_on"] = False

        if s["entrance_light_on"] and not s["door_open"] \
           and s["door_closed_at"] > 0 \
           and now - s["door_closed_at"] > DOOR_LIGHT_SEC:
            command(f"home/{room}/light/set", "OFF")
            s["entrance_light_on"] = False
            print("  → 문 닫힌 지 오래됨, 현관 조명 끔")