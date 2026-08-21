import { useApp } from '@/store/appStore'
import {
  WAREHOUSE_STATE_LABEL,
  TEST_STATE_LABEL,
  WarehouseState,
  TestState,
  formatPowerBankId,
  type SlotView,
} from '@/types/slot'
import { TestDirection } from '@/types/slot'

const DIRECTION_LABEL: Record<number, string> = {
  [TestDirection.None]: '—',
  [TestDirection.InTest]: '进仓',
  [TestDirection.OutTest]: '出仓',
}

function stateColor(testState: number, slotNo: number, currentSlot: number): string {
  if (slotNo === currentSlot && testState === TestState.Running) return 'border-warn bg-warn/5'
  switch (testState) {
    case TestState.Success: return 'border-ok/40 bg-ok/5'
    case TestState.Failed: return 'border-bad/40 bg-bad/5'
    case TestState.Timeout: return 'border-warn/40 bg-warn/5'
    case TestState.Running: return 'border-cyan/40 bg-cyan/5'
    case TestState.Waiting: return 'border-white/20 bg-base-800'
    default: return 'border-white/10 bg-base-800'
  }
}

export function SlotCard({ slot, currentSlot, targetCount }: { slot: SlotView & { id_display?: string; initial_id_display?: string | null }; currentSlot: number; targetCount: number }) {
  const idDisplay = slot.id_display || formatPowerBankId(slot.power_bank_id)
  const initialIdDisplay = slot.initial_id_display
    ?? (slot.initial_id && slot.initial_id.length === 8 ? formatPowerBankId(slot.initial_id) : null)
  const stateLabel = TEST_STATE_LABEL[slot.test_state as TestState] || '—'
  const whLabel = WAREHOUSE_STATE_LABEL[slot.warehouse_state as WarehouseState] || '—'
  const direction = DIRECTION_LABEL[slot.test_direction] || '—'
  const isCurrent = slot.slot_no === currentSlot
  const completed = slot.completed_test_count || 0
  const target = targetCount || 0

  return (
    <div className={`rounded-lg border p-3 ${stateColor(slot.test_state, slot.slot_no, currentSlot)}`}>
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-white">#{slot.slot_no}</span>
          {isCurrent && slot.test_state === TestState.Running && <span className="text-[10px] text-warn animate-breathe">● 执行中</span>}
        </div>
        <span className="text-[10px] text-white/40">{direction}</span>
      </div>
      <div className="space-y-1 text-[11px] font-mono text-white/70">
        <div className="flex justify-between">
          <span className="text-white/40">仓位</span>
          <span>{whLabel}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-white/40">测试</span>
          <span>{stateLabel}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-white/40">ID</span>
          <span className="truncate max-w-[120px]" title={idDisplay}>{idDisplay || '—'}</span>
        </div>
        {initialIdDisplay && (
          <div className="flex justify-between">
            <span className="text-white/40">初始</span>
            <span className="truncate max-w-[120px] text-white/50" title={initialIdDisplay}>{initialIdDisplay}</span>
          </div>
        )}
        <div className="flex justify-between">
          <span className="text-white/40">按键</span>
          <span>锁扣{slot.lock_button} 托盘{slot.tray_button} 检测{slot.detect_button}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-white/40">id_ok</span>
          <span>{slot.id_ok === 1 ? '可读到宝ID' : '未读到宝ID'}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-white/40">计数</span>
          <span>进仓{slot.in_count} 出仓{slot.out_count}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-white/40">出仓成功/失败</span>
          <span><span className="text-ok">{slot.out_success_count || 0}</span> / <span className="text-bad">{slot.out_failure_count || 0}</span></span>
        </div>
        <div className="flex justify-between">
          <span className="text-white/40">进仓成功/失败</span>
          <span><span className="text-ok">{slot.in_success_count || 0}</span> / <span className="text-bad">{slot.in_failure_count || 0}</span></span>
        </div>
        <div className="flex justify-between">
          <span className="text-white/40">完成</span>
          <span>{completed} / {target || '—'}</span>
        </div>
      </div>
    </div>
  )
}

export function SlotGrid() {
  const { state } = useApp()
  const slots = state.status?.slots || []
  const currentSlot = state.status?.runner.current_slot || 0
  const targetCount = state.status?.config.target_test_count || state.status?.runner.target_test_count || 0
  const slotCount = slots.length

  if (slotCount === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-white/30 text-sm">
        尚未初始化，请先连接设备或启用离线模式
      </div>
    )
  }

  return (
    <div
      className="grid grid-cols-3 gap-2 overflow-auto"
      style={{ maxHeight: 'calc(2 * 320px + 1rem)' }}
    >
      {slots.map(s => (
        <SlotCard key={s.slot_no} slot={s} currentSlot={currentSlot} targetCount={targetCount} />
      ))}
    </div>
  )
}
