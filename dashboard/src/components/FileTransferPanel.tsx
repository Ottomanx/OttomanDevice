import { useRef, useState } from 'react'

import type { FileTransferProgress } from '../utils/fileTransfer'

interface FileTransferPanelProps {
  enabled: boolean
  progress: FileTransferProgress | null
  onUpload: (relativePath: string, file: File) => Promise<void>
  onDownload: (relativePath: string) => Promise<void>
  onCancel: (transferId: string) => void
}

export function FileTransferPanel({
  enabled,
  progress,
  onUpload,
  onDownload,
  onCancel,
}: FileTransferPanelProps) {
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [remotePath, setRemotePath] = useState('')
  const [error, setError] = useState<string | null>(null)

  const progressPercent =
    progress && progress.total > 0
      ? Math.min(100, Math.round((progress.transferred / progress.total) * 100))
      : 0

  const handleUploadClick = () => {
    if (!enabled) {
      return
    }
    fileInputRef.current?.click()
  }

  const handleFileSelected = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file || !enabled) {
      return
    }

    const path = remotePath.trim() || file.name
    setError(null)
    try {
      await onUpload(path, file)
    } catch {
      setError('Upload failed')
    }
  }

  const handleDownload = async () => {
    const path = remotePath.trim()
    if (!path || !enabled) {
      return
    }

    setError(null)
    try {
      await onDownload(path)
    } catch {
      setError('Download failed')
    }
  }

  if (!enabled) {
    return null
  }

  return (
    <div className="border-b border-slate-800 bg-slate-950/40 px-5 py-3">
      <div className="flex flex-wrap items-center gap-3">
        <input
          type="text"
          value={remotePath}
          onChange={(event) => setRemotePath(event.target.value)}
          placeholder="workspace/path/file.txt"
          className="min-w-[220px] flex-1 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 outline-none focus:border-emerald-500/50"
        />
        <button
          type="button"
          onClick={handleUploadClick}
          disabled={progress?.status === 'active'}
          className="rounded-lg border border-emerald-700/50 bg-emerald-500/10 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-emerald-200 transition hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Upload file
        </button>
        <button
          type="button"
          onClick={() => void handleDownload()}
          disabled={!remotePath.trim() || progress?.status === 'active'}
          className="rounded-lg border border-emerald-700/50 bg-emerald-500/10 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-emerald-200 transition hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Download file
        </button>
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          onChange={(event) => void handleFileSelected(event)}
        />
      </div>

      {progress && (
        <div className="mt-3 space-y-2">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span>
              {progress.direction === 'upload' ? 'Uploading' : 'Downloading'}{' '}
              {progress.path}
            </span>
            <span>{progressPercent}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-slate-800">
            <div
              className="h-full rounded-full bg-emerald-500 transition-all"
              style={{ width: `${progressPercent}%` }}
            />
          </div>
          {progress.status === 'active' && (
            <button
              type="button"
              onClick={() => onCancel(progress.transferId)}
              className="text-xs font-semibold uppercase tracking-wide text-rose-300 hover:text-rose-200"
            >
              Cancel transfer
            </button>
          )}
          {progress.status === 'complete' && (
            <p className="text-xs text-emerald-300">Transfer complete</p>
          )}
          {progress.status === 'cancelled' && (
            <p className="text-xs text-amber-300">Transfer cancelled</p>
          )}
          {progress.status === 'error' && (
            <p className="text-xs text-rose-300">{progress.errorMessage ?? 'Transfer failed'}</p>
          )}
        </div>
      )}

      {error && <p className="mt-2 text-xs text-rose-300">{error}</p>}
    </div>
  )
}