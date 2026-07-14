import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import {
  assignDeviceGroup,
  assignDeviceTags,
  createDeviceGroup,
  fetchDeviceGroups,
  fetchInventoryDevices,
  fetchInventoryTags,
} from '../services/inventory'
import type { DeviceGroup, InventoryFilters, InventoryPageResult, InventorySort } from '../types/inventory'
import { queryInventoryDevices } from '../utils/inventoryQuery'

const REFRESH_INTERVAL_MS = 5_000
const DEFAULT_PAGE_SIZE = 10

const DEFAULT_FILTERS: InventoryFilters = {
  status: 'all',
  groupId: 'all',
  tag: 'all',
}

const DEFAULT_SORT: InventorySort = {
  field: 'last_seen',
  direction: 'desc',
}

interface UseInventoryResult {
  pageResult: InventoryPageResult
  groups: DeviceGroup[]
  tags: string[]
  search: string
  filters: InventoryFilters
  sort: InventorySort
  pageSize: number
  error: string | null
  isLoading: boolean
  lastUpdated: Date | null
  setSearch: (value: string) => void
  setFilters: (value: InventoryFilters) => void
  setSort: (value: InventorySort) => void
  setPage: (page: number) => void
  setPageSize: (pageSize: number) => void
  refresh: () => Promise<void>
  assignGroup: (deviceId: string, groupId: string | null) => Promise<void>
  assignTags: (deviceId: string, currentTags: string[], nextTags: string[]) => Promise<void>
  createGroup: (name: string) => Promise<void>
}

export function useInventory(): UseInventoryResult {
  const [devices, setDevices] = useState<Awaited<ReturnType<typeof fetchInventoryDevices>>>([])
  const [groups, setGroups] = useState<DeviceGroup[]>([])
  const [tags, setTags] = useState<string[]>([])
  const [search, setSearchState] = useState('')
  const [filters, setFiltersState] = useState<InventoryFilters>(DEFAULT_FILTERS)
  const [sort, setSortState] = useState<InventorySort>(DEFAULT_SORT)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSizeState] = useState(DEFAULT_PAGE_SIZE)
  const [error, setError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const isMountedRef = useRef(true)

  const refresh = useCallback(async () => {
    try {
      const [nextDevices, nextGroups, nextTags] = await Promise.all([
        fetchInventoryDevices(),
        fetchDeviceGroups(),
        fetchInventoryTags(),
      ])

      if (!isMountedRef.current) {
        return
      }

      setDevices(nextDevices)
      setGroups(nextGroups)
      setTags(nextTags)
      setError(null)
      setLastUpdated(new Date())
    } catch (err) {
      if (!isMountedRef.current) {
        return
      }

      const message = err instanceof Error ? err.message : 'Failed to load inventory'
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

  const setSearch = useCallback((value: string) => {
    setSearchState(value)
    setPage(1)
  }, [])

  const setFilters = useCallback((value: InventoryFilters) => {
    setFiltersState(value)
    setPage(1)
  }, [])

  const setSort = useCallback((value: InventorySort) => {
    setSortState(value)
    setPage(1)
  }, [])

  const setPageSize = useCallback((value: number) => {
    setPageSizeState(value)
    setPage(1)
  }, [])

  const pageResult = useMemo(
    () =>
      queryInventoryDevices(devices, {
        search,
        filters,
        sort,
        page,
        pageSize,
      }),
    [devices, search, filters, sort, page, pageSize],
  )

  const assignGroup = useCallback(
    async (deviceId: string, groupId: string | null) => {
      await assignDeviceGroup(deviceId, groupId)
      await refresh()
    },
    [refresh],
  )

  const assignTags = useCallback(
    async (deviceId: string, currentTags: string[], nextTags: string[]) => {
      await assignDeviceTags(deviceId, currentTags, nextTags)
      await refresh()
    },
    [refresh],
  )

  const createGroup = useCallback(
    async (name: string) => {
      await createDeviceGroup(name)
      await refresh()
    },
    [refresh],
  )

  return {
    pageResult,
    groups,
    tags,
    search,
    filters,
    sort,
    pageSize,
    error,
    isLoading,
    lastUpdated,
    setSearch,
    setFilters,
    setSort,
    setPage,
    setPageSize,
    refresh,
    assignGroup,
    assignTags,
    createGroup,
  }
}
