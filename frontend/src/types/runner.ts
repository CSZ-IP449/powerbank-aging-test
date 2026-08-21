export enum FlowState {
  Idle = 'idle',
  Initializing = 'initializing',
  Ready = 'ready',
  Precheck = 'precheck',
  CommandSent = 'command_sent',
  WaitResult = 'wait_result',
  Evaluating = 'evaluating',
  Recording = 'recording',
  NextSlot = 'next_slot',
  Paused = 'paused',
  Stopping = 'stopping',
  Completed = 'completed',
  Fault = 'fault',
}

export const FLOW_STATE_LABEL: Record<FlowState, string> = {
  [FlowState.Idle]: '空闲',
  [FlowState.Initializing]: '初始化中',
  [FlowState.Ready]: '就绪',
  [FlowState.Precheck]: '前置检查',
  [FlowState.CommandSent]: '指令已发',
  [FlowState.WaitResult]: '等待结果',
  [FlowState.Evaluating]: '判定中',
  [FlowState.Recording]: '记录中',
  [FlowState.NextSlot]: '切换槽位',
  [FlowState.Paused]: '已暂停',
  [FlowState.Stopping]: '停止中',
  [FlowState.Completed]: '已完成',
  [FlowState.Fault]: '故障',
}

export type Phase = 'idle' | 'out_warehouse' | 'in_warehouse'

export const PHASE_LABEL: Record<Phase, string> = {
  idle: '空闲',
  out_warehouse: '整柜出仓',
  in_warehouse: '整柜进仓',
}

export interface RunnerState {
  target_test_count: number
  current_round: number
  current_phase: Phase
  current_slot: number
  flow_state: FlowState
  cabinet_model: string
  slot_count: number
  started_at: string | null
}
