// lib/mock.ts
// 하드웨어가 없어도 화면을 만들 수 있게 하는 임시 데이터.
// 나중에 실제 API 호출로 교체할 부분입니다.

import type {
  AiDecision,
  ControlLog,
  DeviceStatus,
  RiskEvent,
  SensorStatus,
} from "./types";

export const mockSensor: SensorStatus = {
  device_id: "esp32-living",
  timestamp: "2026-06-10T19:42:00",
  temperature: 24.8,
  humidity: 52,
  light_level: 180,
  occupancy: true,
  gas_detected: false,
  flame_detected: false,
  sensor_status: "ok",
};

export const mockAi: AiDecision = {
  device_id: "rpi4-server",
  timestamp: "2026-06-10T19:42:03",
  context: "평일 저녁 귀가 직후",
  recommended_action: "거실 조명 켜기 · 냉방 24°C 설정",
  confidence: 0.87,
  reason: "최근 14일간 같은 시간대 동일 패턴 12회 관측",
};

export const mockEvents: RiskEvent[] = [
  {
    id: 3,
    camera_id: "cam-01",
    timestamp: "2026-06-10T19:31:12",
    event_type: "fall_suspected",
    risk_level: "high",
    state_before: "standing",
    state_after: "lying",
    duration_sec: 42,
    snapshot_path: null,
    acknowledged: false,
  },
  {
    id: 2,
    camera_id: "cam-01",
    timestamp: "2026-06-10T14:08:55",
    event_type: "no_response_suspected",
    risk_level: "medium",
    state_before: "sitting",
    state_after: "sitting",
    duration_sec: 1830,
    snapshot_path: null,
    acknowledged: true,
  },
  {
    id: 1,
    camera_id: "cam-01",
    timestamp: "2026-06-10T09:12:40",
    event_type: "abnormal_posture",
    risk_level: "low",
    state_before: "moving",
    state_after: "lying",
    duration_sec: 15,
    snapshot_path: null,
    acknowledged: true,
  },
];

export const mockControls: ControlLog[] = [
  {
    id: 3,
    timestamp: "2026-06-10T19:42:05",
    target_device: "거실 조명",
    command: "ON",
    control_result: "success",
    source: "ai",
  },
  {
    id: 2,
    timestamp: "2026-06-10T19:20:11",
    target_device: "환기 서보",
    command: "OPEN",
    control_result: "success",
    source: "manual",
  },
  {
    id: 1,
    timestamp: "2026-06-10T18:55:02",
    target_device: "부저",
    command: "OFF",
    control_result: "failed",
    source: "ai",
  },
];

export const mockDevices: DeviceStatus[] = [
  { device_id: "esp32-living", name: "거실 센서 노드", node: "ESP32", online: true, last_seen: "3초 전" },
  { device_id: "rpi5-cam", name: "낙상감지 카메라", node: "RPi5", online: true, last_seen: "1초 전" },
  { device_id: "rpi4-server", name: "서버 · 브로커", node: "RPi4", online: true, last_seen: "1초 전" },
  { device_id: "esp32-room", name: "침실 센서 노드", node: "ESP32", online: false, last_seen: "12분 전" },
];