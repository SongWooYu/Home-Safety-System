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

def on_connect(client, userdata, flags, rc):
    print("MQTT connected:", rc)
    client.subscribe("home/#")

def on_message(client, userdata, msg):
    topic = msg.topic
    value = msg.payload.decode()
    parts = topic.split("/")
    room = parts[1] if len(parts) > 1 else None
    metric = parts[2] if len(parts) > 2 else None
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO sensor_log (topic, room, metric, value) VALUES (%s,%s,%s,%s)",
            (topic, room, metric, value),
        )
    print(f"saved: {topic} = {value}")

client = mqtt.Client()
client.on_connect = on_connect
client.on_message = on_message
client.connect("localhost", 1883, 60)
client.loop_forever()
