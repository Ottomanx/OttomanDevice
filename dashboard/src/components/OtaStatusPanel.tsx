import type { DeviceOtaStatus } from '../types/ota'
import { otaInstallResult, otaStatusLabel } from '../types/ota'

interface OtaStatusPanelProps {
  statuses: DeviceOtaStatus[]
  isLoading: boolean
}

const statusTone: Record<string, string> = {
  completed: 'text-emerald-300',
  failed: 'text-rose-300',
  rollback: 'text-amber-300',
  installing: 'text-indigo-300',
  downloading: 'text-sky-300',
  verifying: 'text-cyan-300',
}

export function OtaStatusPanel({ statuses, isLoading }: OtaStatusPanelProps) {
  if (isLoading && statuses.length === 0) {
    return (
      <section className="mb-6 rounded-2xl border border-dashed border-slate-800 bg-slate-900/40 px-6 py-10 text-center text-slate-400">
        Loading live OTA status…
      </section>
    )
  }

  if (statuses.length === 0) {
    return (
      <section className="mb-6 rounded-2xl border border-dashed border-slate-800 bg-slate-900/40 px-6 py-10 text-center text-slate-400">
        No OTA activity reported yet.
      </section>
    )
  }

  return (
    <section className="mb-6 rounded-2xl border border-slate-800 bg-slate-900/70 p-4">
      <div className="mb-4">
        <h2 className="text-lg font-semibold text-white">Live OTA Status</h2>
        <p className="mt-1 text-sm text-slate-400">Fleet install progress and results refresh every 5 seconds.</p>
      </div>

      <div className="space-y-3">
        {statuses.map((status) => (
          <article
            key={status.device_id}
            className="rounded-xl border border-slate-800 bg-slate-950/70 p-4"
          >
            <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
              <div>
                <p className="font-medium text-white">{status.device_name ?? status.device_id}</p>
                <p className="font-mono text-xs text-slate-500">{status.device_id}</p>
              </div>
              <div className="text-sm text-slate-300">
                {status.current_version ?? '—'} → {status.target_version ?? '—'}
              </div>
            </div>

            <div className="mt-4 grid gap-3 md:grid-cols-3">
              <Metric label="Status" value={otaStatusLabel(status.status)} tone={statusTone[status.status]} />
              <Metric label="Progress" value={`${status.progress}%`} />
              <Metric label="Result" value={otaInstallResult(status.status, status.message)} />
            </div>

            <div className="mt-4 h-2 overflow-hidden rounded-full bg-slate-900">
              <div
                className={`h-full rounded-full transition-all duration-300 ${
                  status.status === 'failed' ? 'bg-rose-400' : 'bg-indigo-400'
                }`}
                style={{ width: `${Math.max(0, Math.min(100, status.progress))}%` }}
              />
            </div>
          </article>
        ))}
      </div>
    </section>
  )
}

interface MetricProps {
  label: string
  value: string
  tone?: string
}

function Metric({ label, value, tone = 'text-white' }: MetricProps) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-900/80 px-3 py-2">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className={`mt-1 text-sm font-medium ${tone}`}>{value}</p>
    </div>
  )
}
