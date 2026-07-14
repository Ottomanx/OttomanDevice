import { parseUtcTimestamp } from './deviceStatus'

export function formatPercent(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) {
    return '—'
  }

  return `${value.toFixed(1)}%`
}

export function formatRelativeTime(isoDate: string | null | undefined): string {
  if (!isoDate) {
    return 'Never'
  }

  const timestamp = parseUtcTimestamp(isoDate)
  if (timestamp === null) {
    return 'Unknown'
  }

  const diffMs = Date.now() - timestamp
  const diffSeconds = Math.floor(diffMs / 1000)

  if (diffSeconds < 5) {
    return 'Just now'
  }

  if (diffSeconds < 60) {
    return `${diffSeconds}s ago`
  }

  const diffMinutes = Math.floor(diffSeconds / 60)
  if (diffMinutes < 60) {
    return `${diffMinutes}m ago`
  }

  const diffHours = Math.floor(diffMinutes / 60)
  if (diffHours < 24) {
    return `${diffHours}h ago`
  }

  return new Date(timestamp).toLocaleString()
}

export function formatCameraStatus(available: boolean | null | undefined): string {
  if (available == null) {
    return 'Unknown'
  }

  return available ? 'Available' : 'Unavailable'
}
