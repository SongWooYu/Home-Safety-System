import os
import psycopg2
from flask import Flask, jsonify, send_from_directory

app = Flask(__name__)

ROOMS = ("livingroom", "entrance", "kitchen", "bathroom")

def get_conn():
    return psycopg2.connect(
        host="localhost",
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )

@app.route("/")
def index():
    return send_from_directory(".", "index.html")

@app.route("/api/latest")
def latest():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT DISTINCT ON (topic) topic, room, metric, value, ts
        FROM sensor_log
        WHERE room IN %s
        ORDER BY topic, ts DESC
    """, (ROOMS,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([
        {"room": r[1], "metric": r[2], "value": r[3], "ts": r[4].isoformat()}
        for r in rows
    ])

@app.route("/api/history/<room>/<metric>")
def history(room, metric):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT ts, value FROM sensor_log
        WHERE room = %s AND metric = %s AND ts > now() - interval '1 hour'
        ORDER BY ts
    """, (room, metric))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([{"ts": r[0].isoformat(), "value": r[1]} for r in rows])

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)