import type { DeviceCommandType } from '../types/device'
import type { BulkDeviceResult, BulkOperationProgress } from '../types/fleetOperations'
import { INITIAL_BULK_PROGRESS } from '../types/fleetOperations'

export type BulkCommandRunner = (
  deviceId: string,
  command: DeviceCommandType,
) => Promise<BulkDeviceResult>

export function summarizeBulkResults(results: BulkDeviceResult[]): Pick<
  BulkOperationProgress,
  'completed' | 'successCount' | 'failedCount'
> {
  const successCount = results.filter((result) => result.success).length
  const failedCount = results.length - successCount

  return {
    completed: results.length,
    successCount,
    failedCount,
  }
}

export function buildBulkProgress(
  action: BulkOperationProgress['action'],
  total: number,
  results: BulkDeviceResult[],
  phase: BulkOperationProgress['phase'],
): BulkOperationProgress {
  const summary = summarizeBulkResults(results)

  return {
    phase,
    action,
    total,
    ...summary,
  }
}

export async function executeBulkCommands(
  deviceIds: readonly string[],
  command: DeviceCommandType,
  runner: BulkCommandRunner,
  onProgress?: (progress: BulkOperationProgress) => void,
  action: BulkOperationProgress['action'] = null,
): Promise<BulkDeviceResult[]> {
  const total = deviceIds.length
  const results: BulkDeviceResult[] = []

  onProgress?.(
    buildBulkProgress(action, total, results, 'running'),
  )

  await Promise.all(
    deviceIds.map(async (deviceId) => {
      const result = await runner(deviceId, command)
      results.push(result)
      onProgress?.(
        buildBulkProgress(action, total, results, results.length === total ? 'done' : 'running'),
      )
    }),
  )

  onProgress?.(
    buildBulkProgress(action, total, results, 'done'),
  )

  return results
}

export function resetBulkProgress(): BulkOperationProgress {
  return { ...INITIAL_BULK_PROGRESS }
}
