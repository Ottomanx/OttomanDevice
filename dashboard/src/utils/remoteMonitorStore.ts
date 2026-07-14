const STORAGE_PREFIX = 'ottoman.remoteDesktop.lastMonitor.'

export function saveLastSelectedMonitor(deviceId: string, monitorNumber: number): void {
  try {
    sessionStorage.setItem(
      `${STORAGE_PREFIX}${deviceId}`,
      JSON.stringify({ monitorNumber, updatedAt: Date.now() }),
    )
  } catch {
    // ignore storage failures
  }
}

export function loadLastSelectedMonitor(deviceId: string): number | null {
  try {
    const raw = sessionStorage.getItem(`${STORAGE_PREFIX}${deviceId}`)
    if (!raw) {
      return null
    }
    const parsed = JSON.parse(raw) as { monitorNumber?: number }
    return typeof parsed.monitorNumber === 'number' ? parsed.monitorNumber : null
  } catch {
    return null
  }
}

export function clearLastSelectedMonitor(deviceId: string): void {
  try {
    sessionStorage.removeItem(`${STORAGE_PREFIX}${deviceId}`)
  } catch {
    // ignore
  }
}
