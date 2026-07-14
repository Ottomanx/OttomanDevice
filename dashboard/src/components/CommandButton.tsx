import type { DeviceCommandType } from '../types/device'

interface CommandButtonProps {
  command: DeviceCommandType
  label: string
  isPending: boolean
  disabled: boolean
  onClick: () => void
}

const commandStyles: Record<DeviceCommandType, string> = {
  PING: 'border-sky-500/30 bg-sky-500/10 text-sky-300 hover:bg-sky-500/20',
  HEARTBEAT: 'border-violet-500/30 bg-violet-500/10 text-violet-300 hover:bg-violet-500/20',
  CAMERA_TEST: 'border-amber-500/30 bg-amber-500/10 text-amber-300 hover:bg-amber-500/20',
  SCREENSHOT: 'border-cyan-500/30 bg-cyan-500/10 text-cyan-300 hover:bg-cyan-500/20',
}

export function CommandButton({ command, label, isPending, disabled, onClick }: CommandButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled || isPending}
      className={`rounded-lg border px-3 py-2 text-xs font-semibold uppercase tracking-wide transition disabled:cursor-not-allowed disabled:opacity-50 ${commandStyles[command]}`}
    >
      {isPending ? 'Sending…' : label}
    </button>
  )
}
