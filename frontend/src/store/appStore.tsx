import React, { createContext, useContext, useEffect, useReducer, useRef, useCallback } from 'react'
import { api, subscribeSSE, type FullStatus, type SseEvent } from '@/services/api'
import type { SlotView } from '@/types/slot'
import type { RunnerState } from '@/types/runner'
import type { DeviceInfo, CommLogEntry } from '@/types/comm'

const COMM_LOG_MAX = 300

interface AppState {
  status: FullStatus | null
  commLogs: CommLogEntry[]
  sseConnected: boolean
  loading: boolean
  error: string | null
}

type Action =
  | { type: 'SET_STATUS'; payload: FullStatus }
  | { type: 'UPDATE_RUNNER'; payload: RunnerState }
  | { type: 'UPDATE_SLOT'; payload: SlotView & { slot_no: number } }
  | { type: 'UPDATE_CONNECTION'; payload: { device: string; status: string; error: string | null } }
  | { type: 'APPEND_COMM'; payload: CommLogEntry }
  | { type: 'SET_COMM_LOGS'; payload: CommLogEntry[] }
  | { type: 'CLEAR_SLOTS' }
  | { type: 'SET_SSE'; payload: boolean }
  | { type: 'SET_LOADING'; payload: boolean }
  | { type: 'SET_ERROR'; payload: string | null }

const initialState: AppState = {
  status: null,
  commLogs: [],
  sseConnected: false,
  loading: false,
  error: null,
}

function reducer(state: AppState, action: Action): AppState {
  switch (action.type) {
    case 'SET_STATUS':
      return { ...state, status: action.payload, error: null }
    case 'UPDATE_RUNNER': {
      if (!state.status) return state
      return { ...state, status: { ...state.status, runner: action.payload } }
    }
    case 'UPDATE_SLOT': {
      if (!state.status) return state
      const idx = state.status.slots.findIndex(s => s.slot_no === action.payload.slot_no)
      if (idx < 0) return state
      const slots = [...state.status.slots]
      slots[idx] = { ...slots[idx], ...action.payload }
      return { ...state, status: { ...state.status, slots } }
    }
    case 'UPDATE_CONNECTION': {
      if (!state.status) return state
      const { device, status, error } = action.payload
      const key = device === 'cabinet' ? 'cabinet' : 'fixture'
      const old: DeviceInfo = state.status[key]
      return {
        ...state,
        status: {
          ...state.status,
          [key]: { ...old, status: status as DeviceInfo['status'], error_message: error },
        },
      }
    }
    case 'APPEND_COMM': {
      const logs = [...state.commLogs, action.payload]
      if (logs.length > COMM_LOG_MAX) logs.splice(0, logs.length - COMM_LOG_MAX)
      return { ...state, commLogs: logs }
    }
    case 'SET_COMM_LOGS':
      return { ...state, commLogs: action.payload.slice(-COMM_LOG_MAX) }
    case 'CLEAR_SLOTS': {
      if (!state.status) return state
      return { ...state, status: { ...state.status, slots: [], runner: { ...state.status.runner, slot_count: 0, current_slot: 0 } } }
    }
    case 'SET_SSE':
      return { ...state, sseConnected: action.payload }
    case 'SET_LOADING':
      return { ...state, loading: action.payload }
    case 'SET_ERROR':
      return { ...state, error: action.payload }
    default:
      return state
  }
}

interface AppContextValue {
  state: AppState
  refreshStatus: () => Promise<void>
  loadCommLogs: () => Promise<void>
  clearError: () => void
}

const AppContext = createContext<AppContextValue | null>(null)

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [state, dispatch] = useReducer(reducer, initialState)
  const stateRef = useRef(state)
  stateRef.current = state

  const refreshStatus = useCallback(async () => {
    dispatch({ type: 'SET_LOADING', payload: true })
    try {
      const s = await api.status()
      dispatch({ type: 'SET_STATUS', payload: s })
    } catch (e) {
      dispatch({ type: 'SET_ERROR', payload: String(e) })
    } finally {
      dispatch({ type: 'SET_LOADING', payload: false })
    }
  }, [])

  const loadCommLogs = useCallback(async () => {
    try {
      const { logs } = await api.commLogs(200)
      dispatch({ type: 'SET_COMM_LOGS', payload: logs })
    } catch (e) {
      console.warn('load comm logs failed', e)
    }
  }, [])

  useEffect(() => {
    refreshStatus()
    loadCommLogs()
    const unsub = subscribeSSE((e: SseEvent) => {
      dispatch({ type: 'SET_SSE', payload: true })
      switch (e.event) {
        case 'hello':
          break
        case 'state':
          dispatch({ type: 'UPDATE_RUNNER', payload: e.data })
          break
        case 'slot':
          dispatch({ type: 'UPDATE_SLOT', payload: e.data })
          break
        case 'connection':
          dispatch({ type: 'UPDATE_CONNECTION', payload: e.data })
          break
        case 'comm':
          dispatch({ type: 'APPEND_COMM', payload: e.data })
          break
        case 'slots_cleared':
          dispatch({ type: 'CLEAR_SLOTS' })
          break
      }
    })
    return unsub
  }, [refreshStatus, loadCommLogs])

  const clearError = useCallback(() => dispatch({ type: 'SET_ERROR', payload: null }), [])

  const value: AppContextValue = { state, refreshStatus, loadCommLogs, clearError }
  return React.createElement(AppContext.Provider, { value }, children)
}

export function useApp() {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be used within AppProvider')
  return ctx
}
