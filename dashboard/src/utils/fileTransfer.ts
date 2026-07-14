export interface FileTransferProgress {
  transferId: string
  direction: 'upload' | 'download'
  transferred: number
  total: number
  path: string
  status: 'active' | 'complete' | 'error' | 'cancelled'
  errorMessage?: string
}

const CHUNK_SIZE = 64 * 1024

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
  onChunk: (chunkBase64: string) => Promise<void>,
): Promise<void> {
  let offset = 0
  while (offset < file.size) {
    const slice = file.slice(offset, offset + CHUNK_SIZE)
    const buffer = await slice.arrayBuffer()
    await onChunk(arrayBufferToBase64(buffer))
    offset += CHUNK_SIZE
  }
}

export function assembleDownloadChunks(chunks: Map<number, string>): Uint8Array {
  const orderedOffsets = [...chunks.keys()].sort((left, right) => left - right)
  const parts: Uint8Array[] = []
  let totalLength = 0

  for (const offset of orderedOffsets) {
    const chunk = base64ToUint8Array(chunks.get(offset) ?? '')
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

export function triggerBrowserDownload(filename: string, data: Uint8Array): void {
  const blob = new Blob([data.slice()])
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}