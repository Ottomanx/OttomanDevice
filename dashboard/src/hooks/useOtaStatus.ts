import { useCallback, useEffect, useRef, useState } from 'react'

import { fetchDeviceOtaStatuses } from '../services/otaStatus'
import type { DeviceOtaStatus } from '../types/ota'

const REFRESH_INTERVAL_MS = 5_000

interface UseOtaStatusResult {
  statuses: DeviceOtaStatus[]
  error: string | null
  isLoading: boolean
  lastUpdated: Date | null
  refresh: () => Promise<void>
}

export function useOtaStatus(): UseOtaStatusResult {
  const [statuses, setStatuses] = useState<DeviceOtaStatus[]>([])
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const isMountedRef = useRef(true)

  const refresh = useCallback(async () => {
    try {
      const nextStatuses = await fetchDeviceOtaStatuses()
      if (!isMountedRef.current) {
        return
      }

      setStatuses(nextStatuses)
      setError(null)
      setLastUpdated(new Date())
    } catch (err) {
      if (!isMountedRef.current) {
        return
      }

      const message = err instanceof Error ? err.message : 'Failed to load OTA status'
      setError(message)
    } finally {
      if (isMountedRef.current) {
        setIsLoading(false)
      }
    }
  }, [])

  useEffect(() => {
    isMountedRef.current = true
    void refresh()

    const intervalId = window.setInterval(() => {
      void refresh()
    }, REFRESH_INTERVAL_MS)

    return () => {
      isMountedRef.current = false
      window.clearInterval(intervalId)
    }
  }, [refresh])

  return { statuses, error, isLoading, lastUpdated, refresh }
}
