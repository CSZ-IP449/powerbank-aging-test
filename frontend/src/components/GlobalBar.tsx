import { useState } from 'react'
import { api } from '@/services/api'
import { useApp } from '@/store/appStore'
import { FLOW_STATE_LABEL, PHASE_LABEL, type Phase } from '@/types/runner'
import { FlowState } from '@/types/runner'
import { Play, Pause, Square, Settings, RefreshCw, Eraser } from 'lucide-react'

export function GlobalBar({ onOpenConfig }: { onOpenConfig: () => void }) {
  const { state, refreshStatus } = useApp()
  const runner = state.status?.runner
  const config = state.status?.config
  const slots = state.status?.slots || []
  const [busy, setBusy] = useState(false)

  const currentSlot = runner?.current_slot || 0
  const slotCount = runner?.slot_count || 0
  const successCount = slots.filter(s => s.test_state === 0x03).length
  const failCount = slots.filter(s => s.test_state === 0x04).length
  const timeoutCount = slots.filter(s => s.test_state === 0x05).length
  const pendingCount = slots.filter(s => s.test_state === 0x00 || s.test_state === 0x01).length

  const phaseLabel = runner ? PHASE_LABEL[runner.current_phase as Phase] : '空闲'
  const flowLabel = runner ? FLOW_STATE_LABEL[runner.flow_state as FlowState] : '空闲'

  async function init() {
    setBusy(true)
    try {
      await api.init()
      await refreshStatus()
    } finally {
      setBusy(false)
    }
  }

  async function start() {
    setBusy(true)
    try {
      await api.start()
    } finally {
      setBusy(false)
    }
  }

  async function pause() {
    await api.pause()
  }

  async function resume() {
    await api.resume()
  }

  async function stop() {
    setBusy(true)
    try {
      await api.stop()
    } finally {
      setBusy(false)
    }
  }

  async function refresh() {
    setBusy(true)
    try {
      await api.refresh()
      await refreshStatus()
    } finally {
      setBusy(false)
    }
  }

  async function clearStats() {
    if (!window.confirm('确认清零所有槽位的累计统计？该操作会记入日志且不可恢复。')) return
    setBusy(true)
    try {
      await api.clearStats('all')
      await refreshStatus()
    } finally {
      setBusy(false)
    }
  }

  const isRunning = runner?.flow_state && ![FlowState.Idle, FlowState.Completed, FlowState.Fault, FlowState.Paused].includes(runner.flow_state as FlowState)
  const isPaused = runner?.flow_state === FlowState.Paused
  const isFault = runner?.flow_state === FlowState.Fault

  return (
    <div className="space-y-3 border-b border-white/5 pb-3">
      <div className="flex items-center justify-between text-sm">
        <div className="flex items-center gap-4 text-white/70">
          <span className="font-semibold text-white">进出仓老化测试</span>
          <span className="text-white/40">{runner?.cabinet_model || '--'}</span>
          <span className="text-white/40">{slotCount} 槽位</span>
        </div>
        <div className="flex items-center gap-2 text-xs text-white/40">
          <span className={`h-1.5 w-1.5 rounded-full ${state.sseConnected ? 'bg-ok' : 'bg-bad'}`} />
          {state.sseConnected ? '已订阅' : '未订阅'}
          <span className="ml-2 rounded bg-white/10 px-1.5 py-0.5 text-[10px] text-white/60">
            v11.5
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
        <Info label="目标次数" value={config?.target_test_count?.toString() || '--'} />
        <Info label="当前轮次" value={(runner?.current_round || 0).toString()} />
        <Info label="当前阶段" value={phaseLabel} />
        <Info label="当前槽位" value={slotCount > 0 ? `${currentSlot}/${slotCount}` : '--'} />
      </div>

      <div className="grid grid-cols-4 gap-2 text-xs">
        <Info label="成功" value={successCount.toString()} color="text-ok" />
        <Info label="失败" value={failCount.toString()} color="text-bad" />
        <Info label="超时" value={timeoutCount.toString()} color="text-warn" />
        <Info label="等待" value={pendingCount.toString()} color="text-white/50" />
      </div>

      <div className="flex items-center justify-between">
        <div className="text-xs text-white/50">
          状态：<span className={isFault ? 'text-bad' : 'text-white/80'}>{flowLabel}</span>
          {isFault && <span className="ml-2 text-bad/80">· 请排查后点击启动重试</span>}
        </div>
        <div className="flex items-center gap-2">
          <button onClick={init} disabled={busy} className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded border border-white/10 hover:bg-white/5 disabled:opacity-50">
            <RefreshCw className="h-3 w-3" /> 初始化
          </button>
          <button onClick={refresh} disabled={busy} className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded border border-white/10 hover:bg-white/5 disabled:opacity-50">
            <RefreshCw className="h-3 w-3" /> 刷新
          </button>
          <button onClick={onOpenConfig} className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded border border-white/10 hover:bg-white/5">
            <Settings className="h-3 w-3" /> 配置
          </button>
          <button onClick={clearStats} disabled={busy || isRunning || isPaused} className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded border border-white/10 hover:bg-white/5 disabled:opacity-50">
            <Eraser className="h-3 w-3" /> 清零统计
          </button>
          {!isRunning && !isPaused ? (
            <button onClick={start} disabled={busy} className="flex items-center gap-1 text-xs px-3 py-1.5 rounded bg-ok/20 border border-ok/40 text-ok hover:bg-ok/30 disabled:opacity-50">
              <Play className="h-3 w-3" /> 启动
            </button>
          ) : isPaused ? (
            <button onClick={resume} className="flex items-center gap-1 text-xs px-3 py-1.5 rounded bg-ok/20 border border-ok/40 text-ok hover:bg-ok/30">
              <Play className="h-3 w-3" /> 继续
            </button>
          ) : (
            <button onClick={pause} className="flex items-center gap-1 text-xs px-3 py-1.5 rounded bg-warn/20 border border-warn/40 text-warn hover:bg-warn/30">
              <Pause className="h-3 w-3" /> 暂停
            </button>
          )}
          <button onClick={stop} disabled={!isRunning && !isPaused} className="flex items-center gap-1 text-xs px-3 py-1.5 rounded bg-bad/20 border border-bad/40 text-bad hover:bg-bad/30 disabled:opacity-50">
            <Square className="h-3 w-3" /> 停止
          </button>
        </div>
      </div>
    </div>
  )
}

function Info({ label, value, color = 'text-white' }: { label: string; value: string; color?: string }) {
  return (
    <div className="rounded border border-white/5 bg-base-800 px-2.5 py-1.5">
      <div className="text-[10px] text-white/40">{label}</div>
      <div className={`text-sm font-mono ${color}`}>{value}</div>
    </div>
  )
}
