import type { DeviceEnhanced, OnlineStatus } from '../types/device'

export const HEARTBEAT_INTERVAL_MS = 30_000
export const ONLINE_THRESHOLD_MS = HEARTBEAT_INTERVAL_MS * 3
export const ONLINE_THRESHOLD_SECONDS = ONLINE_THRESHOLD_MS / 1000

const TIMEZONE_SUFFIX_PATTERN = /(?:[zZ]|[+-]\d{2}(?::?\d{2}(?::?\d{2})?)?)$/

export function normalizeUtcTimestampInput(isoDate: string): string {
  let normalized = isoDate.trim()

  // Postgres/Supabase may return a space between date and time.
  normalized = normalized.replace(/^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})/, '$1T$2')

  // Normalize short UTC offsets such as +00 or -00.
  if (/[+-]\d{2}$/.test(normalized)) {
    normalized = `${normalized}:00`
  }

  return normalized
}

export function parseUtcTimestamp(isoDate: string | null | undefined): number | null {
  if (!isoDate) {
    return null
  }

  const normalized = normalizeUtcTimestampInput(isoDate)
  if (!normalized) {
    return null
  }

  const hasExplicitTimezone = TIMEZONE_SUFFIX_PATTERN.test(normalized)
  const candidate = hasExplicitTimezone ? normalized : `${normalized}Z`
  const parsed = Date.parse(candidate)

  return Number.isNaN(parsed) ? null : parsed
}

export function getDeviceIdentityKey(device: DeviceEnhanced): string {
  return (device.computer_name || device.hostname || device.device_id).trim().toLowerCase()
}

function getRegistrationTimestamp(device: DeviceEnhanced): number {
  return parseUtcTimestamp(device.created_at) ?? 0
}

function getLastSeenTimestamp(device: DeviceEnhanced): number {
  return parseUtcTimestamp(device.last_online_at) ?? 0
}

export function dedupeDevices<T extends DeviceEnhanced>(devices: T[]): T[] {
  const groups = new Map<string, T[]>()

  for (const device of devices) {
    const key = getDeviceIdentityKey(device)
    const group = groups.get(key) ?? []
    group.push(device)
    groups.set(key, group)
  }

  const deduped: T[] = []

  for (const group of groups.values()) {
    const latestRegistration = Math.max(...group.map(getRegistrationTimestamp))
    const latestRegistrations = group.filter(
      (device) => getRegistrationTimestamp(device) >= latestRegistration,
    )

    const activeDevice = latestRegistrations.reduce((best, device) => {
      const bestSeen = getLastSeenTimestamp(best)
      const candidateSeen = getLastSeenTimestamp(device)
      return candidateSeen >= bestSeen ? device : best
    })

    deduped.push(activeDevice)
  }

  return deduped.sort((left, right) => getLastSeenTimestamp(right) - getLastSeenTimestamp(left))
}

export interface OnlineStatusDebugInfo {
  device: string
  last_online_at: string | null
  parsed_timestamp: string | null
  current_time: string
  difference_seconds: number | null
  online_result: OnlineStatus
  db_status: string | null
  threshold_seconds: number
}

export function analyzeOnlineStatus(device: DeviceEnhanced): OnlineStatusDebugInfo {
  const parsed = parseUtcTimestamp(device.last_online_at)
  const now = Date.now()

  return {
    device: device.computer_name || device.hostname || device.device_id,
    last_online_at: device.last_online_at,
    parsed_timestamp: parsed === null ? null : new Date(parsed).toISOString(),
    current_time: new Date(now).toISOString(),
    difference_seconds:
      parsed === null ? null : Math.round(((now - parsed) / 1000) * 100) / 100,
    online_result: getOnlineStatus(device),
    db_status: device.status,
    threshold_seconds: ONLINE_THRESHOLD_SECONDS,
  }
}

export function logOnlineStatusDebug(devices: DeviceEnhanced[]): void {
  for (const device of devices) {
    console.log('[OnlineStatusDebug]', analyzeOnlineStatus(device))
  }
}

export function getOnlineStatus(device: DeviceEnhanced): OnlineStatus {
  if (!device.last_online_at) {
    return device.status?.toUpperCase() === 'ONLINE' ? 'online' : 'unknown'
  }

  const lastSeen = parseUtcTimestamp(device.last_online_at)
  if (lastSeen === null) {
    return device.status?.toUpperCase() === 'ONLINE' ? 'online' : 'unknown'
  }

  const ageMs = Date.now() - lastSeen
  if (ageMs <= ONLINE_THRESHOLD_MS) {
    return 'online'
  }

  return 'offline'
}

export function getStatusLabel(status: OnlineStatus): string {
  switch (status) {
    case 'online':
      return 'Online'
    case 'offline':
      return 'Offline'
    default:
      return 'Unknown'
  }
}
