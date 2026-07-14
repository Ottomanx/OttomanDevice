import type { OnlineStatus } from '../types/device'
import { getStatusLabel } from '../utils/deviceStatus'

interface StatusBadgeProps {
  status: OnlineStatus
}

const statusStyles: Record<OnlineStatus, string> = {
  online: 'bg-emerald-500/15 text-emerald-400 ring-emerald-500/30',
  offline: 'bg-rose-500/15 text-rose-400 ring-rose-500/30',
  unknown: 'bg-slate-500/15 text-slate-400 ring-slate-500/30',
}

const statusDotStyles: Record<OnlineStatus, string> = {
  online: 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]',
  offline: 'bg-rose-400',
  unknown: 'bg-slate-400',
}

export function StatusBadge({ status }: StatusBadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wide ring-1 ring-inset ${statusStyles[status]}`}
    >
      <span className={`h-2 w-2 rounded-full ${statusDotStyles[status]}`} />
      {getStatusLabel(status)}
    </span>
  )
}
