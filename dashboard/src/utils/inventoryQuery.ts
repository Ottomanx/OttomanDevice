import type { DeviceEnhanced } from '../types/device'
import type {
  InventoryDevice,
  InventoryFilters,
  InventoryPageResult,
  InventoryQueryOptions,
  InventorySort,
  TagSyncPlan,
} from '../types/inventory'
import { getOnlineStatus } from './deviceStatus'

export function getDeviceDisplayName(device: DeviceEnhanced): string {
  return device.computer_name || device.hostname || device.device_id
}

export function normalizeInventoryDevice(
  device: DeviceEnhanced,
  groupId: string | null,
  groupName: string | null,
  tags: string[],
): InventoryDevice {
  return {
    ...device,
    group_id: groupId,
    group_name: groupName,
    tags: [...tags].sort((a, b) => a.localeCompare(b)),
    online_status: getOnlineStatus(device),
  }
}

export function matchesInventorySearch(device: InventoryDevice, query: string): boolean {
  const normalized = query.trim().toLowerCase()
  if (!normalized) {
    return true
  }

  const fields = [
    getDeviceDisplayName(device),
    device.device_id,
    device.operating_system,
    device.firmware_version,
    device.local_ip,
    device.group_name,
    ...device.tags,
  ]

  return fields.some((field) => field?.toLowerCase().includes(normalized))
}

export function matchesInventoryFilters(device: InventoryDevice, filters: InventoryFilters): boolean {
  if (filters.status !== 'all' && device.online_status !== filters.status) {
    return false
  }

  if (filters.groupId !== 'all' && device.group_id !== filters.groupId) {
    return false
  }

  if (filters.tag !== 'all' && !device.tags.includes(filters.tag)) {
    return false
  }

  return true
}

function compareNullableText(left: string | null | undefined, right: string | null | undefined): number {
  const a = left ?? ''
  const b = right ?? ''
  return a.localeCompare(b)
}

function compareNullableNumber(left: number | null | undefined, right: number | null | undefined): number {
  const a = left ?? -1
  const b = right ?? -1
  return a - b
}

export function compareInventoryDevices(
  left: InventoryDevice,
  right: InventoryDevice,
  sort: InventorySort,
): number {
  let result = 0

  switch (sort.field) {
    case 'name':
      result = compareNullableText(getDeviceDisplayName(left), getDeviceDisplayName(right))
      break
    case 'status':
      result = compareNullableText(left.online_status, right.online_status)
      break
    case 'last_seen':
      result = compareNullableText(left.last_online_at, right.last_online_at)
      break
    case 'firmware':
      result = compareNullableText(left.firmware_version, right.firmware_version)
      break
    case 'os':
      result = compareNullableText(left.operating_system, right.operating_system)
      break
    case 'cpu':
      result = compareNullableNumber(left.cpu_usage, right.cpu_usage)
      break
    case 'ram':
      result = compareNullableNumber(left.ram_usage, right.ram_usage)
      break
    case 'ip':
      result = compareNullableText(left.local_ip, right.local_ip)
      break
    case 'group':
      result = compareNullableText(left.group_name, right.group_name)
      break
    default:
      result = 0
  }

  return sort.direction === 'asc' ? result : -result
}

export function sortInventoryDevices(devices: InventoryDevice[], sort: InventorySort): InventoryDevice[] {
  return [...devices].sort((left, right) => compareInventoryDevices(left, right, sort))
}

export function paginateInventoryDevices(
  devices: InventoryDevice[],
  page: number,
  pageSize: number,
): InventoryPageResult {
  const safePageSize = Math.max(1, pageSize)
  const totalItems = devices.length
  const totalPages = Math.max(1, Math.ceil(totalItems / safePageSize))
  const safePage = Math.min(Math.max(1, page), totalPages)
  const start = (safePage - 1) * safePageSize

  return {
    items: devices.slice(start, start + safePageSize),
    totalItems,
    totalPages,
    page: safePage,
    pageSize: safePageSize,
  }
}

export function queryInventoryDevices(
  devices: InventoryDevice[],
  options: InventoryQueryOptions,
): InventoryPageResult {
  const filtered = devices.filter(
    (device) => matchesInventorySearch(device, options.search) && matchesInventoryFilters(device, options.filters),
  )
  const sorted = sortInventoryDevices(filtered, options.sort)
  return paginateInventoryDevices(sorted, options.page, options.pageSize)
}

export function computeTagSyncPlan(currentTags: string[], nextTags: string[]): TagSyncPlan {
  const current = new Set(currentTags.map((tag) => tag.trim()).filter(Boolean))
  const next = new Set(nextTags.map((tag) => tag.trim()).filter(Boolean))

  const toAdd = [...next].filter((tag) => !current.has(tag)).sort((a, b) => a.localeCompare(b))
  const toRemove = [...current].filter((tag) => !next.has(tag)).sort((a, b) => a.localeCompare(b))

  return { toAdd, toRemove }
}
