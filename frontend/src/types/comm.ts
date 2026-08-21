export enum DeviceType {
  Cabinet = 'cabinet',
  Fixture = 'fixture',
  Mock = 'mock',
}

export enum ConnectionStatus {
  Disconnected = 'disconnected',
  Connecting = 'connecting',
  Connected = 'connected',
  Error = 'error',
}

export const CONNECTION_STATUS_LABEL: Record<ConnectionStatus, string> = {
  [ConnectionStatus.Disconnected]: '未连接',
  [ConnectionStatus.Connecting]: '连接中',
  [ConnectionStatus.Connected]: '已连接',
  [ConnectionStatus.Error]: '通信异常',
}

export interface DeviceInfo {
  device_type: DeviceType
  port: string
  baudrate: number
  status: ConnectionStatus
  error_message: string | null
}

export interface CommLogEntry {
  id: number
  timestamp: string
  direction: 'send' | 'recv'
  device: DeviceType
  raw_hex: string
  parsed: string
  slot_no: number | null
}

export interface OperationLogEntry {
  id: number
  timestamp: string
  action: string
  detail: string
}
