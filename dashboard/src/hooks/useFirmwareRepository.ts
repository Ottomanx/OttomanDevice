import { useCallback, useEffect, useRef, useState } from 'react'

import {
  fetchFirmwareReleases,
  setFirmwareReleasePublished,
  uploadFirmwarePackage,
} from '../services/firmware'
import type { FirmwareRelease, FirmwareUploadInput } from '../types/firmware'

const REFRESH_INTERVAL_MS = 5_000

interface UseFirmwareRepositoryResult {
  releases: FirmwareRelease[]
  error: string | null
  isLoading: boolean
  isUploading: boolean
  lastUpdated: Date | null
  refresh: () => Promise<void>
  uploadFirmware: (input: FirmwareUploadInput) => Promise<void>
  publishRelease: (releaseId: string) => Promise<void>
  unpublishRelease: (releaseId: string) => Promise<void>
}

export function useFirmwareRepository(): UseFirmwareRepositoryResult {
  const [releases, setReleases] = useState<FirmwareRelease[]>([])
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [isUploading, setIsUploading] = useState(false)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const isMountedRef = useRef(true)

  const refresh = useCallback(async () => {
    try {
      const nextReleases = await fetchFirmwareReleases()
      if (!isMountedRef.current) {
        return
      }

      setReleases(nextReleases)
      setError(null)
      setLastUpdated(new Date())
    } catch (err) {
      if (!isMountedRef.current) {
        return
      }

      const message = err instanceof Error ? err.message : 'Failed to load firmware releases'
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

  const uploadFirmware = useCallback(
    async (input: FirmwareUploadInput) => {
      setIsUploading(true)
      try {
        await uploadFirmwarePackage(input)
        await refresh()
      } finally {
        if (isMountedRef.current) {
          setIsUploading(false)
        }
      }
    },
    [refresh],
  )

  const publishRelease = useCallback(
    async (releaseId: string) => {
      await setFirmwareReleasePublished(releaseId, true)
      await refresh()
    },
    [refresh],
  )

  const unpublishRelease = useCallback(
    async (releaseId: string) => {
      await setFirmwareReleasePublished(releaseId, false)
      await refresh()
    },
    [refresh],
  )

  return {
    releases,
    error,
    isLoading,
    isUploading,
    lastUpdated,
    refresh,
    uploadFirmware,
    publishRelease,
    unpublishRelease,
  }
}
