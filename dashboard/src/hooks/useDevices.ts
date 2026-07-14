import { useCallback, useEffect, useRef, useState } from 'react'

import { fetchDevices } from '../services/devices'
import type { DeviceEnhanced } from '../types/device'
import { logOnlineStatusDebug } from '../utils/deviceStatus'

const REFRESH_INTERVAL_MS = 5_000

interface UseDevicesResult {
  devices: DeviceEnhanced[]
  error: string | null
  isLoading: boolean
  lastUpdated: Date | null
  refresh: () => Promise<void>
}

export function useDevices(): UseDevicesResult {
  const [devices, setDevices] = useState<DeviceEnhanced[]>([])
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const isMountedRef = useRef(true)

  const refresh = useCallback(async () => {
    try {
      const nextDevices = await fetchDevices()
      if (!isMountedRef.current) {
        return
      }

      setDevices(nextDevices)
      logOnlineStatusDebug(nextDevices)
      setError(null)
      setLastUpdated(new Date())
    } catch (err) {
      if (!isMountedRef.current) {
        return
      }

      const message = err instanceof Error ? err.message : 'Failed to load devices'
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

  return { devices, error, isLoading, lastUpdated, refresh }
}
