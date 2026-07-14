from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "dashboard" / "src" / "components" / "FileTransferPanel.tsx"

OUT.write_text(
    r"""import { useRef, useState } from 'react'

import {
  formatEta,
  formatTransferSpeed,
  type FileTransferProgress,
  type TransferHistoryEntry,
} from '../utils/fileTransfer'

interface FileTransferPanelProps {
  enabled: boolean
  progress: FileTransferProgress | null
  history: TransferHistoryEntry[]
  onUpload: (relativePath: string, file: File) => Promise<void>
  onDownload: (relativePath: string) => Promise<void>
  onCancel: (transferId: string) => void
  onPause: (transferId: string) => void
  onResume: (transferId: string) => void
  onRetry: (transferId: string) => void
}

export function FileTransferPanel({
  enabled,
  progress,
  history,
  onUpload,
  onDownload,
  onCancel,
  onPause,
  onResume,
  onRetry,
}: FileTransferPanelProps) {
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const [remotePath, setRemotePath] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [dragActive, setDragActive] = useState(false)

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

  const handleFileSelected = async (file: File) => {
    if (!enabled) {
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

  const handleInputChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (file) {
      await handleFileSelected(file)
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

  const handleDrop = async (event: React.DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setDragActive(false)
    if (!enabled) {
      return
    }
    const file = event.dataTransfer.files?.[0]
    if (file) {
      await handleFileSelected(file)
    }
  }

  if (!enabled) {
    return null
  }

  return (
    <div className="border-b border-slate-800 bg-slate-950/40 px-5 py-3">
      <div
        className={`mb-3 rounded-lg border border-dashed px-4 py-6 text-center transition ${
          dragActive
            ? 'border-emerald-400 bg-emerald-500/10'
            : 'border-slate-700 bg-slate-900/40'
        }`}
        onDragEnter={(event) => {
          event.preventDefault()
          setDragActive(true)
        }}
        onDragOver={(event) => event.preventDefault()}
        onDragLeave={() => setDragActive(false)}
        onDrop={(event) => void handleDrop(event)}
      >
        <p className="text-sm text-slate-300">Drag and drop a file to upload</p>
        <button
          type="button"
          onClick={handleUploadClick}
          className="mt-2 text-xs font-semibold uppercase tracking-wide text-emerald-300 hover:text-emerald-200"
        >
          Browse files
        </button>
      </div>

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
          disabled={progress?.status === 'active' || progress?.status === 'queued'}
          className="rounded-lg border border-emerald-700/50 bg-emerald-500/10 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-emerald-200 transition hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Upload file
        </button>
        <button
          type="button"
          onClick={() => void handleDownload()}
          disabled={
            !remotePath.trim() ||
            progress?.status === 'active' ||
            progress?.status === 'queued'
          }
          className="rounded-lg border border-emerald-700/50 bg-emerald-500/10 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-emerald-200 transition hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-50"
        >
          Download file
        </button>
        <input
          ref={fileInputRef}
          type="file"
          className="hidden"
          onChange={(event) => void handleInputChange(event)}
        />
      </div>

      {progress && (
        <div className="mt-3 space-y-2">
          <div className="flex items-center justify-between text-xs text-slate-400">
            <span>
              {progress.direction === 'upload' ? 'Uploading' : 'Downloading'} {progress.path}
            </span>
            <span>{progressPercent}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-slate-800">
            <div
              className="h-full rounded-full bg-emerald-500 transition-all"
              style={{ width: `${progressPercent}%` }}
            />
          </div>
          <div className="flex flex-wrap items-center gap-4 text-xs text-slate-500">
            <span>Speed: {formatTransferSpeed(progress.speedBytesPerSecond)}</span>
            <span>ETA: {formatEta(progress.etaSeconds)}</span>
            {progress.status === 'queued' && <span className="text-amber-300">Queued</span>}
          </div>
          <div className="flex flex-wrap gap-3">
            {(progress.status === 'active' || progress.status === 'queued') && (
              <>
                <button
                  type="button"
                  onClick={() => onPause(progress.transferId)}
                  className="text-xs font-semibold uppercase tracking-wide text-amber-300 hover:text-amber-200"
                >
                  Pause
                </button>
                <button
                  type="button"
                  onClick={() => onCancel(progress.transferId)}
                  className="text-xs font-semibold uppercase tracking-wide text-rose-300 hover:text-rose-200"
                >
                  Cancel
                </button>
              </>
            )}
            {progress.status === 'paused' && (
              <button
                type="button"
                onClick={() => onResume(progress.transferId)}
                className="text-xs font-semibold uppercase tracking-wide text-emerald-300 hover:text-emerald-200"
              >
                Resume
              </button>
            )}
          </div>
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

      {history.length > 0 && (
        <div className="mt-4 space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
            Transfer history
          </p>
          <ul className="max-h-32 space-y-1 overflow-y-auto text-xs text-slate-400">
            {history.map((entry) => (
              <li
                key={`${entry.transferId}-${entry.finishedAt ?? entry.startedAt ?? 0}`}
                className="flex items-center justify-between gap-2 rounded border border-slate-800 px-2 py-1"
              >
                <span>
                  {entry.direction} {entry.path} ({entry.status})
                </span>
                {entry.status === 'error' && (
                  <button
                    type="button"
                    onClick={() => onRetry(entry.transferId)}
                    className="font-semibold uppercase tracking-wide text-emerald-300 hover:text-emerald-200"
                  >
                    Retry
                  </button>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      {error && <p className="mt-2 text-xs text-rose-300">{error}</p>}
    </div>
  )
}
""",
    encoding="utf-8",
)
print("wrote", OUT.name)
