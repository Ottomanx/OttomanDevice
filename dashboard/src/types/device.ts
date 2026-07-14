export type DeviceCommandType = 'PING' | 'HEARTBEAT' | 'CAMERA_TEST' | 'SCREENSHOT'

export type DeviceCommandStatus = 'PENDING' | 'DONE'

export type CommandFeedbackStatus = 'idle' | 'queued' | 'running' | 'done' | 'failed'

export interface DeviceEnhanced {
  id: string
  device_id: string
  computer_name: string | null
  operating_system: string | null
  python_version: string | null
  firmware_version: string | null
  status: string | null
  last_online_at: string | null
  created_at: string
  cpu_usage: number | null
  ram_usage: number | null
  disk_usage: number | null
  hostname: string | null
  local_ip: string | null
  system_uptime: number | null
  camera_available: boolean | null
}

export interface DeviceCommand {
  id: string
  device_id: string
  command: DeviceCommandType
  status: DeviceCommandStatus
  created_at: string
  executed_at: string | null
}

export interface ScreenshotItem {
  name: string
  url: string
  createdAt: string | null
}

export type OnlineStatus = 'online' | 'offline' | 'unknown'
