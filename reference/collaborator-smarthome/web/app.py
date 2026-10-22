import os
import psycopg2
from flask import Flask, jsonify, send_from_directory

app = Flask(__name__)

# Optional, isolated vision-event notification (no changes to sensor/DB logic).
from fall_notice import install as install_fall_notice
install_fall_notice(app)
from device_control import install as install_device_control
install_device_control(app)

def get_conn():
    return psycopg2.connect(
        host="localhost",
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
    )

def query(sql, params=()):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return rows


@app.route("/")
def index():
    return send_from_directory(".", "index.html")


@app.route("/api/meta")
def meta():
    rooms = query("SELECT id, name_ko FROM rooms ORDER BY sort")
    metrics = query("SELECT id, name_ko, unit, is_numeric FROM metrics ORDER BY sort")
    return jsonify({
        "rooms": [{"id": r[0], "name": r[1]} for r in rooms],
        "metrics": [{"id": m[0], "name": m[1], "unit": m[2] or "", "numeric": m[3]} for m in metrics],
    })


@app.route("/api/latest")
def latest():
    sensors = query("""
        SELECT DISTINCT ON (room, metric) room, metric, num_value, str_value, ts
        FROM sensor_data
        ORDER BY room, metric, ts DESC
    """)
    commands = query("""
        SELECT DISTINCT ON (room, device) room, device, value, ts
        FROM command_log
        ORDER BY room, device, ts DESC
    """)
    return jsonify({
        "sensors": [
            {"room": r[0], "metric": r[1],
             "value": r[2] if r[2] is not None else r[3],
             "ts": r[4].isoformat()}
            for r in sensors
        ],
        "commands": [
            {"room": r[0], "device": r[1], "value": r[2], "ts": r[3].isoformat()}
            for r in commands
        ],
    })


@app.route("/api/history/<room>/<metric>")
def history(room, metric):
    rows = query("""
        SELECT ts, num_value FROM sensor_data
        WHERE room = %s AND metric = %s AND num_value IS NOT NULL
          AND ts > now() - interval '1 hour'
        ORDER BY ts
    """, (room, metric))
    return jsonify([{"ts": r[0].isoformat(), "value": r[1]} for r in rows])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
