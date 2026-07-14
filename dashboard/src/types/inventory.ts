import type { DeviceEnhanced, OnlineStatus } from './device'

export interface DeviceGroup {
  id: string
  name: string
  created_at: string
}

export interface InventoryDevice extends DeviceEnhanced {
  group_id: string | null
  group_name: string | null
  tags: string[]
  online_status: OnlineStatus
}

export type InventorySortField =
  | 'name'
  | 'status'
  | 'last_seen'
  | 'firmware'
  | 'os'
  | 'cpu'
  | 'ram'
  | 'ip'
  | 'group'

export type InventorySortDirection = 'asc' | 'desc'

export interface InventorySort {
  field: InventorySortField
  direction: InventorySortDirection
}

export interface InventoryFilters {
  status: OnlineStatus | 'all'
  groupId: string | 'all'
  tag: string | 'all'
}

export interface InventoryQueryOptions {
  search: string
  filters: InventoryFilters
  sort: InventorySort
  page: number
  pageSize: number
}

export interface InventoryPageResult {
  items: InventoryDevice[]
  totalItems: number
  totalPages: number
  page: number
  pageSize: number
}

export interface TagSyncPlan {
  toAdd: string[]
  toRemove: string[]
}
