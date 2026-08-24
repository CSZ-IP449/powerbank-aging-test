export interface TestConfig {
  target_test_count: number
  max_retry: number
  slot_timeout_ms: number
  phase_interval_ms: number
}

export const DEFAULT_CONFIG: TestConfig = {
  target_test_count: 100,
  max_retry: 0,
  slot_timeout_ms: 5000,
  phase_interval_ms: 3000,
}
