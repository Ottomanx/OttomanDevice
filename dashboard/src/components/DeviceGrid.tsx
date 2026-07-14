import type { DeviceEnhanced } from '../types/device'
import { BulkActionToolbar } from './BulkActionToolbar'
import { DeviceCard } from './DeviceCard'
import type { BulkActionType, BulkOperationProgress } from '../types/fleetOperations'

interface DeviceGridProps {
  devices: DeviceEnhanced[]
  previewDeviceId: string | null
  onPreview: (deviceId: string) => void
  canViewDesktop: boolean
  canUseCamera: boolean
  canRestart: boolean
  permissionsLoading: boolean
  selectedDeviceIds: Set<string>
  isAllSelected: boolean
  bulkProgress: BulkOperationProgress
  isBulkRunning: boolean
  onToggleDevice: (deviceId: string) => void
  onToggleSelectAll: () => void
  onRunBulkAction: (action: BulkActionType) => void
  onClearSelection: () => void
}

export function DeviceGrid({
  devices,
  previewDeviceId,
  onPreview,
  canViewDesktop,
  canUseCamera,
  canRestart,
  permissionsLoading,
  selectedDeviceIds,
  isAllSelected,
  bulkProgress,
  isBulkRunning,
  onToggleDevice,
  onToggleSelectAll,
  onRunBulkAction,
  onClearSelection,
}: DeviceGridProps) {
  if (devices.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-700 bg-slate-900/40 px-6 py-16 text-center">
        <p className="text-lg font-medium text-slate-300">No devices registered yet</p>
        <p className="mt-2 text-sm text-slate-500">
          Start an OttomanDevice agent to see it appear here automatically.
        </p>
      </div>
    )
  }

  return (
    <section>
      <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">Fleet</h2>
        <label className="inline-flex items-center gap-2 text-sm text-slate-300">
          <input
            type="checkbox"
            checked={isAllSelected}
            onChange={onToggleSelectAll}
            className="h-4 w-4 rounded border-slate-600 bg-slate-950 text-indigo-500 focus:ring-indigo-400"
          />
          Select all
        </label>
      </div>

      <BulkActionToolbar
        selectedCount={selectedDeviceIds.size}
        progress={bulkProgress}
        isRunning={isBulkRunning}
        canRestart={canRestart}
        canUseCamera={canUseCamera}
        permissionsLoading={permissionsLoading}
        onRunAction={onRunBulkAction}
        onClearSelection={onClearSelection}
      />

      <div className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
        {devices.map((device) => (
          <DeviceCard
            key={device.id}
            device={device}
            isPreviewActive={previewDeviceId === device.device_id}
            isSelected={selectedDeviceIds.has(device.device_id)}
            onToggleSelect={() => onToggleDevice(device.device_id)}
            onPreview={onPreview}
            canViewDesktop={canViewDesktop}
            canUseCamera={canUseCamera}
            permissionsLoading={permissionsLoading}
          />
        ))}
      </div>
    </section>
  )
}
