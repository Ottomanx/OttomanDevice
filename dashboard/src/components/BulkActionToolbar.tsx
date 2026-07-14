import type { BulkActionType, BulkOperationProgress } from '../types/fleetOperations'
import { bulkActionLabel } from '../types/fleetOperations'

interface BulkActionToolbarProps {
  selectedCount: number
  progress: BulkOperationProgress
  isRunning: boolean
  canRestart: boolean
  canUseCamera: boolean
  permissionsLoading: boolean
  onRunAction: (action: BulkActionType) => void
  onClearSelection: () => void
}

const bulkActions: BulkActionType[] = ['restart', 'screenshot', 'camera_test', 'ping']

const actionStyles: Record<BulkActionType, string> = {
  restart: 'border-rose-500/30 bg-rose-500/10 text-rose-300 hover:bg-rose-500/20',
  screenshot: 'border-cyan-500/30 bg-cyan-500/10 text-cyan-300 hover:bg-cyan-500/20',
  camera_test: 'border-amber-500/30 bg-amber-500/10 text-amber-300 hover:bg-amber-500/20',
  ping: 'border-sky-500/30 bg-sky-500/10 text-sky-300 hover:bg-sky-500/20',
}

export function BulkActionToolbar({
  selectedCount,
  progress,
  isRunning,
  canRestart,
  canUseCamera,
  permissionsLoading,
  onRunAction,
  onClearSelection,
}: BulkActionToolbarProps) {
  if (selectedCount === 0) {
    return null
  }

  const progressPercent =
    progress.total > 0 ? Math.round((progress.completed / progress.total) * 100) : 0

  return (
    <section className="mb-4 rounded-2xl border border-indigo-500/30 bg-indigo-500/10 p-4">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <p className="text-sm font-semibold text-indigo-200">
            {selectedCount} device{selectedCount === 1 ? '' : 's'} selected
          </p>
          <p className="mt-1 text-xs text-slate-400">Run a bulk action across the selected fleet.</p>
        </div>

        <div className="flex flex-wrap gap-2">
          {bulkActions.map((action) => {
            const disabled =
              isRunning ||
              permissionsLoading ||
              (action === 'restart' && !canRestart) ||
              (action === 'camera_test' && !canUseCamera)

            return (
              <button
                key={action}
                type="button"
                disabled={disabled}
                onClick={() => onRunAction(action)}
                className={`rounded-lg border px-3 py-2 text-xs font-semibold uppercase tracking-wide transition disabled:cursor-not-allowed disabled:opacity-50 ${actionStyles[action]}`}
              >
                {bulkActionLabel(action)}
              </button>
            )
          })}
          <button
            type="button"
            disabled={isRunning}
            onClick={onClearSelection}
            className="rounded-lg border border-slate-700 bg-slate-950 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-300 transition hover:border-slate-500 hover:text-white disabled:opacity-50"
          >
            Clear
          </button>
        </div>
      </div>

      {progress.phase !== 'idle' && (
        <div className="mt-4 space-y-3 border-t border-indigo-500/20 pt-4">
          <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
            <p className="text-slate-200">
              {progress.action ? bulkActionLabel(progress.action) : 'Bulk action'}: {progress.completed}/
              {progress.total}
            </p>
            <p className="text-xs uppercase tracking-wide text-slate-500">
              {progress.phase === 'running' ? 'In progress' : 'Complete'}
            </p>
          </div>

          <div className="h-2 overflow-hidden rounded-full bg-slate-900">
            <div
              className="h-full rounded-full bg-indigo-400 transition-all duration-300"
              style={{ width: `${progressPercent}%` }}
            />
          </div>

          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            <Stat label="Progress" value={`${progressPercent}%`} />
            <Stat label="Success" value={String(progress.successCount)} tone="success" />
            <Stat label="Failed" value={String(progress.failedCount)} tone="failed" />
          </div>
        </div>
      )}
    </section>
  )
}

interface StatProps {
  label: string
  value: string
  tone?: 'neutral' | 'success' | 'failed'
}

const toneStyles = {
  neutral: 'text-white',
  success: 'text-emerald-300',
  failed: 'text-rose-300',
}

function Stat({ label, value, tone = 'neutral' }: StatProps) {
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-950/70 px-3 py-2">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`mt-1 text-lg font-semibold ${toneStyles[tone]}`}>{value}</p>
    </div>
  )
}
