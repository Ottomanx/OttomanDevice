import { useCallback, useEffect, useRef, useState } from 'react'

import { listDeviceScreenshots } from '../services/screenshots'
import type { ScreenshotItem } from '../types/device'

const REFRESH_INTERVAL_MS = 10_000

interface UseScreenshotHistoryResult {
  screenshots: ScreenshotItem[]
  isLoading: boolean
  error: string | null
  lastUpdated: Date | null
}

export function useScreenshotHistory(deviceId: string | null): UseScreenshotHistoryResult {
  const [screenshots, setScreenshots] = useState<ScreenshotItem[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const isMountedRef = useRef(true)

  const refresh = useCallback(async () => {
    if (!deviceId) {
      return
    }

    setIsLoading(true)

    try {
      const items = await listDeviceScreenshots(deviceId)
      if (!isMountedRef.current) {
        return
      }

      setScreenshots(items)
      setError(null)
      setLastUpdated(new Date())
    } catch (err) {
      if (!isMountedRef.current) {
        return
      }

      setError(err instanceof Error ? err.message : 'Failed to load screenshots')
    } finally {
      if (isMountedRef.current) {
        setIsLoading(false)
      }
    }
  }, [deviceId])

  useEffect(() => {
    isMountedRef.current = true

    if (!deviceId) {
      setScreenshots([])
      setError(null)
      setLastUpdated(null)
      return () => {
        isMountedRef.current = false
      }
    }

    void refresh()

    const intervalId = window.setInterval(() => {
      void refresh()
    }, REFRESH_INTERVAL_MS)

    return () => {
      isMountedRef.current = false
      window.clearInterval(intervalId)
    }
  }, [deviceId, refresh])

  return { screenshots, isLoading, error, lastUpdated }
}
