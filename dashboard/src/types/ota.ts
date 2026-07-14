export type OtaStatus =
  | 'idle'
  | 'checking'
  | 'downloading'
  | 'verifying'
  | 'installing'
  | 'completed'
  | 'failed'
  | 'rollback'

export interface DeviceOtaStatus {
  device_id: string
  current_version: string | null
  target_version: string | null
  status: OtaStatus
  message: string | null
  progress: number
  package_id: string | null
  updated_at: string
  device_name: string | null
}

export function otaStatusLabel(status: OtaStatus): string {
  switch (status) {
    case 'idle':
      return 'Idle'
    case 'checking':
      return 'Checking'
    case 'downloading':
      return 'Downloading'
    case 'verifying':
      return 'Verifying'
    case 'installing':
      return 'Installing'
    case 'completed':
      return 'Completed'
    case 'failed':
      return 'Failed'
    case 'rollback':
      return 'Rollback'
    default:
      return status
  }
}

export function otaInstallResult(status: OtaStatus, message: string | null): string {
  if (status === 'completed') {
    return message ?? 'Install completed'
  }

  if (status === 'failed') {
    return message ?? 'Install failed'
  }

  if (status === 'rollback') {
    return message ?? 'Rolling back'
  }

  return message ?? '—'
}
