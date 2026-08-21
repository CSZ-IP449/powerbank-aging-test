import { useState } from 'react'
import { api } from '@/services/api'
import { useApp } from '@/store/appStore'
import type { DeviceInfo } from '@/types/comm'
import { ConnectionStatus, CONNECTION_STATUS_LABEL } from '@/types/comm'

function StatusDot({ status }: { status: string }) {
  const color =
    status === ConnectionStatus.Connected ? 'bg-ok' :
    status === ConnectionStatus.Connecting ? 'bg-warn animate-breathe' :
    status === ConnectionStatus.Error ? 'bg-bad' :
    'bg-white/30'
  return <span className={`inline-block h-2 w-2 rounded-full ${color}`} />
}

function DeviceConnect({ device }: { device: 'cabinet' | 'fixture' }) {
  const { state, refreshStatus } = useApp()
  const info: DeviceInfo | undefined = state.status?.[device]
  const [ports, setPorts] = useState<string[]>([])
  const [port, setPort] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const label = device === 'cabinet' ? '充电柜' : '测试工装'

  async function loadPorts() {
    try {
      const { ports } = await api.ports()
      setPorts(ports)
      if (!port && ports.length) setPort(ports[0])
    } catch (e) {
      setError(String(e))
    }
  }

  async function connect() {
    if (!port) return
    setBusy(true)
    setError(null)
    try {
      const fn = device === 'cabinet' ? api.connectCabinet : api.connectFixture
      const res = await fn(port, 115200)
      if (!res.ok) setError(res.error || '连接失败')
      await refreshStatus()
    } catch (e) {
      setError(String(e))
    } finally {
      setBusy(false)
    }
  }

  async function disconnect() {
    setBusy(true)
    try {
      const fn = device === 'cabinet' ? api.disconnectCabinet : api.disconnectFixture
      await fn()
      await refreshStatus()
    } finally {
      setBusy(false)
    }
  }

  const isConnected = info?.status === ConnectionStatus.Connected

  return (
    <div className="rounded-lg border border-white/10 bg-base-800 p-3">
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2 text-sm text-white/80">
          <StatusDot status={info?.status || 'disconnected'} />
          <span>{label}</span>
        </div>
        <span className="text-[11px] text-white/40 font-mono">
          {info?.status ? CONNECTION_STATUS_LABEL[info.status as ConnectionStatus] : '未连接'}
        </span>
      </div>
      {isConnected ? (
        <div className="flex items-center justify-between">
          <div className="text-xs text-white/60 font-mono truncate">
            {info?.port} @ {info?.baudrate}
          </div>
          <button
            onClick={disconnect}
            disabled={busy}
            className="text-xs px-2 py-1 rounded border border-white/10 hover:bg-white/5 disabled:opacity-50"
          >
            断开
          </button>
        </div>
      ) : (
        <div className="space-y-2">
          <div className="flex gap-1">
            <select
              value={port}
              onClick={loadPorts}
              onChange={e => setPort(e.target.value)}
              className="flex-1 h-8 px-2 text-xs rounded bg-base-700 border border-white/10 text-white"
            >
              {ports.length === 0 && <option value="">点击选择端口</option>}
              {ports.map(p => <option key={p} value={p}>{p}</option>)}
            </select>
            <button
              onClick={loadPorts}
              className="text-xs px-2 py-1 rounded border border-white/10 hover:bg-white/5"
            >
              刷新
            </button>
          </div>
          <button
            onClick={connect}
            disabled={busy || !port}
            className="w-full h-8 text-xs rounded bg-cyan/20 border border-cyan/30 text-cyan hover:bg-cyan/30 disabled:opacity-50"
          >
            {busy ? '连接中...' : '连接'}
          </button>
          {error && <div className="text-xs text-bad">{error}</div>}
        </div>
      )}
      {info?.error_message && (
        <div className="text-xs text-bad mt-2">{info.error_message}</div>
      )}
    </div>
  )
}

export function ConnectionPanel() {
  const { refreshStatus } = useApp()
  const [busy, setBusy] = useState(false)

  async function enableMock() {
    setBusy(true)
    try {
      await api.enableMock()
      await api.init()
      await refreshStatus()
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="space-y-3">
      <DeviceConnect device="cabinet" />
      <DeviceConnect device="fixture" />
      <div className="rounded-lg border border-white/10 bg-base-800 p-3">
        <div className="text-xs text-white/50 mb-2">无硬件时可使用离线模式开发调试</div>
        <button
          onClick={enableMock}
          disabled={busy}
          className="w-full h-8 text-xs rounded border border-white/10 hover:bg-white/5 disabled:opacity-50"
        >
          {busy ? '启动中...' : '启用离线模式'}
        </button>
      </div>
    </div>
  )
}
