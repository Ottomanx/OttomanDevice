import { useDeviceCommand } from '../hooks/useDeviceCommand'
import type { DeviceEnhanced } from '../types/device'
import { getOnlineStatus } from '../utils/deviceStatus'
import { formatCameraStatus, formatRelativeTime } from '../utils/format'
import { CommandButton } from './CommandButton'
import { CommandStatus } from './CommandStatus'
import { MetricBar } from './MetricBar'
import { StatusBadge } from './StatusBadge'

interface DeviceCardProps {
  device: DeviceEnhanced
  isPreviewActive: boolean
  isSelected: boolean
  onToggleSelect: () => void
  onPreview: (deviceId: string) => void
  canViewDesktop: boolean
  canUseCamera: boolean
  permissionsLoading: boolean
}

export function DeviceCard({
  device,
  isPreviewActive,
  isSelected,
  onToggleSelect,
  onPreview,
  canViewDesktop,
  canUseCamera,
  permissionsLoading,
}: DeviceCardProps) {
  const { activeCommand, commandStatus, failureReason, sendCommand } = useDeviceCommand()
  const onlineStatus = getOnlineStatus(device)
  const displayName = device.computer_name || device.hostname || device.device_id
  const isCommandBusy = commandStatus === 'queued' || commandStatus === 'running'

  return (
    <article className={`flex h-full flex-col rounded-2xl border bg-slate-900/70 p-5 shadow-xl shadow-black/20 backdrop-blur ${
      isSelected ? 'border-indigo-500/50 ring-1 ring-indigo-500/30' : 'border-slate-800'
    }`}>
      <div className="mb-5 flex items-start justify-between gap-3">
        <label className="inline-flex items-start gap-3 min-w-0">
          <input
            type="checkbox"
            checked={isSelected}
            onChange={onToggleSelect}
            className="mt-1 h-4 w-4 rounded border-slate-600 bg-slate-950 text-indigo-500 focus:ring-indigo-400"
          />
          <div className="min-w-0">
            <p className="text-xs uppercase tracking-wide text-slate-500">Device name</p>
            <h2 className="mt-1 truncate text-lg font-semibold text-white">{displayName}</h2>
            <p className="mt-1 truncate font-mono text-xs text-slate-500">{device.device_id}</p>
          </div>
        </label>
        <StatusBadge status={onlineStatus} />
      </div>

      <div className="mb-5 space-y-4">
        <MetricBar label="CPU" value={device.cpu_usage} />
        <MetricBar label="RAM" value={device.ram_usage} />
        <MetricBar label="Disk" value={device.disk_usage} />
      </div>

      <dl className="mb-5 grid grid-cols-2 gap-3 text-sm">
        <div className="rounded-xl bg-slate-950/60 p-3">
          <dt className="text-xs uppercase tracking-wide text-slate-500">Camera status</dt>
          <dd className="mt-1 font-medium text-slate-200">
            {formatCameraStatus(device.camera_available)}
          </dd>
        </div>
        <div className="rounded-xl bg-slate-950/60 p-3">
          <dt className="text-xs uppercase tracking-wide text-slate-500">Last heartbeat</dt>
          <dd className="mt-1 font-medium text-slate-200">
            {formatRelativeTime(device.last_online_at)}
          </dd>
        </div>
      </dl>

      <div className="mb-4">
        <CommandStatus
          command={activeCommand}
          status={commandStatus}
          failureReason={failureReason}
        />
      </div>

      <div className="mt-auto space-y-2">
        <button
          type="button"
          onClick={() => onPreview(device.device_id)}
          disabled={permissionsLoading || !canViewDesktop}
          className={`w-full rounded-lg border px-3 py-2 text-xs font-semibold uppercase tracking-wide transition ${
            isPreviewActive
              ? 'border-indigo-500/50 bg-indigo-500/20 text-indigo-200'
              : canViewDesktop
                ? 'border-indigo-500/30 bg-indigo-500/10 text-indigo-300 hover:bg-indigo-500/20'
                : 'cursor-not-allowed border-slate-700/50 bg-slate-800/40 text-slate-500'
          }`}
        >
          {!canViewDesktop
            ? 'Desktop permission required'
            : isPreviewActive
              ? 'Viewing desktop'
              : 'View desktop'}
        </button>

        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          <CommandButton
            command="PING"
            label="Ping"
            isPending={activeCommand === 'PING' && isCommandBusy}
            disabled={isCommandBusy && activeCommand !== 'PING'}
            onClick={() => void sendCommand(device.device_id, 'PING')}
          />
          <CommandButton
            command="HEARTBEAT"
            label="Heartbeat"
            isPending={activeCommand === 'HEARTBEAT' && isCommandBusy}
            disabled={isCommandBusy && activeCommand !== 'HEARTBEAT'}
            onClick={() => void sendCommand(device.device_id, 'HEARTBEAT')}
          />
          <CommandButton
            command="CAMERA_TEST"
            label="Camera test"
            isPending={activeCommand === 'CAMERA_TEST' && isCommandBusy}
            disabled={
              !canUseCamera || permissionsLoading || (isCommandBusy && activeCommand !== 'CAMERA_TEST')
            }
            onClick={() => void sendCommand(device.device_id, 'CAMERA_TEST')}
          />
        </div>
      </div>
    </article>
  )
}
