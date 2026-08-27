// lib/types.ts
// 보고서 10.1 MQTT 메시지 표를 그대로 코드로 옮긴 것.
// 여기가 프론트엔드와 라즈베리파이 서버 사이의 '계약서'입니다.

export type RiskLevel = "low" | "medium" | "high";

export type PostureState = "standing" | "sitting" | "lying" | "moving" | "unknown";

/** home/status — ESP32가 보내는 환경 상태 */
export interface SensorStatus {
  device_id: string;
  timestamp: string;
  temperature: number; // °C
  humidity: number; // %
  light_level: number; // lux
  occupancy: boolean; // 재실 여부
  gas_detected: boolean;
  flame_detected: boolean;
  sensor_status: "ok" | "warn" | "error";
}

/** home/ai — AI 판단 결과 */
export interface AiDecision {
  device_id: string;
  timestamp: string;
  context: string; // 예: "저녁 귀가 직후"
  recommended_action: string; // 예: "거실 조명 켜기"
  confidence: number; // 0 ~ 1
  reason: string;
}

/** home/control — IoT 제어 이력 */
export interface ControlLog {
  id: number;
  timestamp: string;
  target_device: string;
  command: string;
  control_result: "success" | "failed";
  source: "ai" | "manual"; // 수동 제어 우선순위 확인용
}

/** risk/event — 낙상·무반응 위험 이벤트 */
export interface RiskEvent {
  id: number;
  camera_id: string;
  timestamp: string;
  event_type: "fall_suspected" | "no_response_suspected" | "abnormal_posture";
  risk_level: RiskLevel;
  state_before: PostureState;
  state_after: PostureState;
  duration_sec: number;
  snapshot_path: string | null;
  acknowledged: boolean; // 보호자 확인 여부
}

/** 장치 연결 상태 */
export interface DeviceStatus {
  device_id: string;
  name: string;
  node: "ESP32" | "RPi4" | "RPi5";
  online: boolean;
  last_seen: string;
}