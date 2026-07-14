import { useCallback, useEffect, useState } from 'react'

import { useAuth } from '../contexts/AuthContext'
import { fetchUserPermissions } from '../services/permissions'
import { hasPermission, type PermissionKey } from '../types/permissions'

interface UsePermissionsResult {
  permissions: PermissionKey[]
  isLoading: boolean
  error: string | null
  can: (permission: PermissionKey) => boolean
  refresh: () => Promise<void>
}

export function usePermissions(): UsePermissionsResult {
  const { user, isLoading: authLoading } = useAuth()
  const [permissions, setPermissions] = useState<PermissionKey[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    if (!user) {
      setPermissions([])
      setError(null)
      setIsLoading(false)
      return
    }

    setIsLoading(true)
    setError(null)

    try {
      const nextPermissions = await fetchUserPermissions(user.id)
      setPermissions(nextPermissions)
    } catch (err) {
      setPermissions([])
      setError(err instanceof Error ? err.message : 'Failed to load permissions')
    } finally {
      setIsLoading(false)
    }
  }, [user])

  useEffect(() => {
    if (authLoading) {
      setIsLoading(true)
      return
    }

    void refresh()
  }, [authLoading, refresh])

  const can = useCallback(
    (permission: PermissionKey) => hasPermission(permissions, permission),
    [permissions],
  )

  return {
    permissions,
    isLoading: authLoading || isLoading,
    error,
    can,
    refresh,
  }
}