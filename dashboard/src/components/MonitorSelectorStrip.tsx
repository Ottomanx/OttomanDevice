import {
  formatMonitorResolution,
  type MonitorView,
} from '../utils/remoteMonitorSync'

interface MonitorSelectorStripProps {
  monitors: MonitorView[]
  selectedNumber: number | null
  switchInProgress: boolean
  onSelect: (monitorNumber: number) => void
}

export function MonitorSelectorStrip({
  monitors,
  selectedNumber,
  switchInProgress,
  onSelect,
}: MonitorSelectorStripProps) {
  if (monitors.length === 0) {
    return null
  }

  return (
    <div className="border-b border-slate-800 bg-slate-950/30 px-5 py-3">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
        Monitors
      </p>
      <div className="flex flex-wrap gap-2">
        {monitors.map((monitor) => {
          const selected = monitor.number === selectedNumber
          return (
            <button
              key={monitor.number}
              type="button"
              disabled={switchInProgress}
              onClick={() => onSelect(monitor.number)}
              className={`rounded-lg border px-3 py-2 text-left text-xs transition ${
                selected
                  ? 'border-emerald-500/60 bg-emerald-500/10 text-emerald-100'
                  : 'border-slate-700 bg-slate-900/60 text-slate-300 hover:border-slate-500'
              } disabled:cursor-not-allowed disabled:opacity-60`}
            >
              <span className="block font-semibold">Monitor {monitor.number}</span>
              <span className="mt-1 block text-slate-400">
                {formatMonitorResolution(monitor.width, monitor.height)}
              </span>
              {monitor.isPrimary && (
                <span className="mt-1 inline-block rounded bg-sky-500/20 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-sky-200">
                  Primary
                </span>
              )}
            </button>
          )
        })}
      </div>
    </div>
  )
}
