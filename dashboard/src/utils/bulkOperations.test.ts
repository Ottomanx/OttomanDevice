import { describe, expect, it, vi } from 'vitest'

import type { DeviceCommandType } from '../types/device'
import type { BulkDeviceResult } from '../types/fleetOperations'
import {
  buildBulkProgress,
  executeBulkCommands,
  summarizeBulkResults,
} from './bulkOperations'

describe('bulk operations progress', () => {
  it('summarizes success and failed counts', () => {
    const results: BulkDeviceResult[] = [
      { deviceId: 'a', success: true },
      { deviceId: 'b', success: false, reason: 'timeout' },
      { deviceId: 'c', success: true },
    ]

    expect(summarizeBulkResults(results)).toEqual({
      completed: 3,
      successCount: 2,
      failedCount: 1,
    })
  })

  it('updates progress as bulk commands complete', async () => {
    const progressSnapshots: number[] = []
    const runner = vi.fn(async (deviceId: string, _command: DeviceCommandType) => {
      if (deviceId === 'device-b') {
        return { deviceId, success: false, reason: 'offline' }
      }

      return { deviceId, success: true }
    })

    await executeBulkCommands(
      ['device-a', 'device-b', 'device-c'],
      'SCREENSHOT',
      runner,
      (progress) => {
        progressSnapshots.push(progress.completed)
      },
      'screenshot',
    )

    expect(runner).toHaveBeenCalledTimes(3)
    expect(runner).toHaveBeenCalledWith('device-a', 'SCREENSHOT')
    expect(progressSnapshots[0]).toBe(0)
    expect(progressSnapshots[progressSnapshots.length - 1]).toBe(3)
  })

  it('handles partial failures across the selected fleet', async () => {
    const runner = vi.fn(async (deviceId: string) => {
      if (deviceId === 'device-b') {
        return { deviceId, success: false, reason: 'Command timed out' }
      }

      return { deviceId, success: true }
    })

    const results = await executeBulkCommands(['device-a', 'device-b'], 'HEARTBEAT', runner, undefined, 'restart')
    const progress = buildBulkProgress('restart', 2, results, 'done')

    expect(results).toEqual([
      { deviceId: 'device-a', success: true },
      { deviceId: 'device-b', success: false, reason: 'Command timed out' },
    ])
    expect(progress.successCount).toBe(1)
    expect(progress.failedCount).toBe(1)
    expect(progress.completed).toBe(2)
  })
})
