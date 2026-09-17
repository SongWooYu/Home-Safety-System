CREATE TABLE rooms (
    id      TEXT PRIMARY KEY,
    name_ko TEXT NOT NULL,
    sort    INT  NOT NULL DEFAULT 0
);

CREATE TABLE metrics (
    id         TEXT PRIMARY KEY,
    name_ko    TEXT NOT NULL,
    unit       TEXT,
    is_numeric BOOLEAN NOT NULL DEFAULT false,
    sort       INT NOT NULL DEFAULT 0
);

CREATE TABLE sensor_data (
    id        BIGSERIAL PRIMARY KEY,
    ts        TIMESTAMPTZ NOT NULL DEFAULT now(),
    room      TEXT NOT NULL REFERENCES rooms(id),
    metric    TEXT NOT NULL REFERENCES metrics(id),
    num_value REAL,
    str_value TEXT
);

CREATE TABLE command_log (
    id     BIGSERIAL PRIMARY KEY,
    ts     TIMESTAMPTZ NOT NULL DEFAULT now(),
    room   TEXT NOT NULL REFERENCES rooms(id),
    device TEXT NOT NULL,
    value  TEXT NOT NULL
);

CREATE TABLE learned_rules (
    id         BIGSERIAL PRIMARY KEY,
    room       TEXT NOT NULL REFERENCES rooms(id),
    rule       TEXT NOT NULL,
    value      REAL,
    detail     TEXT,
    learned_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (room, rule)
);

CREATE TABLE anomalies (
    id          BIGSERIAL PRIMARY KEY,
    room        TEXT NOT NULL REFERENCES rooms(id),
    day         DATE NOT NULL,
    kind        TEXT NOT NULL,
    score       REAL,
    description TEXT,
    detected_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_sensor_data_room_metric_ts ON sensor_data (room, metric, ts DESC);
CREATE INDEX idx_command_log_room_device_ts ON command_log (room, device, ts DESC);

INSERT INTO rooms (id, name_ko, sort) VALUES
  ('entrance',   '현관',       1),
  ('livingroom', '거실',       2),
  ('kitchen',    '부엌',       3),
  ('bathroom',   '화장실',     4),
  ('studio',     '스튜디오',   5),
  ('sim_studio', '시뮬레이션', 6);

INSERT INTO metrics (id, name_ko, unit, is_numeric, sort) VALUES
  ('door',        '현관문', NULL,  false, 1),
  ('motion',      '움직임', NULL,  false, 2),
  ('presence',    '재실',   NULL,  false, 3),
  ('distance',    '거리',   'cm',  true,  4),
  ('temperature', '온도',   '°C',  true,  5),
  ('humidity',    '습도',   '%',   true,  6),
  ('brightness',  '조도',   NULL,  true,  7),
  ('gas',         '가스',   NULL,  false, 8);