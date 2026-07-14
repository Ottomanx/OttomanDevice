import { useScreenshotHistory } from '../hooks/useScreenshotHistory'

interface ScreenshotHistoryProps {
  deviceId: string
  deviceName: string
}

export function ScreenshotHistory({ deviceId, deviceName }: ScreenshotHistoryProps) {
  const { screenshots, isLoading, error, lastUpdated } = useScreenshotHistory(deviceId)

  return (
    <section className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/80 shadow-xl shadow-black/20 backdrop-blur">
      <div className="border-b border-slate-800 px-5 py-4">
        <p className="text-xs font-semibold uppercase tracking-[0.2em] text-indigo-400">
          Screenshot History
        </p>
        <h3 className="mt-1 text-lg font-semibold text-white">{deviceName}</h3>
        <p className="mt-1 text-xs text-slate-500">
          Latest captures from storage
          {lastUpdated ? ` · updated ${lastUpdated.toLocaleTimeString()}` : ''}
        </p>
      </div>

      <div className="p-4">
        {isLoading && screenshots.length === 0 && (
          <div className="flex min-h-[160px] items-center justify-center">
            <div className="flex items-center gap-3 text-sm text-slate-400">
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-600 border-t-indigo-400" />
              Loading screenshots…
            </div>
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
            {error}
          </div>
        )}

        {!isLoading && !error && screenshots.length === 0 && (
          <div className="rounded-xl border border-dashed border-slate-700 px-4 py-10 text-center">
            <p className="text-sm font-medium text-slate-300">No screenshots yet</p>
            <p className="mt-2 text-xs text-slate-500">
              Screenshots appear here when captured by the device agent.
            </p>
          </div>
        )}

        {screenshots.length > 0 && (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {screenshots.map((screenshot) => (
              <a
                key={screenshot.name}
                href={screenshot.url}
                target="_blank"
                rel="noreferrer"
                className="group overflow-hidden rounded-xl border border-slate-800 bg-slate-950/60 transition hover:border-indigo-500/40"
              >
                <img
                  src={screenshot.url}
                  alt={`Screenshot ${screenshot.name}`}
                  className="aspect-video w-full object-cover transition group-hover:scale-[1.02]"
                  loading="lazy"
                />
                <p className="truncate px-2 py-2 font-mono text-[10px] text-slate-500">
                  {screenshot.name.replace('.png', '')}
                </p>
              </a>
            ))}
          </div>
        )}
      </div>
    </section>
  )
}
