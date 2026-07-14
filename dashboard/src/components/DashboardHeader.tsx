import type { DeviceEnhanced } from '../types/device'
import { getOnlineStatus } from '../utils/deviceStatus'

interface DashboardHeaderProps {
  devices: DeviceEnhanced[]
  lastUpdated: Date | null
  isLoading: boolean
}

export function DashboardHeader({ devices, lastUpdated, isLoading }: DashboardHeaderProps) {
  const total = devices.length
  const online = devices.filter((device) => getOnlineStatus(device) === 'online').length
  const offline = total - online

  return (
    <header className="mb-8 space-y-6 border-b border-slate-800 pb-8">
      <div className="flex flex-col gap-6 lg:flex-row lg:items-end lg:justify-between">
        <div className="max-w-2xl">
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-indigo-400">
            OttomanDevice
          </p>
          <h1 className="mt-2 text-3xl font-bold tracking-tight text-white sm:text-4xl">
            Device Dashboard
          </h1>
          <p className="mt-3 text-sm leading-relaxed text-slate-400 sm:text-base">
            Monitor fleet telemetry, preview desktops, and track remote commands. Device data
            refreshes every 5 seconds.
          </p>
        </div>

        <div className="rounded-xl border border-slate-800 bg-slate-900/80 px-4 py-3 text-sm lg:min-w-[180px]">
          <div className="flex items-center gap-2 text-slate-300">
            <span
              className={`h-2 w-2 rounded-full ${isLoading ? 'animate-pulse bg-amber-400' : 'bg-emerald-400'}`}
            />
            {isLoading ? 'Loading devices…' : 'Live'}
          </div>
          <p className="mt-1 text-xs text-slate-500">
            Last updated: {lastUpdated ? lastUpdated.toLocaleTimeString() : '—'}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard label="Total devices" value={total} tone="neutral" />
        <StatCard label="Online" value={online} tone="online" />
        <StatCard label="Offline" value={offline} tone="offline" />
      </div>
    </header>
  )
}

interface StatCardProps {
  label: string
  value: number
  tone: 'neutral' | 'online' | 'offline'
}

const toneStyles = {
  neutral: 'border-slate-800 bg-slate-900/60 text-white',
  online: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-300',
  offline: 'border-rose-500/20 bg-rose-500/10 text-rose-300',
}

function StatCard({ label, value, tone }: StatCardProps) {
  return (
    <div className={`rounded-2xl border px-5 py-4 ${toneStyles[tone]}`}>
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-2 text-3xl font-bold">{value}</p>
    </div>
  )
}
