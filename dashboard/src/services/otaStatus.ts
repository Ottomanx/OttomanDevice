import { supabase } from '../lib/supabase'
import type { DeviceOtaStatus, OtaStatus } from '../types/ota'

interface DeviceOtaStatusRow {
  device_id: string
  current_version: string | null
  target_version: string | null
  status: string
  message: string | null
  progress: number | null
  package_id: string | null
  updated_at: string
  devices_enhanced:
    | { computer_name: string | null; hostname: string | null }
    | { computer_name: string | null; hostname: string | null }[]
    | null
}

function resolveDeviceName(
  device: DeviceOtaStatusRow['devices_enhanced'],
  deviceId: string,
): string | null {
  if (!device) {
    return deviceId
  }

  const entry = Array.isArray(device) ? device[0] : device
  if (!entry) {
    return deviceId
  }

  return entry.computer_name || entry.hostname || deviceId
}

function mapOtaStatusRow(row: DeviceOtaStatusRow): DeviceOtaStatus {
  return {
    device_id: row.device_id,
    current_version: row.current_version,
    target_version: row.target_version,
    status: row.status as OtaStatus,
    message: row.message,
    progress: row.progress ?? 0,
    package_id: row.package_id,
    updated_at: row.updated_at,
    device_name: resolveDeviceName(row.devices_enhanced, row.device_id),
  }
}

export async function fetchDeviceOtaStatuses(): Promise<DeviceOtaStatus[]> {
  const { data, error } = await supabase
    .from('device_ota_status')
    .select(
      `
        device_id,
        current_version,
        target_version,
        status,
        message,
        progress,
        package_id,
        updated_at,
        devices_enhanced (computer_name, hostname)
      `,
    )
    .order('updated_at', { ascending: false })

  if (error) {
    throw new Error(error.message)
  }

  return ((data ?? []) as unknown as DeviceOtaStatusRow[]).map(mapOtaStatusRow)
}
