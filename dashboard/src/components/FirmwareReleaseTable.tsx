import type { FirmwareRelease } from '../types/firmware'

interface FirmwareReleaseTableProps {
  releases: FirmwareRelease[]
  isLoading: boolean
  canManage: boolean
  onPublish: (releaseId: string) => Promise<void>
  onUnpublish: (releaseId: string) => Promise<void>
}

export function FirmwareReleaseTable({
  releases,
  isLoading,
  canManage,
  onPublish,
  onUnpublish,
}: FirmwareReleaseTableProps) {
  if (isLoading && releases.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-800 bg-slate-900/40 px-6 py-16 text-center text-slate-400">
        Loading firmware releases…
      </div>
    )
  }

  if (releases.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-800 bg-slate-900/40 px-6 py-16 text-center text-slate-400">
        No firmware packages uploaded yet.
      </div>
    )
  }

  return (
    <div className="overflow-x-auto rounded-2xl border border-slate-800 bg-slate-900/70">
      <table className="min-w-full divide-y divide-slate-800 text-left text-sm">
        <thead className="bg-slate-950/70 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-4 py-3">Version</th>
            <th className="px-4 py-3">File</th>
            <th className="px-4 py-3">Size</th>
            <th className="px-4 py-3">SHA256</th>
            <th className="px-4 py-3">Status</th>
            <th className="px-4 py-3">Release notes</th>
            <th className="px-4 py-3">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800 text-slate-200">
          {releases.map((release) => (
            <tr key={release.id} className="align-top hover:bg-slate-950/40">
              <td className="px-4 py-3 font-medium text-white">{release.package.version}</td>
              <td className="px-4 py-3">{release.package.file_name}</td>
              <td className="px-4 py-3">{formatFileSize(release.package.file_size_bytes)}</td>
              <td className="px-4 py-3 font-mono text-xs text-slate-400">
                {release.package.sha256.slice(0, 12)}…
              </td>
              <td className="px-4 py-3">
                <span
                  className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
                    release.published
                      ? 'bg-emerald-500/15 text-emerald-300'
                      : 'bg-slate-700/40 text-slate-300'
                  }`}
                >
                  {release.published ? 'Published' : 'Draft'}
                </span>
              </td>
              <td className="px-4 py-3 max-w-xs whitespace-pre-wrap text-slate-300">
                {release.release_notes || '—'}
              </td>
              <td className="px-4 py-3">
                {canManage && (
                  <div className="flex flex-wrap gap-2">
                    {release.published ? (
                      <button
                        type="button"
                        onClick={() => void onUnpublish(release.id)}
                        className="rounded-lg border border-slate-700 px-2 py-1 text-xs text-slate-200 hover:border-rose-400 hover:text-rose-200"
                      >
                        Unpublish
                      </button>
                    ) : (
                      <button
                        type="button"
                        onClick={() => void onPublish(release.id)}
                        className="rounded-lg border border-emerald-500/30 bg-emerald-500/10 px-2 py-1 text-xs text-emerald-200 hover:bg-emerald-500/20"
                      >
                        Publish
                      </button>
                    )}
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`
  }

  const kb = bytes / 1024
  if (kb < 1024) {
    return `${kb.toFixed(1)} KB`
  }

  return `${(kb / 1024).toFixed(1)} MB`
}
