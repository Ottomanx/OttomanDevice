from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "dashboard" / "src" / "utils" / "remoteFileTransfer.ts"

CONTENT = r'''import {
  Base64TransferTransport,
  FixedChunkSizeStrategy,
  NoOpBandwidthLimiter,
  type BandwidthLimiter,
  type ChunkSizeStrategy,
  type TransferTransport,
} from './remoteFileTransferTransport'
import {
  loadPendingTransfers,
  removePendingTransfer,
  savePendingTransfer,
  type PendingTransferRecord,
} from './remoteFileTransferStore'
import {
  assembleDownloadChunks,
  createTransferId,
  triggerBrowserDownload,
  type FileTransferProgress,
  type TransferHistoryEntry,
} from './fileTransfer'

export type SendMessageFn = (type: string, payload?: Record<string, unknown>) => void

interface SpeedSample {
  transferred: number
  atMs: number
}

export class RemoteFileTransferController {
  private readonly transport: TransferTransport
  private readonly chunkSizeStrategy: ChunkSizeStrategy
  private readonly bandwidthLimiter: BandwidthLimiter
  private sendMessage: SendMessageFn
  private activeTransferId: string | null = null
  private paused = false
  private downloadChunks = new Map<string, Map<number, string>>()
  private downloadPaths = new Map<string, string>()
  private downloadSha256 = new Map<string, string>()
  private speedSample: SpeedSample | null = null
  private pendingUploadFile: File | null = null

  progress: FileTransferProgress | null = null
  history: TransferHistoryEntry[] = []
  onProgressChange: ((progress: FileTransferProgress | null) => void) | null = null
  onHistoryChange: ((history: TransferHistoryEntry[]) => void) | null = null

  constructor(
    sendMessage: SendMessageFn,
    options?: {
      chunkSize?: number
      chunkSizeStrategy?: ChunkSizeStrategy
      transport?: TransferTransport
      bandwidthLimiter?: BandwidthLimiter
    },
  ) {
    this.sendMessage = sendMessage
    this.transport = options?.transport ?? new Base64TransferTransport()
    this.chunkSizeStrategy =
      options?.chunkSizeStrategy ??
      new FixedChunkSizeStrategy(options?.chunkSize ?? 65536)
    this.bandwidthLimiter = options?.bandwidthLimiter ?? new NoOpBandwidthLimiter()
  }

  setSendMessage(sendMessage: SendMessageFn): void {
    this.sendMessage = sendMessage
  }

  reset(): void {
    this.activeTransferId = null
    this.paused = false
    this.downloadChunks.clear()
    this.downloadPaths.clear()
    this.downloadSha256.clear()
    this.speedSample = null
    this.pendingUploadFile = null
    this.setProgress(null)
  }

  getProgress(): FileTransferProgress | null {
    return this.progress
  }

  getHistory(): TransferHistoryEntry[] {
    return this.history
  }

  async uploadFile(relativePath: string, file: File, overwrite = false): Promise<void> {
    const transferId = createTransferId()
    this.activeTransferId = transferId
    this.paused = false
    this.pendingUploadFile = file
    const sha256 = await computeFileSha256(file)

    this.setProgress({
      transferId,
      direction: 'upload',
      transferred: 0,
      total: file.size,
      path: relativePath,
      status: 'active',
      sha256,
      startedAt: Date.now(),
    })

    this.sendMessage('FILE_UPLOAD', {
      transfer_id: transferId,
      path: relativePath,
      size: file.size,
      sha256,
      overwrite,
    })

    await this.sendUploadChunks(transferId, file, 0)
  }

  downloadFile(relativePath: string): void {
    const transferId = createTransferId()
    this.activeTransferId = transferId
    this.paused = false
    this.downloadChunks.set(transferId, new Map())
    this.downloadPaths.set(transferId, relativePath)

    this.setProgress({
      transferId,
      direction: 'download',
      transferred: 0,
      total: 0,
      path: relativePath,
      status: 'queued',
      startedAt: Date.now(),
    })

    this.sendMessage('FILE_DOWNLOAD', {
      transfer_id: transferId,
      path: relativePath,
    })
  }

  pauseTransfer(transferId: string): void {
    this.paused = true
    this.sendMessage('FILE_UPLOAD', { transfer_id: transferId, pause: true })
    this.sendMessage('FILE_DOWNLOAD', { transfer_id: transferId, pause: true })
    if (this.progress?.transferId === transferId) {
      this.setProgress({ ...this.progress, status: 'paused' })
    }
  }

  resumeTransfer(transferId: string): void {
    this.paused = false
    this.sendMessage('FILE_UPLOAD', { transfer_id: transferId, resume: true })
    this.sendMessage('FILE_DOWNLOAD', { transfer_id: transferId, resume: true })
    if (this.progress?.transferId === transferId) {
      this.setProgress({ ...this.progress, status: 'active' })
    }
    if (this.pendingUploadFile && this.progress?.direction === 'upload') {
      void this.sendUploadChunks(transferId, this.pendingUploadFile, this.progress.transferred)
    }
  }

  cancelTransfer(transferId: string): void {
    if (this.activeTransferId === transferId) {
      this.activeTransferId = null
    }
    this.pendingUploadFile = null
    this.sendMessage('FILE_UPLOAD', { transfer_id: transferId, cancel: true })
    this.sendMessage('FILE_DOWNLOAD', { transfer_id: transferId, cancel: true })
    this.downloadChunks.delete(transferId)
    this.downloadPaths.delete(transferId)
    this.downloadSha256.delete(transferId)
    removePendingTransfer(transferId)
    if (this.progress?.transferId === transferId) {
      this.setProgress({ ...this.progress, status: 'cancelled' })
      this.finalizeHistory(transferId, 'cancelled')
    }
  }

  retryTransfer(transferId: string): void {
    const entry = this.history.find((item) => item.transferId === transferId)
    if (!entry) {
      return
    }
    if (entry.direction === 'download') {
      this.downloadFile(entry.path)
      return
    }
    if (this.pendingUploadFile) {
      void this.uploadFile(entry.path, this.pendingUploadFile)
    }
  }

  resumePendingAfterReconnect(): void {
    const pending = loadPendingTransfers()
    for (const record of pending.values()) {
      if (record.direction !== 'upload') {
        continue
      }
      this.sendMessage('FILE_UPLOAD', {
        transfer_id: record.transferId,
        path: record.path,
        size: record.total,
        sha256: record.sha256,
        resume: true,
        offset: record.transferred,
      })
    }
  }

  handleMessage(type: string, payload: Record<string, unknown>): void {
    switch (type) {
      case 'FILE_PROGRESS':
        this.handleProgress(payload)
        break
      case 'FILE_COMPLETE':
        void this.handleComplete(payload)
        break
      case 'FILE_ERROR':
        this.handleError(payload)
        break
      case 'FILE_DOWNLOAD':
        this.handleDownloadChunk(payload)
        break
      default:
        break
    }
  }

  private async sendUploadChunks(
    transferId: string,
    file: File,
    startOffset: number,
  ): Promise<void> {
    const chunkSize = this.chunkSizeStrategy.chunkSize()
    let offset = startOffset

    while (offset < file.size) {
      if (this.activeTransferId !== transferId || this.paused) {
        return
      }

      const slice = file.slice(offset, offset + chunkSize)
      const buffer = await slice.arrayBuffer()
      await this.bandwidthLimiter.acquire(buffer.byteLength)

      const encoded = this.transport.encodeChunk(buffer)
      const payload: Record<string, unknown> = {
        transfer_id: transferId,
        offset,
      }
      if (typeof encoded === 'string') {
        payload.chunk = encoded
      } else {
        payload.chunk = encoded
      }

      this.sendMessage('FILE_UPLOAD', payload)
      await this.bandwidthLimiter.report(buffer.byteLength)
      offset += buffer.byteLength

      savePendingTransfer({
        transferId,
        direction: 'upload',
        path: this.progress?.path ?? file.name,
        total: file.size,
        transferred: offset,
        sha256: this.progress?.sha256,
        fileName: file.name,
        fileSize: file.size,
      })
    }
  }

  private handleProgress(payload: Record<string, unknown>): void {
    const transferId =
      typeof payload.transfer_id === 'string' ? payload.transfer_id : null
    if (!transferId) {
      return
    }

    const transferred =
      typeof payload.transferred === 'number' ? payload.transferred : 0
    const total = typeof payload.total === 'number' ? payload.total : 0
    const direction = payload.direction === 'download' ? 'download' : 'upload'
    const state = typeof payload.state === 'string' ? payload.state : 'active'
    const status = mapProgressState(state)

    const speed = this.computeSpeed(transferId, transferred)
    const etaSeconds = speed > 0 && total > transferred ? (total - transferred) / speed : undefined

    const path =
      this.progress?.transferId === transferId
        ? this.progress.path
        : (this.downloadPaths.get(transferId) ?? '')

    this.setProgress({
      transferId,
      direction,
      transferred,
      total,
      path,
      status,
      speedBytesPerSecond: speed,
      etaSeconds,
      startedAt: this.progress?.startedAt ?? Date.now(),
      sha256: this.progress?.sha256,
    })
  }

  private async handleComplete(payload: Record<string, unknown>): Promise<void> {
    const transferId =
      typeof payload.transfer_id === 'string' ? payload.transfer_id : null
    if (!transferId) {
      return
    }

    const path = typeof payload.path === 'string' ? payload.path : ''
    const size = typeof payload.size === 'number' ? payload.size : 0
    const sha256 = typeof payload.sha256 === 'string' ? payload.sha256 : undefined

    if (this.activeTransferId === transferId) {
      this.activeTransferId = null
    }

    removePendingTransfer(transferId)

    const isDownload = this.downloadPaths.has(transferId)
    if (isDownload) {
      const chunks = this.downloadChunks.get(transferId)
      if (chunks) {
        const data = assembleDownloadChunks(chunks, this.transport)
        const expected = sha256 ?? this.downloadSha256.get(transferId)
        if (expected) {
          const actual = await computeBytesSha256(data)
          if (actual !== expected) {
            this.handleError({
              transfer_id: transferId,
              code: 'HASH_MISMATCH',
              message: 'SHA256 verification failed',
            })
            return
          }
        }
        const filename = path.split('/').pop() || 'download'
        triggerBrowserDownload(filename, data)
      }
      this.downloadChunks.delete(transferId)
      this.downloadPaths.delete(transferId)
      this.downloadSha256.delete(transferId)
    }

    this.setProgress({
      transferId,
      direction: isDownload ? 'download' : 'upload',
      transferred: size,
      total: size,
      path,
      status: 'complete',
      sha256,
      startedAt: this.progress?.startedAt ?? Date.now(),
    })
    this.finalizeHistory(transferId, 'complete')
    this.pendingUploadFile = null
  }

  private handleError(payload: Record<string, unknown>): void {
    const transferId =
      typeof payload.transfer_id === 'string' ? payload.transfer_id : null
    const code = typeof payload.code === 'string' ? payload.code : 'ERROR'
    const errorMessage =
      typeof payload.message === 'string' ? payload.message : 'Transfer failed'

    if (transferId && this.activeTransferId === transferId) {
      this.activeTransferId = null
    }
    if (transferId) {
      this.downloadChunks.delete(transferId)
      this.downloadPaths.delete(transferId)
    }

    if (transferId && this.progress?.transferId === transferId) {
      const status = code === 'CANCELLED' ? 'cancelled' : code === 'PAUSED' ? 'paused' : 'error'
      this.setProgress({
        ...this.progress,
        status,
        errorMessage,
      })
      if (status !== 'paused') {
        this.finalizeHistory(transferId, status, errorMessage)
      }
    }
  }

  private handleDownloadChunk(payload: Record<string, unknown>): void {
    const transferId =
      typeof payload.transfer_id === 'string' ? payload.transfer_id : null
    const offset = typeof payload.offset === 'number' ? payload.offset : 0
    const isFinal = payload.final === true
    if (!transferId || !('chunk' in payload)) {
      return
    }

    const encoded = payload.chunk
    const decoded = this.transport.decodeChunk(encoded)
    if (!decoded) {
      return
    }

    const chunks = this.downloadChunks.get(transferId) ?? new Map()
    if (typeof encoded === 'string') {
      chunks.set(offset, encoded)
    } else {
      chunks.set(offset, arrayBufferToBase64(decoded.buffer))
    }
    this.downloadChunks.set(transferId, chunks)

    if (typeof payload.sha256 === 'string') {
      this.downloadSha256.set(transferId, payload.sha256)
    }

    if (!isFinal) {
      return
    }
  }

  private computeSpeed(transferId: string, transferred: number): number {
    const now = Date.now()
    if (!this.speedSample || this.progress?.transferId !== transferId) {
      this.speedSample = { transferred, atMs: now }
      return 0
    }
    const elapsed = (now - this.speedSample.atMs) / 1000
    if (elapsed <= 0) {
      return this.progress?.speedBytesPerSecond ?? 0
    }
    const speed = (transferred - this.speedSample.transferred) / elapsed
    this.speedSample = { transferred, atMs: now }
    return speed > 0 ? speed : 0
  }

  private setProgress(progress: FileTransferProgress | null): void {
    this.progress = progress
    this.onProgressChange?.(progress)
  }

  private finalizeHistory(
    transferId: string,
    status: FileTransferProgress['status'],
    errorMessage?: string,
  ): void {
    if (!this.progress || this.progress.transferId !== transferId) {
      return
    }
    const entry: TransferHistoryEntry = {
      ...this.progress,
      status,
      errorMessage,
      finishedAt: Date.now(),
    }
    this.history = [entry, ...this.history.filter((item) => item.transferId !== transferId)].slice(
      0,
      20,
    )
    this.onHistoryChange?.(this.history)
  }
}

function mapProgressState(state: string): FileTransferProgress['status'] {
  if (state === 'paused') {
    return 'paused'
  }
  if (state === 'queued') {
    return 'queued'
  }
  return 'active'
}

export async function computeFileSha256(file: File): Promise<string> {
  const buffer = await file.arrayBuffer()
  return computeBytesSha256(new Uint8Array(buffer))
}

export async function computeBytesSha256(data: Uint8Array): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', data)
  return [...new Uint8Array(digest)]
    .map((byte) => byte.toString(16).padStart(2, '0'))
    .join('')
}

function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer)
  let binary = ''
  for (let index = 0; index < bytes.length; index += 1) {
    binary += String.fromCharCode(bytes[index]!)
  }
  return btoa(binary)
}
'''

if __name__ == '__main__':
    OUT.write_text(CONTENT, encoding='utf-8')
    assert b'\x00' not in OUT.read_bytes()
    print('wrote', OUT.name)
