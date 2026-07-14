import { afterEach, describe, expect, it, vi } from 'vitest'

import type { DeviceEnhanced } from '../types/device'
import {
  HEARTBEAT_INTERVAL_MS,
  ONLINE_THRESHOLD_MS,
  analyzeOnlineStatus,
  dedupeDevices,
  getOnlineStatus,
  normalizeUtcTimestampInput,
  parseUtcTimestamp,
} from './deviceStatus'

function makeDevice(overrides: Partial<DeviceEnhanced> = {}): DeviceEnhanced {
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
    ...overrides,
  }
}

describe('normalizeUtcTimestampInput', () => {
  it('normalizes space-separated timestamps', () => {
    expect(normalizeUtcTimestampInput('2026-07-14 00:14:00+00')).toBe('2026-07-14T00:14:00+00:00')
  })

  it('normalizes short +00 offsets', () => {
    expect(normalizeUtcTimestampInput('2026-07-14T00:14:00+00')).toBe('2026-07-14T00:14:00+00:00')
  })
})

describe('parseUtcTimestamp', () => {
  it('parses Z-suffixed timestamps', () => {
    expect(parseUtcTimestamp('2026-07-13T12:00:00.000Z')).toBe(Date.parse('2026-07-13T12:00:00.000Z'))
  })

  it('parses offset timestamps from the agent', () => {
    expect(parseUtcTimestamp('2026-07-13T12:00:00.123456+00:00')).toBe(
      Date.parse('2026-07-13T12:00:00.123456+00:00'),
    )
  })

  it('parses Supabase short UTC offsets', () => {
    expect(parseUtcTimestamp('2026-07-13T21:14:52.592+00')).toBe(
      Date.parse('2026-07-13T21:14:52.592+00:00'),
    )
  })

  it('parses space-separated timestamps with short UTC offsets', () => {
    expect(parseUtcTimestamp('2026-07-14 00:14:00+00')).toBe(Date.parse('2026-07-14T00:14:00+00:00'))
  })

  it('treats timezone-less timestamps as UTC', () => {
    const parsed = parseUtcTimestamp('2026-07-13T12:00:00')
    expect(parsed).toBe(Date.parse('2026-07-13T12:00:00Z'))
  })
})

describe('getOnlineStatus', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('marks a recent heartbeat as online when status is ONLINE', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-13T12:00:30.000Z'))

    const status = getOnlineStatus(
      makeDevice({
        status: 'ONLINE',
        last_online_at: '2026-07-13T12:00:15.000+00',
      }),
    )

    expect(status).toBe('online')
  })

  it('marks a recent heartbeat as online even when status is stale', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-13T12:00:30.000Z'))

    const status = getOnlineStatus(
      makeDevice({
        status: 'OFFLINE',
        last_online_at: '2026-07-13T12:00:15.000Z',
      }),
    )

    expect(status).toBe('online')
  })

  it('marks devices offline after the heartbeat threshold', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-13T12:02:00.000Z'))

    const status = getOnlineStatus(
      makeDevice({
        status: 'ONLINE',
        last_online_at: '2026-07-13T12:00:00.000Z',
      }),
    )

    expect(status).toBe('offline')
  })

  it('uses the configured heartbeat threshold', () => {
    expect(ONLINE_THRESHOLD_MS).toBe(HEARTBEAT_INTERVAL_MS * 3)
  })
})

describe('analyzeOnlineStatus', () => {
  it('reports parsed UTC values and age in seconds', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-13T12:00:30.000Z'))

    const debug = analyzeOnlineStatus(
      makeDevice({
        last_online_at: '2026-07-13T12:00:15.000+00',
      }),
    )

    expect(debug.parsed_timestamp).toBe('2026-07-13T12:00:15.000Z')
    expect(debug.difference_seconds).toBe(15)
    expect(debug.online_result).toBe('online')
  })
})

describe('dedupeDevices', () => {
  it('keeps the newest active row for the same computer name', () => {
    const devices = dedupeDevices([
      makeDevice({
        id: 'uuid-old',
        device_id: 'device-old',
        last_online_at: '2026-07-13T11:00:00.000Z',
        created_at: '2026-07-13T08:00:00.000Z',
        status: 'OFFLINE',
      }),
      makeDevice({
        id: 'uuid-new',
        device_id: 'device-new',
        last_online_at: '2026-07-13T12:00:00.000Z',
        created_at: '2026-07-13T10:00:00.000Z',
        status: 'ONLINE',
      }),
    ])

    expect(devices).toHaveLength(1)
    expect(devices[0].device_id).toBe('device-new')
  })

  it('ignores rows older than the latest registration', () => {
    const devices = dedupeDevices([
      makeDevice({
        id: 'uuid-old',
        device_id: 'device-old',
        last_online_at: '2026-07-13T12:30:00.000Z',
        created_at: '2026-07-13T08:00:00.000Z',
        status: 'ONLINE',
      }),
      makeDevice({
        id: 'uuid-new',
        device_id: 'device-new',
        last_online_at: '2026-07-13T12:00:00.000Z',
        created_at: '2026-07-13T11:00:00.000Z',
        status: 'ONLINE',
      }),
    ])

    expect(devices).toHaveLength(1)
    expect(devices[0].device_id).toBe('device-new')
  })
})
