import time
import random
import paho.mqtt.client as mqtt

client = mqtt.Client()
client.connect("localhost", 1883, 60)
client.loop_start()

temp = 24.0

while True:
    # 온도가 조금씩 오르내림
    temp += random.uniform(-0.5, 0.7)
    temp = max(18, min(40, temp))

    # 사람이 있을지 없을지 랜덤
    motion = "ON" if random.random() < 0.3 else "OFF"

    client.publish("home/livingroom/temperature", f"{temp:.1f}")
    client.publish("home/livingroom/humidity", str(random.randint(40, 70)))
    client.publish("home/livingroom/motion", motion)

    print(f"보냄: {temp:.1f}도, 움직임 {motion}")
    time.sleep(30)