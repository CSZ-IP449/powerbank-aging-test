import { useState } from 'react'
import { AppProvider } from '@/store/appStore'
import { ConnectionPanel } from '@/components/ConnectionPanel'
import { GlobalBar } from '@/components/GlobalBar'
import { SlotGrid } from '@/components/SlotGrid'
import { ConfigDialog } from '@/components/ConfigDialog'
import { ProtocolDebug } from '@/components/ProtocolDebug'

function MainView() {
  const [configOpen, setConfigOpen] = useState(false)

  return (
    <div className="min-h-screen bg-base-900 text-white">
      <div className="mx-auto max-w-[1600px] p-4 space-y-3">
        <GlobalBar onOpenConfig={() => setConfigOpen(true)} />

        <div className="grid grid-cols-[260px_1fr] gap-3">
          <div className="space-y-3">
            <ConnectionPanel />
            <ProtocolDebug />
          </div>
          <div>
            <SlotGrid />
          </div>
        </div>

        <div className="flex items-center justify-between border-t border-white/5 pt-3 font-mono text-[11px] text-white/35">
          <span>© 2026 进出仓老化测试</span>
          <span className="flex items-center gap-1.5">
            <span className="h-1.5 w-1.5 rounded-full bg-ok animate-breathe" />
            桌面版 v0.1.0
          </span>
        </div>
      </div>

      <ConfigDialog open={configOpen} onClose={() => setConfigOpen(false)} />
    </div>
  )
}

export default function App() {
  return (
    <AppProvider>
      <MainView />
    </AppProvider>
  )
}
