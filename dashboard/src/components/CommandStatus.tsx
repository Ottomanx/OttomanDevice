import type { CommandFeedbackStatus, DeviceCommandType } from '../types/device'

interface CommandStatusProps {
  command: DeviceCommandType | null
  status: CommandFeedbackStatus
  failureReason: string | null
}

const statusConfig: Record<
  Exclude<CommandFeedbackStatus, 'idle'>,
  { label: string; className: string }
> = {
  queued: {
    label: 'Queued',
    className: 'bg-amber-500/15 text-amber-300 ring-amber-500/30',
  },
  running: {
    label: 'Running',
    className: 'bg-sky-500/15 text-sky-300 ring-sky-500/30',
  },
  done: {
    label: 'Done',
    className: 'bg-emerald-500/15 text-emerald-300 ring-emerald-500/30',
  },
  failed: {
    label: 'Failed',
    className: 'bg-rose-500/15 text-rose-300 ring-rose-500/30',
  },
}

export function CommandStatus({ command, status, failureReason }: CommandStatusProps) {
  if (status === 'idle' || !command) {
    return null
  }

  const config = statusConfig[status]

  return (
    <div className={`rounded-lg px-3 py-2 text-sm ring-1 ring-inset ${config.className}`}>
      <div className="flex items-center justify-between gap-3">
        <span className="font-medium">
          {command}: {config.label}
        </span>
        {status === 'running' && (
          <span className="h-2 w-2 animate-pulse rounded-full bg-sky-400" />
        )}
      </div>
      {failureReason && <p className="mt-1 text-xs opacity-80">{failureReason}</p>}
    </div>
  )
}
