import { useCallback, useEffect, useRef, useState } from 'react'

import { createDeviceCommand, fetchDeviceCommand } from '../services/commands'
import type { CommandFeedbackStatus, DeviceCommandType } from '../types/device'

const POLL_INTERVAL_MS = 2_000
const COMMAND_TIMEOUT_MS = 60_000
const FEEDBACK_CLEAR_MS = 6_000

interface UseDeviceCommandResult {
  activeCommand: DeviceCommandType | null
  commandStatus: CommandFeedbackStatus
  failureReason: string | null
  sendCommand: (deviceId: string, command: DeviceCommandType) => Promise<void>
  clearFeedback: () => void
}

export function useDeviceCommand(): UseDeviceCommandResult {
  const [activeCommand, setActiveCommand] = useState<DeviceCommandType | null>(null)
  const [commandStatus, setCommandStatus] = useState<CommandFeedbackStatus>('idle')
  const [failureReason, setFailureReason] = useState<string | null>(null)
  const pollTimerRef = useRef<number | null>(null)
  const timeoutRef = useRef<number | null>(null)

  const clearTimers = useCallback(() => {
    if (pollTimerRef.current !== null) {
      window.clearInterval(pollTimerRef.current)
      pollTimerRef.current = null
    }
    if (timeoutRef.current !== null) {
      window.clearTimeout(timeoutRef.current)
      timeoutRef.current = null
    }
  }, [])

  const clearFeedback = useCallback(() => {
    clearTimers()
    setActiveCommand(null)
    setCommandStatus('idle')
    setFailureReason(null)
  }, [clearTimers])

  const sendCommand = useCallback(
    async (deviceId: string, command: DeviceCommandType) => {
      clearTimers()
      setActiveCommand(command)
      setCommandStatus('queued')
      setFailureReason(null)

      try {
        const created = await createDeviceCommand(deviceId, command)
        setCommandStatus('running')

        const startedAt = Date.now()

        const poll = async () => {
          try {
            const updated = await fetchDeviceCommand(created.id)

            if (updated.status === 'DONE') {
              clearTimers()
              setCommandStatus('done')
              return
            }

            if (Date.now() - startedAt >= COMMAND_TIMEOUT_MS) {
              clearTimers()
              setCommandStatus('failed')
              setFailureReason('Command timed out')
            }
          } catch (err) {
            clearTimers()
            setCommandStatus('failed')
            setFailureReason(err instanceof Error ? err.message : 'Failed to check command status')
          }
        }

        await poll()
        pollTimerRef.current = window.setInterval(() => {
          void poll()
        }, POLL_INTERVAL_MS)

        timeoutRef.current = window.setTimeout(() => {
          clearTimers()
          setCommandStatus('failed')
          setFailureReason('Command timed out')
        }, COMMAND_TIMEOUT_MS)
      } catch (err) {
        clearTimers()
        setCommandStatus('failed')
        setFailureReason(err instanceof Error ? err.message : 'Failed to queue command')
      }
    },
    [clearTimers],
  )

  useEffect(() => {
    if (commandStatus !== 'done' && commandStatus !== 'failed') {
      return
    }

    const timeoutId = window.setTimeout(clearFeedback, FEEDBACK_CLEAR_MS)
    return () => window.clearTimeout(timeoutId)
  }, [commandStatus, clearFeedback])

  useEffect(() => clearTimers, [clearTimers])

  return { activeCommand, commandStatus, failureReason, sendCommand, clearFeedback }
}
