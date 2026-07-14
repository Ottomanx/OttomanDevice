import type { DeviceCommandType } from './device'

export type BulkActionType = 'restart' | 'screenshot' | 'camera_test' | 'ping'

export type BulkOperationPhase = 'idle' | 'running' | 'done'

export interface BulkDeviceResult {
  deviceId: string
  success: boolean
  reason?: string
}

export interface BulkOperationProgress {
  phase: BulkOperationPhase
  action: BulkActionType | null
  total: number
  completed: number
  successCount: number
  failedCount: number
}

export const INITIAL_BULK_PROGRESS: BulkOperationProgress = {
  phase: 'idle',
  action: null,
  total: 0,
  completed: 0,
  successCount: 0,
  failedCount: 0,
}

export function bulkActionToCommand(action: BulkActionType): DeviceCommandType {
  switch (action) {
    case 'ping':
      return 'PING'
    case 'screenshot':
      return 'SCREENSHOT'
    case 'camera_test':
      return 'CAMERA_TEST'
    case 'restart':
      return 'HEARTBEAT'
  }
}

export function bulkActionLabel(action: BulkActionType): string {
  switch (action) {
    case 'ping':
      return 'Ping'
    case 'screenshot':
      return 'Screenshot'
    case 'camera_test':
      return 'Camera Test'
    case 'restart':
      return 'Restart'
  }
}
