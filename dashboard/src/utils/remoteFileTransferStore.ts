const STORAGE_KEY = 'ottoman.fileTransfer.pending'

export interface PendingTransferRecord {
  transferId: string
  direction: 'upload' | 'download'
  path: string
  total: number
  transferred: number
  sha256?: string
  fileName?: string
  fileSize?: number
  fileType?: string
}

export function savePendingTransfer(record: PendingTransferRecord): void {
  try {
    const existing = loadPendingTransfers()
    existing.set(record.transferId, record)
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify([...existing.entries()]))
  } catch {
    // ignore storage failures
  }
}

export function removePendingTransfer(transferId: string): void {
  try {
    const existing = loadPendingTransfers()
    existing.delete(transferId)
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify([...existing.entries()]))
  } catch {
    // ignore
  }
}

export function loadPendingTransfers(): Map<string, PendingTransferRecord> {
  try {
    const raw = sessionStorage.getItem(STORAGE_KEY)
    if (!raw) {
      return new Map()
    }
    const parsed = JSON.parse(raw) as [string, PendingTransferRecord][]
    return new Map(parsed)
  } catch {
    return new Map()
  }
}

export function clearPendingTransfers(): void {
  try {
    sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    // ignore
  }
}
