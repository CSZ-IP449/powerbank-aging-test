import { useState } from 'react'
import { X, Save } from 'lucide-react'
import { api } from '@/services/api'
import { useApp } from '@/store/appStore'
import type { TestConfig } from '@/types/config'

export function ConfigDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { state, refreshStatus } = useApp()
  const cfg = state.status?.config
  const [target, setTarget] = useState(cfg?.target_test_count ?? 100)
  const [retry, setRetry] = useState(cfg?.max_retry ?? 0)
  const [timeoutMs, setTimeoutMs] = useState(cfg?.slot_timeout_ms ?? 5000)
  const [intervalMs, setIntervalMs] = useState(cfg?.phase_interval_ms ?? 3000)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!open) return null

  async function save() {
    setSaving(true)
    setError(null)
    try {
      const cfg: Partial<TestConfig> = {
        target_test_count: target,
        max_retry: retry,
        slot_timeout_ms: timeoutMs,
        phase_interval_ms: intervalMs,
      }
      await api.setConfig(cfg)
      await refreshStatus()
      onClose()
    } catch (e) {
      setError(String(e))
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/60 backdrop-blur-sm pt-12">
      <div className="w-full max-w-md rounded-2xl border border-white/10 bg-base-900 shadow-2xl">
        <div className="flex items-center justify-between border-b border-white/10 px-5 py-4">
          <h2 className="text-base font-semibold text-white">测试配置</h2>
          <button onClick={onClose} className="rounded-md p-1 text-white/50 hover:bg-white/10 hover:text-white">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="space-y-4 px-5 py-5">
          <Field label="目标完整测试次数">
            <input type="number" min={1} max={100000} value={target}
              onChange={e => setTarget(Number(e.target.value))}
              className="h-9 w-full rounded-lg border border-white/10 bg-base-800 px-3 text-sm text-white outline-none focus:border-cyan" />
          </Field>
          <Field label="最大重试次数（仅失败）">
            <input type="number" min={0} max={10} value={retry}
              onChange={e => setRetry(Number(e.target.value))}
              className="h-9 w-full rounded-lg border border-white/10 bg-base-800 px-3 text-sm text-white outline-none focus:border-cyan" />
          </Field>
          <Field label="单槽超时（毫秒）">
            <input type="number" min={1000} max={30000} step={500} value={timeoutMs}
              onChange={e => setTimeoutMs(Number(e.target.value))}
              className="h-9 w-full rounded-lg border border-white/10 bg-base-800 px-3 text-sm text-white outline-none focus:border-cyan" />
            <div className="text-[10px] text-white/40 mt-1">出仓和进仓均为 5000ms</div>
          </Field>
          <Field label="阶段切换间隔（毫秒）">
            <input type="number" min={0} max={60000} step={500} value={intervalMs}
              onChange={e => setIntervalMs(Number(e.target.value))}
              className="h-9 w-full rounded-lg border border-white/10 bg-base-800 px-3 text-sm text-white outline-none focus:border-cyan" />
            <div className="text-[10px] text-white/40 mt-1">出仓→进仓、进仓→下一轮出仓之间</div>
          </Field>
          {error && <div className="text-xs text-bad">{error}</div>}
        </div>
        <div className="flex justify-end gap-2 border-t border-white/10 px-5 py-4">
          <button onClick={onClose} className="text-xs px-3 py-1.5 rounded border border-white/10 hover:bg-white/5">取消</button>
          <button onClick={save} disabled={saving}
            className="flex items-center gap-1 text-xs px-3 py-1.5 rounded bg-cyan/20 border border-cyan/40 text-cyan hover:bg-cyan/30 disabled:opacity-50">
            <Save className="h-3 w-3" /> 保存
          </button>
        </div>
      </div>
    </div>
  )
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-xs text-white/60 mb-1.5">{label}</label>
      {children}
    </div>
  )
}
