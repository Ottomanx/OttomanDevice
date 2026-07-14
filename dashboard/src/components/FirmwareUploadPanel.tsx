import { useState } from 'react'

interface FirmwareUploadPanelProps {
  disabled: boolean
  isUploading: boolean
  onUpload: (input: { file: File; version: string; releaseNotes: string }) => Promise<void>
}

export function FirmwareUploadPanel({ disabled, isUploading, onUpload }: FirmwareUploadPanelProps) {
  const [version, setVersion] = useState('')
  const [releaseNotes, setReleaseNotes] = useState('')
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [error, setError] = useState<string | null>(null)

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault()
    setError(null)

    if (!selectedFile) {
      setError('Select a firmware package file')
      return
    }

    if (!version.trim()) {
      setError('Version is required')
      return
    }

    try {
      await onUpload({
        file: selectedFile,
        version: version.trim(),
        releaseNotes,
      })
      setVersion('')
      setReleaseNotes('')
      setSelectedFile(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Upload failed')
    }
  }

  return (
    <section className="mb-6 rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
      <h2 className="text-lg font-semibold text-white">Upload firmware package</h2>
      <p className="mt-1 text-sm text-slate-400">
        Packages are hashed and signed before release. Installation is not performed automatically.
      </p>

      <form onSubmit={(event) => void handleSubmit(event)} className="mt-4 grid gap-4 md:grid-cols-2">
        <label className="flex flex-col gap-1 text-xs uppercase tracking-wide text-slate-500">
          Version
          <input
            type="text"
            value={version}
            onChange={(event) => setVersion(event.target.value)}
            placeholder="0.2.0"
            disabled={disabled || isUploading}
            className="rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm normal-case text-white outline-none focus:border-indigo-400 disabled:opacity-50"
          />
        </label>

        <label className="flex flex-col gap-1 text-xs uppercase tracking-wide text-slate-500">
          Package file
          <input
            type="file"
            onChange={(event) => setSelectedFile(event.target.files?.[0] ?? null)}
            disabled={disabled || isUploading}
            className="rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm normal-case text-white file:mr-3 file:rounded-lg file:border-0 file:bg-indigo-500/20 file:px-3 file:py-1 file:text-indigo-200 disabled:opacity-50"
          />
        </label>

        <label className="flex flex-col gap-1 text-xs uppercase tracking-wide text-slate-500 md:col-span-2">
          Release notes
          <textarea
            value={releaseNotes}
            onChange={(event) => setReleaseNotes(event.target.value)}
            rows={4}
            disabled={disabled || isUploading}
            placeholder="Security fixes, compatibility notes, rollout guidance..."
            className="rounded-xl border border-slate-700 bg-slate-950 px-3 py-2 text-sm normal-case text-white outline-none focus:border-indigo-400 disabled:opacity-50"
          />
        </label>

        <div className="md:col-span-2">
          {error && <p className="mb-3 text-sm text-rose-300">{error}</p>}
          <button
            type="submit"
            disabled={disabled || isUploading}
            className="rounded-xl border border-indigo-500/30 bg-indigo-500/15 px-4 py-2 text-sm font-semibold text-indigo-200 transition hover:bg-indigo-500/25 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {isUploading ? 'Uploading…' : 'Upload package'}
          </button>
        </div>
      </form>
    </section>
  )
}
