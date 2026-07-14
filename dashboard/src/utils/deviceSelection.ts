export function toggleDeviceSelection(selected: ReadonlySet<string>, deviceId: string): Set<string> {
  const next = new Set(selected)
  if (next.has(deviceId)) {
    next.delete(deviceId)
  } else {
    next.add(deviceId)
  }
  return next
}

export function selectAllDeviceIds(deviceIds: readonly string[]): Set<string> {
  return new Set(deviceIds)
}

export function clearDeviceSelection(): Set<string> {
  return new Set()
}

export function areAllDevicesSelected(deviceIds: readonly string[], selected: ReadonlySet<string>): boolean {
  if (deviceIds.length === 0) {
    return false
  }

  return deviceIds.every((deviceId) => selected.has(deviceId))
}

export function isDeviceSelected(selected: ReadonlySet<string>, deviceId: string): boolean {
  return selected.has(deviceId)
}
