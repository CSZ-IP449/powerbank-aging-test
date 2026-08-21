import { useState, useMemo } from 'react'
import { useApp } from '@/store/appStore'
import { api } from '@/services/api'
import { Eraser, Filter, Send } from 'lucide-react'

const COMMAND_NAMES: Record<number, string> = {
  0x01: '查询柜型',
  0x02: '槽位状态',
  0x03: '工装进仓',
  0x04: '柜出仓',
}

const ADDRESS_NAMES: Record<number, string> = {
  0xA0: '柜',
  0xA1: '工',
}

const COMMANDS_NEED_SLOT = [0x02, 0x03, 0x04]

type DeviceFilter = 'all' | 'cabinet' | 'fixture' | 'mock'

function parseFrame(rawHex: string): { addr: string; cmd: string; cmdName: string } | null {
  // rawHex 形如 "7E A0 03 04 01 9A B7 7E"
  const tokens = rawHex.trim().split(/\s+/)
  if (tokens.length < 4) return null
  // 跳过开头的 7E，依次是 addr control cmd ...
  let idx = 0
  if (tokens[0].toUpperCase() === '7E') idx = 1
  const addrByte = parseInt(tokens[idx], 16)
  const cmdByte = parseInt(tokens[idx + 2], 16)
  if (Number.isNaN(addrByte) || Number.isNaN(cmdByte)) return null
  const addr = ADDRESS_NAMES[addrByte] || `${addrByte.toString(16).toUpperCase().padStart(2, '0')}`
  const cmdName = COMMAND_NAMES[cmdByte] || `0x${cmdByte.toString(16).toUpperCase().padStart(2, '0')}`
  return {
    addr,
    cmd: `0x${cmdByte.toString(16).toUpperCase().padStart(2, '0')}`,
    cmdName,
  }
}

export function ProtocolDebug() {
  const { state } = useApp()
  const [filter, setFilter] = useState<DeviceFilter>('all')
  const [minId, setMinId] = useState(0)
  const [sendAddr, setSendAddr] = useState(0xA0)
  const [sendCmd, setSendCmd] = useState(0x02)
  const [sendSlot, setSendSlot] = useState(1)
  const [sending, setSending] = useState(false)
  const [lastReq, setLastReq] = useState('')
  const [lastResp, setLastResp] = useState('')
  const [lastParsed, setLastParsed] = useState('')
  const [sendError, setSendError] = useState('')

  const filteredLogs = useMemo(() => {
    let logs = state.commLogs
    if (filter !== 'all') {
      logs = logs.filter(l => l.device === filter)
    }
    if (minId > 0) {
      // 仅本地清空：只显示清空后追加的新报文
      logs = logs.filter(l => l.id > minId)
    }
    return logs
  }, [state.commLogs, filter, minId])

  function clearDisplay() {
    const last = state.commLogs[state.commLogs.length - 1]
    setMinId(last ? last.id : 0)
  }

  async function handleSend() {
    setSending(true)
    setSendError('')
    try {
      const slot = COMMANDS_NEED_SLOT.includes(sendCmd) ? sendSlot : undefined
      const r = await api.debugSend(sendAddr, sendCmd, slot)
      if (r.ok) {
        setLastReq(r.request_hex || '')
        setLastResp(r.response_hex || '')
        setLastParsed(r.parsed ? JSON.stringify(r.parsed) : '')
      } else {
        setSendError(r.error || '发送失败')
        setLastReq(r.request_hex || '')
        setLastResp('')
        setLastParsed('')
      }
    } catch (e) {
      setSendError(String(e))
    } finally {
      setSending(false)
    }
  }

  const connected = state.status?.cabinet?.status === 'connected' || state.status?.fixture?.status === 'connected' || !!state.status?.runner?.cabinet_model

  return (
    <div className="rounded-lg border border-white/10 bg-base-800">
      <div className="flex items-center justify-between border-b border-white/10 px-3 py-2">
        <span className="text-xs text-white/70">协议报文（{filteredLogs.length} 条）</span>
        <div className="flex items-center gap-2">
          <Filter className="h-3 w-3 text-white/30" />
          <select
            value={filter}
            onChange={e => setFilter(e.target.value as DeviceFilter)}
            className="h-6 px-1.5 text-[11px] rounded bg-base-700 border border-white/10 text-white/80"
          >
            <option value="all">全部</option>
            <option value="cabinet">仅柜</option>
            <option value="fixture">仅工</option>
            <option value="mock">仅 Mock</option>
          </select>
          <button
            onClick={clearDisplay}
            className="flex items-center gap-1 text-[11px] px-1.5 py-0.5 rounded border border-white/10 hover:bg-white/5 text-white/60"
            title="清空当前显示（不影响日志文件）"
          >
            <Eraser className="h-3 w-3" /> 清空
          </button>
        </div>
      </div>
      <div className="px-3 py-1 text-[10px] text-white/30 font-mono border-b border-white/5">
        HDLC · A0 充电柜 · A1 工装 · 7E 起止 · 7D 转义
      </div>

      {/* 手动发送区 */}
      <div className="border-b border-white/10 px-3 py-2 space-y-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[11px] text-white/50">设备</span>
          <select
            value={sendAddr}
            onChange={e => setSendAddr(parseInt(e.target.value, 10))}
            className="h-6 px-1.5 text-[11px] rounded bg-base-700 border border-white/10 text-white/80"
          >
            <option value={0xA0}>充电柜 (0xA0)</option>
            <option value={0xA1}>测试工装 (0xA1)</option>
          </select>
          <span className="text-[11px] text-white/50 ml-1">命令</span>
          <select
            value={sendCmd}
            onChange={e => setSendCmd(parseInt(e.target.value, 10))}
            className="h-6 px-1.5 text-[11px] rounded bg-base-700 border border-white/10 text-white/80"
          >
            <option value={0x01}>查询柜型 (0x01)</option>
            <option value={0x02}>槽位状态 (0x02)</option>
            <option value={0x03}>工装进仓 (0x03)</option>
            <option value={0x04}>柜出仓 (0x04)</option>
          </select>
          {COMMANDS_NEED_SLOT.includes(sendCmd) && (
            <>
              <span className="text-[11px] text-white/50 ml-1">槽位</span>
              <input
                type="number"
                min={1}
                max={128}
                value={sendSlot}
                onChange={e => setSendSlot(Math.max(1, Math.min(128, parseInt(e.target.value) || 1)))}
                className="h-6 w-14 px-1.5 text-[11px] rounded bg-base-700 border border-white/10 text-white/80"
              />
            </>
          )}
          <button
            onClick={handleSend}
            disabled={sending || !connected}
            className="flex items-center gap-1 text-[11px] px-2 py-0.5 rounded bg-cyan/20 border border-cyan/40 text-cyan hover:bg-cyan/30 disabled:opacity-40 disabled:cursor-not-allowed"
            title={connected ? '发送指令' : '请先连接设备或启用模拟模式'}
          >
            <Send className="h-3 w-3" /> {sending ? '发送中...' : '发送'}
          </button>
        </div>

        {(lastReq || lastResp || sendError) && (
          <div className="font-mono text-[10px] space-y-0.5">
            {lastReq && (
              <div className="text-cyan">→ {lastReq}</div>
            )}
            {lastResp && (
              <div className="text-ok">← {lastResp}</div>
            )}
            {lastParsed && (
              <div className="text-white/50">解析: {lastParsed}</div>
            )}
            {sendError && (
              <div className="text-bad">错误: {sendError}</div>
            )}
          </div>
        )}
      </div>
      <div className="overflow-auto max-h-[300px] font-mono text-[11px]">
        {filteredLogs.length === 0 ? (
          <div className="p-3 text-white/30">{minId > 0 ? '已清空显示，等待新报文' : '暂无通信记录'}</div>
        ) : (
          <table className="w-full">
            <thead className="sticky top-0 bg-base-900 text-white/40">
              <tr>
                <th className="px-2 py-1 text-left">时间</th>
                <th className="px-2 py-1 text-left">设备</th>
                <th className="px-2 py-1 text-left">方向</th>
                <th className="px-2 py-1 text-left">命令</th>
                <th className="px-2 py-1 text-left">槽</th>
                <th className="px-2 py-1 text-left">报文</th>
              </tr>
            </thead>
            <tbody>
              {filteredLogs.slice().reverse().map(l => {
                const parsed = parseFrame(l.raw_hex)
                return (
                  <tr key={l.id} className="border-t border-white/5 hover:bg-white/5">
                    <td className="px-2 py-1 text-white/50">{l.timestamp.split('T')[1] || ''}</td>
                    <td className="px-2 py-1 text-white/70">
                      {l.device === 'cabinet' ? '柜' : l.device === 'fixture' ? '工' : l.device === 'mock' ? 'M' : l.device}
                    </td>
                    <td className="px-2 py-1">
                      <span className={l.direction === 'send' ? 'text-cyan' : 'text-ok'}>
                        {l.direction === 'send' ? '→' : '←'}
                      </span>
                    </td>
                    <td className="px-2 py-1 text-white/70" title={parsed?.cmd || ''}>
                      {parsed?.cmdName || '—'}
                    </td>
                    <td className="px-2 py-1 text-white/60">{l.slot_no ?? '—'}</td>
                    <td className="px-2 py-1 text-white/80 break-all">{l.raw_hex}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}
