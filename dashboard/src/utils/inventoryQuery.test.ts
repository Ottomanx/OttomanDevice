import { describe, expect, it } from 'vitest'

import type { InventoryDevice, InventoryQueryOptions } from '../types/inventory'
import {
  computeTagSyncPlan,
  matchesInventoryFilters,
  matchesInventorySearch,
  paginateInventoryDevices,
  queryInventoryDevices,
} from './inventoryQuery'

function makeDevice(overrides: Partial<InventoryDevice> = {}): InventoryDevice {
  return {
    id: 'uuid-1',
    device_id: 'device-alpha',
    computer_name: 'Alpha Workstation',
    operating_system: 'Windows-10',
    python_version: '3.13.0',
    firmware_version: '0.2.0',
    status: 'ONLINE',
    last_online_at: '2026-07-13T12:00:00.000Z',
    created_at: '2026-07-13T10:00:00.000Z',
    cpu_usage: 12.5,
    ram_usage: 45.0,
    disk_usage: 60.0,
    hostname: 'alpha-host',
    local_ip: '192.168.1.10',
    system_uptime: 3600,
    camera_available: true,
    group_id: 'group-1',
    group_name: 'Engineering',
    tags: ['lab', 'priority'],
    online_status: 'online',
    ...overrides,
  }
}

const sampleDevices: InventoryDevice[] = [
  makeDevice(),
  makeDevice({
    id: 'uuid-2',
    device_id: 'device-beta',
    computer_name: 'Beta Laptop',
    operating_system: 'Linux',
    firmware_version: '0.1.9',
    local_ip: '10.0.0.5',
    cpu_usage: 80,
    ram_usage: 70,
    group_id: 'group-2',
    group_name: 'Sales',
    tags: ['field'],
    online_status: 'offline',
    last_online_at: '2026-07-12T08:00:00.000Z',
  }),
  makeDevice({
    id: 'uuid-3',
    device_id: 'device-gamma',
    computer_name: 'Gamma Server',
    operating_system: 'Windows-11',
    firmware_version: '0.2.1',
    local_ip: '172.16.0.20',
    group_id: null,
    group_name: null,
    tags: [],
    online_status: 'unknown',
    last_online_at: null,
  }),
]

describe('inventory search', () => {
  it('matches device name and device id', () => {
    expect(matchesInventorySearch(sampleDevices[0], 'alpha')).toBe(true)
    expect(matchesInventorySearch(sampleDevices[0], 'device-alpha')).toBe(true)
    expect(matchesInventorySearch(sampleDevices[0], 'beta')).toBe(false)
  })

  it('matches ip, os, firmware, group, and tags', () => {
    expect(matchesInventorySearch(sampleDevices[0], '192.168')).toBe(true)
    expect(matchesInventorySearch(sampleDevices[0], 'windows-10')).toBe(true)
    expect(matchesInventorySearch(sampleDevices[0], 'engineering')).toBe(true)
    expect(matchesInventorySearch(sampleDevices[0], 'priority')).toBe(true)
    expect(matchesInventorySearch(sampleDevices[1], 'linux')).toBe(true)
  })

  it('returns all devices for empty search', () => {
    expect(sampleDevices.every((device) => matchesInventorySearch(device, ''))).toBe(true)
  })
})

describe('inventory filter', () => {
  it('filters by online status', () => {
    expect(matchesInventoryFilters(sampleDevices[0], { status: 'online', groupId: 'all', tag: 'all' })).toBe(
      true,
    )
    expect(matchesInventoryFilters(sampleDevices[1], { status: 'online', groupId: 'all', tag: 'all' })).toBe(
      false,
    )
  })

  it('filters by group id', () => {
    expect(matchesInventoryFilters(sampleDevices[0], { status: 'all', groupId: 'group-1', tag: 'all' })).toBe(
      true,
    )
    expect(matchesInventoryFilters(sampleDevices[2], { status: 'all', groupId: 'group-1', tag: 'all' })).toBe(
      false,
    )
  })

  it('filters by tag', () => {
    expect(matchesInventoryFilters(sampleDevices[0], { status: 'all', groupId: 'all', tag: 'lab' })).toBe(true)
    expect(matchesInventoryFilters(sampleDevices[2], { status: 'all', groupId: 'all', tag: 'lab' })).toBe(false)
  })
})

describe('inventory pagination', () => {
  it('returns the requested page slice', () => {
    const page = paginateInventoryDevices(sampleDevices, 2, 2)

    expect(page.totalItems).toBe(3)
    expect(page.totalPages).toBe(2)
    expect(page.page).toBe(2)
    expect(page.items).toHaveLength(1)
    expect(page.items[0].device_id).toBe('device-gamma')
  })

  it('clamps invalid page numbers', () => {
    const page = paginateInventoryDevices(sampleDevices, 99, 2)
    expect(page.page).toBe(2)
  })
})

describe('inventory query', () => {
  const baseOptions: InventoryQueryOptions = {
    search: '',
    filters: { status: 'all', groupId: 'all', tag: 'all' },
    sort: { field: 'name', direction: 'asc' },
    page: 1,
    pageSize: 2,
  }

  it('combines search, filter, sort, and pagination', () => {
    const result = queryInventoryDevices(sampleDevices, {
      ...baseOptions,
      search: 'windows',
      filters: { status: 'all', groupId: 'all', tag: 'all' },
      page: 1,
      pageSize: 1,
    })

    expect(result.totalItems).toBe(2)
    expect(result.items).toHaveLength(1)
    expect(result.items[0].device_id).toBe('device-alpha')
  })

  it('sorts by cpu descending when requested', () => {
    const result = queryInventoryDevices(sampleDevices, {
      ...baseOptions,
      sort: { field: 'cpu', direction: 'desc' },
      pageSize: 3,
    })

    expect(result.items.map((device) => device.device_id)).toEqual([
      'device-beta',
      'device-alpha',
      'device-gamma',
    ])
  })
})

describe('tag assignment plan', () => {
  it('computes tags to add and remove', () => {
    const plan = computeTagSyncPlan(['lab', 'staging'], ['lab', 'priority', 'prod'])

    expect(plan.toAdd).toEqual(['priority', 'prod'])
    expect(plan.toRemove).toEqual(['staging'])
  })

  it('ignores blank tags and trims whitespace', () => {
    const plan = computeTagSyncPlan([' lab '], [' lab ', '  ', 'ops'])

    expect(plan.toAdd).toEqual(['ops'])
    expect(plan.toRemove).toEqual([])
  })
})
