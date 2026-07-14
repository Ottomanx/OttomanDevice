import { useEffect, useState } from 'react'

import { getDesktopPreviewUrl } from '../services/desktopPreview'

const REFRESH_INTERVAL_MS = 1_000

interface UseDesktopPreviewResult {
  frameUrl: string | null
  frameKey: number
  isLoading: boolean
  hasError: boolean
  lastRefreshed: Date | null
  onFrameLoad: () => void
  onFrameError: () => void
}

export function useDesktopPreview(deviceId: string | null): UseDesktopPreviewResult {
  const [frameKey, setFrameKey] = useState(() => Date.now())
  const [isLoading, setIsLoading] = useState(true)
  const [hasError, setHasError] = useState(false)
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null)

  useEffect(() => {
    if (!deviceId) {
      return
    }

    setFrameKey(Date.now())
    setIsLoading(true)
    setHasError(false)

    const intervalId = window.setInterval(() => {
      setFrameKey(Date.now())
      setIsLoading(true)
    }, REFRESH_INTERVAL_MS)

    return () => window.clearInterval(intervalId)
  }, [deviceId])

  useEffect(() => {
    if (frameKey) {
      setIsLoading(true)
    }
  }, [frameKey])

  const frameUrl = deviceId ? getDesktopPreviewUrl(deviceId, frameKey) : null

  const onFrameLoad = () => {
    setIsLoading(false)
    setHasError(false)
    setLastRefreshed(new Date())
  }

  const onFrameError = () => {
    setIsLoading(false)
    setHasError(true)
  }

  return {
    frameUrl,
    frameKey,
    isLoading,
    hasError,
    lastRefreshed,
    onFrameLoad,
    onFrameError,
  }
}
