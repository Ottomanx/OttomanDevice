import { createDeviceCommand, fetchDeviceCommand } from './commands'
import type { DeviceCommandType } from '../types/device'
import type { BulkDeviceResult } from '../types/fleetOperations'

const POLL_INTERVAL_MS = 2_000
const COMMAND_TIMEOUT_MS = 60_000

export async function runDeviceCommand(
  deviceId: string,
  command: DeviceCommandType,
): Promise<BulkDeviceResult> {
  try {
    const created = await createDeviceCommand(deviceId, command)
    const startedAt = Date.now()

    while (Date.now() - startedAt < COMMAND_TIMEOUT_MS) {
      const updated = await fetchDeviceCommand(created.id)

      if (updated.status === 'DONE') {
        return { deviceId, success: true }
      }

      await sleep(POLL_INTERVAL_MS)
    }

    return { deviceId, success: false, reason: 'Command timed out' }
  } catch (err) {
    return {
      deviceId,
      success: false,
      reason: err instanceof Error ? err.message : 'Failed to run command',
    }
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms)
  })
}
