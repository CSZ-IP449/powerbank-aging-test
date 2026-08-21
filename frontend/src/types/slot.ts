export enum WarehouseState {
  Unknown = 0x00,
  InCabinet = 0x01,
  OutCabinet = 0x02,
  WarehousingIn = 0x03,
  WarehousingOut = 0x04,
  Abnormal = 0x05,
}

export const WAREHOUSE_STATE_LABEL: Record<WarehouseState, string> = {
  [WarehouseState.Unknown]: '未知',
  [WarehouseState.InCabinet]: '仓内',
  [WarehouseState.OutCabinet]: '已出仓',
  [WarehouseState.WarehousingIn]: '进仓中',
  [WarehouseState.WarehousingOut]: '出仓中',
  [WarehouseState.Abnormal]: '异常',
}

export enum TestDirection {
  None = 0,
  InTest = 1,
  OutTest = 2,
}

export enum TestState {
  NotTested = 0x00,
  Waiting = 0x01,
  Running = 0x02,
  Success = 0x03,
  Failed = 0x04,
  Timeout = 0x05,
  Cancelled = 0x06,
  Undeterminable = 0x07,
}

export const TEST_STATE_LABEL: Record<TestState, string> = {
  [TestState.NotTested]: '未测试',
  [TestState.Waiting]: '等待',
  [TestState.Running]: '执行中',
  [TestState.Success]: '成功',
  [TestState.Failed]: '失败',
  [TestState.Timeout]: '超时',
  [TestState.Cancelled]: '已取消',
  [TestState.Undeterminable]: '无法判定',
}

export interface SlotData {
  slot_no: number
  warehouse_state: WarehouseState
  id_ok: 0 | 1
  power_bank_id: number[]
  lock_button: 0 | 1
  tray_button: 0 | 1
  detect_button: 0 | 1
  test_result: number
  error_code: number
}

export interface SlotStats {
  in_count: number
  out_count: number
  success_count: number
  failure_count: number
  completed_test_count: number
  round_count: number
  out_success_count: number
  out_failure_count: number
  in_success_count: number
  in_failure_count: number
}

export interface SlotView extends SlotData, SlotStats {
  test_direction: TestDirection
  test_state: TestState
  app_result: number
  failure_reason: number
  initial_id: number[] | null
  initial_id_ok: 0 | 1 | null
}

export function formatPowerBankId(idBytes: number[]): string {
  if (!idBytes || idBytes.length !== 8) return '--------'
  const head = idBytes.slice(0, 4)
    .map(b => {
      const c = String.fromCharCode(b)
      return b >= 0x20 && b <= 0x7e ? c : '.'
    })
    .join('')
  const tail = idBytes.slice(4, 8)
    .map(b => b.toString(16).toUpperCase().padStart(2, '0'))
    .join('')
  return head + tail
}
