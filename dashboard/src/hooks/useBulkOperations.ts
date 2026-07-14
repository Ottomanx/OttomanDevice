import { useCallback, useRef, useState } from 'react'

import { runDeviceCommand } from '../services/bulkCommands'
import type { BulkActionType, BulkOperationProgress } from '../types/fleetOperations'
import { INITIAL_BULK_PROGRESS, bulkActionToCommand } from '../types/fleetOperations'
import { executeBulkCommands, resetBulkProgress } from '../utils/bulkOperations'

interface UseBulkOperationsResult {
  progress: BulkOperationProgress
  isRunning: boolean
  runBulkAction: (deviceIds: readonly string[], action: BulkActionType) => Promise<void>
  clearProgress: () => void
}

const PROGRESS_CLEAR_MS = 8_000

export function useBulkOperations(): UseBulkOperationsResult {
  const [progress, setProgress] = useState<BulkOperationProgress>(INITIAL_BULK_PROGRESS)
  const clearTimerRef = useRef<number | null>(null)

  const clearProgressTimer = useCallback(() => {
    if (clearTimerRef.current !== null) {
      window.clearTimeout(clearTimerRef.current)
      clearTimerRef.current = null
    }
  }, [])

  const clearProgress = useCallback(() => {
    clearProgressTimer()
    setProgress(resetBulkProgress())
  }, [clearProgressTimer])

  const runBulkAction = useCallback(
    async (deviceIds: readonly string[], action: BulkActionType) => {
      if (deviceIds.length === 0 || progress.phase === 'running') {
        return
      }

      clearProgressTimer()
      const command = bulkActionToCommand(action)

      await executeBulkCommands(
        deviceIds,
        command,
        runDeviceCommand,
        setProgress,
        action,
      )

      clearTimerRef.current = window.setTimeout(() => {
        setProgress(resetBulkProgress())
      }, PROGRESS_CLEAR_MS)
    },
    [clearProgressTimer, progress.phase],
  )

  return {
    progress,
    isRunning: progress.phase === 'running',
    runBulkAction,
    clearProgress,
  }
}
