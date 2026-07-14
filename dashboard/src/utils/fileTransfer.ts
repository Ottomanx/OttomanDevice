import type { TransferTransport } from './remoteFileTransferTransport'
import { Base64TransferTransport } from './remoteFileTransferTransport'

export type FileTransferStatus =
  | 'queued'
  | 'active'
  | 'paused'
  | 'complete'
  | 'error'
  | 'cancelled'

export interface FileTransferProgress {
  transferId: string
  direction: 'upload' | 'download'
  transferred: number
  total: number
  path: string
  status: FileTransferStatus
  errorMessage?: string
  speedBytesPerSecond?: number
  etaSeconds?: number
  sha256?: string
  startedAt?: number
}

export interface TransferHistoryEntry extends FileTransferProgress {
  finishedAt?: number
}

export const DEFAULT_CHUNK_SIZE = 65536

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (let index = 0; index < bytes.length; index += 1) {
    binary += String.fromCharCode(bytes[index]!)
  }
  return btoa(binary)
}

function base64ToUint8Array(value: string): Uint8Array {
  const binary = atob(value)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index)
  }
  return bytes
}

export function createTransferId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID()
  }
  return `transfer-${Date.now()}`
}

export async function readFileInChunks(
  file: File,
  onChunk: (chunkBase64: string, offset: number) => Promise<void>,
  chunkSize = DEFAULT_CHUNK_SIZE,
  startOffset = 0,
): Promise<void> {
  let offset = startOffset
  while (offset < file.size) {
    const slice = file.slice(offset, offset + chunkSize)
    const buffer = await slice.arrayBuffer()
    await onChunk(arrayBufferToBase64(buffer), offset)
    offset += buffer.byteLength
  }
}

export function assembleDownloadChunks(
  chunks: Map<number, string>,
  transport: TransferTransport = new Base64TransferTransport(),
): Uint8Array {
  const orderedOffsets = [...chunks.keys()].sort((left, right) => left - right)
  const parts: Uint8Array[] = []
  let totalLength = 0

  for (const offset of orderedOffsets) {
    const encoded = chunks.get(offset) ?? ''
    const chunk = transport.decodeChunk(encoded) ?? base64ToUint8Array(encoded)
    parts.push(chunk)
    totalLength += chunk.length
  }

  const combined = new Uint8Array(totalLength)
  let position = 0
  for (const part of parts) {
    combined.set(part, position)
    position += part.length
  }

  return combined
}

export function formatTransferSpeed(bytesPerSecond?: number): string {
  if (!bytesPerSecond || bytesPerSecond <= 0) {
    return '--'
  }
  if (bytesPerSecond >= 1024 * 1024) {
    return `${(bytesPerSecond / (1024 * 1024)).toFixed(1)} MB/s`
  }
  if (bytesPerSecond >= 1024) {
    return `${(bytesPerSecond / 1024).toFixed(1)} KB/s`
  }
  return `${Math.round(bytesPerSecond)} B/s`
}

export function formatEta(seconds?: number): string {
  if (seconds === undefined || !Number.isFinite(seconds) || seconds <= 0) {
    return '--'
  }
  if (seconds < 60) {
    return `${Math.ceil(seconds)}s`
  }
  const minutes = Math.floor(seconds / 60)
  const remaining = Math.ceil(seconds % 60)
  return `${minutes}m ${remaining}s`
}

export function triggerBrowserDownload(filename: string, data: Uint8Array): void {
  const blob = new Blob([data.slice()])
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}
