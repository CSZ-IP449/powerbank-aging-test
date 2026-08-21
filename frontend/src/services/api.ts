import type { SlotView } from '@/types/slot'
import type { RunnerState } from '@/types/runner'
import type { DeviceInfo, CommLogEntry } from '@/types/comm'
import type { TestConfig } from '@/types/config'

export interface FullStatus {
  cabinet: DeviceInfo
  fixture: DeviceInfo
  runner: RunnerState
  slots: (SlotView & { id_display?: string; initial_id_display?: string | null })[]
  config: TestConfig
}

async function postJson(url: string, body?: unknown): Promise<unknown> {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  return res.json()
}

interface ApiResult {
  ok: boolean
  error?: string
  [key: string]: unknown
}

interface DebugSendResult {
  ok: boolean
  error?: string
  request_hex?: string
  response_hex?: string
  parsed?: Record<string, unknown>
}

export const api = {
  health: () => fetch('/api/health').then(r => r.json()),
  version: () => fetch('/api/version').then(r => r.json()),
  ports: () => fetch('/api/ports').then(r => r.json()) as Promise<{ ports: string[] }>,
  status: () => fetch('/api/status').then(r => r.json()) as Promise<FullStatus>,
  connectCabinet: (port: string, baudrate = 115200) =>
    postJson('/api/connect/cabinet', { port, baudrate }) as Promise<ApiResult>,
  connectFixture: (port: string, baudrate = 115200) =>
    postJson('/api/connect/fixture', { port, baudrate }) as Promise<ApiResult>,
  disconnectCabinet: () => postJson('/api/disconnect/cabinet') as Promise<ApiResult>,
  disconnectFixture: () => postJson('/api/disconnect/fixture') as Promise<ApiResult>,
  enableMock: () => postJson('/api/mock/enable') as Promise<ApiResult>,
  disableMock: () => postJson('/api/mock/disable') as Promise<ApiResult>,
  init: () => postJson('/api/init') as Promise<ApiResult>,
  setConfig: (cfg: Partial<TestConfig>) => postJson('/api/config', cfg) as Promise<ApiResult>,
  start: () => postJson('/api/start') as Promise<ApiResult>,
  pause: () => postJson('/api/pause') as Promise<ApiResult>,
  resume: () => postJson('/api/resume') as Promise<ApiResult>,
  stop: () => postJson('/api/stop') as Promise<ApiResult>,
  refresh: () => postJson('/api/refresh') as Promise<ApiResult>,
  clearStats: (scope: 'all' | 'slot' = 'all', slotNo?: number) =>
    postJson('/api/clear-stats', { scope, slot_no: slotNo }) as Promise<ApiResult>,
  commLogs: (limit = 100) =>
    fetch(`/api/comm-logs?limit=${limit}`).then(r => r.json()) as Promise<{ logs: CommLogEntry[] }>,
  debugSend: (address: number, command: number, slotNo?: number) =>
    postJson('/api/debug/send', { address, command, slot_no: slotNo }) as Promise<DebugSendResult>,
}

export type SseEvent =
  | { event: 'hello'; data: Record<string, never> }
  | { event: 'state'; data: RunnerState }
  | { event: 'slot'; data: SlotView & { slot_no: number } }
  | { event: 'connection'; data: { device: string; status: string; error: string | null } }
  | { event: 'comm'; data: CommLogEntry }
  | { event: 'slots_cleared'; data: { slot_count: number } }

export function subscribeSSE(onEvent: (e: SseEvent) => void): () => void {
  const es = new EventSource('/events')
  es.onmessage = (ev) => {
    try {
      const parsed = JSON.parse(ev.data) as SseEvent
      onEvent(parsed)
    } catch (e) {
      console.warn('SSE parse error', e)
    }
  }
  es.onerror = () => {
    console.warn('SSE error, will reconnect')
  }
  return () => es.close()
}
