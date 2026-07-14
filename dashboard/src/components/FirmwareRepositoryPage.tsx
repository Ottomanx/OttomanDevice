import { FirmwareReleaseTable } from './FirmwareReleaseTable'
import { FirmwareUploadPanel } from './FirmwareUploadPanel'
import { OtaStatusPanel } from './OtaStatusPanel'
import { useFirmwareRepository } from '../hooks/useFirmwareRepository'
import { useOtaStatus } from '../hooks/useOtaStatus'
import { usePermissions } from '../hooks/usePermissions'

export function FirmwareRepositoryPage() {
  const { can, isLoading: permissionsLoading } = usePermissions()
  const {
    releases,
    error,
    isLoading,
    isUploading,
    lastUpdated,
    uploadFirmware,
    publishRelease,
    unpublishRelease,
  } = useFirmwareRepository()
  const {
    statuses: otaStatuses,
    error: otaError,
    isLoading: otaLoading,
  } = useOtaStatus()

  const canManageFirmware = can('ota')

  return (
    <section>
      <header className="mb-6 border-b border-slate-800 pb-6">
        <p className="text-sm font-semibold uppercase tracking-[0.2em] text-indigo-400">OttomanDevice</p>
        <h1 className="mt-2 text-3xl font-bold tracking-tight text-white sm:text-4xl">Firmware Repository</h1>
        <p className="mt-3 max-w-3xl text-sm leading-relaxed text-slate-400 sm:text-base">
          Upload signed firmware packages, manage release notes, publish versions, and monitor live OTA
          install progress across the fleet.
        </p>
        <p className="mt-2 text-xs text-slate-500">
          Last updated: {lastUpdated ? lastUpdated.toLocaleTimeString() : '—'}
        </p>
      </header>

      {error && (
        <div className="mb-6 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
          Failed to load firmware repository: {error}
        </div>
      )}

      {!permissionsLoading && !canManageFirmware && (
        <div className="mb-6 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
          OTA permission required to upload or publish firmware packages.
        </div>
      )}

      {otaError && (
        <div className="mb-6 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
          Failed to load OTA status: {otaError}
        </div>
      )}

      <OtaStatusPanel statuses={otaStatuses} isLoading={otaLoading} />

      <FirmwareUploadPanel
        disabled={!canManageFirmware || permissionsLoading}
        isUploading={isUploading}
        onUpload={uploadFirmware}
      />

      <FirmwareReleaseTable
        releases={releases}
        isLoading={isLoading}
        canManage={canManageFirmware}
        onPublish={publishRelease}
        onUnpublish={unpublishRelease}
      />
    </section>
  )
}
