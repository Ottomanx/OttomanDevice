import { useMemo, useState } from 'react'

import { AppNav, type AppPage } from './components/AppNav'
import { DashboardHeader } from './components/DashboardHeader'
import { DesktopPreviewPanel } from './components/DesktopPreviewPanel'
import { DeviceGrid } from './components/DeviceGrid'
import { FirmwareRepositoryPage } from './components/FirmwareRepositoryPage'
import { InventoryPage } from './components/InventoryPage'
import { ScreenshotHistory } from './components/ScreenshotHistory'
import { SignInForm } from './components/SignInForm'
import { useAuth } from './contexts/AuthContext'
import { useBulkOperations } from './hooks/useBulkOperations'
import { useDeviceSelection } from './hooks/useDeviceSelection'
import { useDevices } from './hooks/useDevices'
import { usePermissions } from './hooks/usePermissions'
import { getOnlineStatus } from './utils/deviceStatus'
import type { BulkActionType } from './types/fleetOperations'

function AuthLoadingScreen() {
  return (
    <div className="flex min-h-svh items-center justify-center bg-[radial-gradient(circle_at_top,_rgba(99,102,241,0.18),_transparent_45%),linear-gradient(180deg,_#0a0f1a_0%,_#020617_100%)]">
      <p className="text-sm text-slate-400">Restoring session…</p>
    </div>
  )
}

function AuthenticatedDashboard() {
  const [activePage, setActivePage] = useState<AppPage>('dashboard')
  const { devices, error, isLoading, lastUpdated } = useDevices()
  const { can, isLoading: permissionsLoading, error: permissionsError } = usePermissions()
  const [previewDeviceId, setPreviewDeviceId] = useState<string | null>(null)
  const {
    selectedDeviceIds,
    isAllSelected,
    toggleDevice,
    selectAll,
    clearSelection,
  } = useDeviceSelection()
  const { progress: bulkProgress, isRunning: isBulkRunning, runBulkAction } = useBulkOperations()

  const deviceIds = useMemo(() => devices.map((device) => device.device_id), [devices])

  const previewDevice = useMemo(
    () => devices.find((device) => device.device_id === previewDeviceId) ?? null,
    [devices, previewDeviceId],
  )

  const handlePreview = (deviceId: string) => {
    setPreviewDeviceId((current) => (current === deviceId ? null : deviceId))
  }

  const handleRunBulkAction = (action: BulkActionType) => {
    void runBulkAction([...selectedDeviceIds], action)
  }

  const previewDeviceName =
    previewDevice?.computer_name || previewDevice?.hostname || previewDevice?.device_id || ''

  return (
    <div className="min-h-svh bg-[radial-gradient(circle_at_top,_rgba(99,102,241,0.18),_transparent_45%),linear-gradient(180deg,_#0a0f1a_0%,_#020617_100%)]">
      <main className="mx-auto max-w-7xl px-4 py-6 sm:px-6 sm:py-8 lg:px-8">
        <AppNav activePage={activePage} onNavigate={setActivePage} />

        {activePage === 'inventory' ? (
          <InventoryPage />
        ) : activePage === 'firmware' ? (
          <FirmwareRepositoryPage />
        ) : (
          <>
            <DashboardHeader
              devices={devices}
              lastUpdated={lastUpdated}
              isLoading={isLoading && devices.length === 0}
            />

            {error && (
              <div className="mb-6 rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
                Failed to load devices: {error}
              </div>
            )}

            {permissionsError && (
              <div className="mb-6 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
                Failed to load permissions: {permissionsError}
              </div>
            )}

            {previewDevice && can('desktop') && (
              <div className="mb-8 space-y-6">
                <DesktopPreviewPanel
                  deviceId={previewDevice.device_id}
                  deviceName={previewDeviceName}
                  onlineStatus={getOnlineStatus(previewDevice)}
                  mouseControlEnabled={can('mouse')}
                  keyboardControlEnabled={can('keyboard')}
                  clipboardControlEnabled={can('clipboard')}
                  fileTransferEnabled={can('file_transfer')}
                  onClose={() => setPreviewDeviceId(null)}
                />
                <ScreenshotHistory deviceId={previewDevice.device_id} deviceName={previewDeviceName} />
              </div>
            )}

            <DeviceGrid
              devices={devices}
              previewDeviceId={previewDeviceId}
              onPreview={handlePreview}
              canViewDesktop={can('desktop')}
              canUseCamera={can('camera')}
              canRestart={can('restart')}
              permissionsLoading={permissionsLoading}
              selectedDeviceIds={selectedDeviceIds}
              isAllSelected={isAllSelected(deviceIds)}
              bulkProgress={bulkProgress}
              isBulkRunning={isBulkRunning}
              onToggleDevice={toggleDevice}
              onToggleSelectAll={() => selectAll(deviceIds)}
              onRunBulkAction={handleRunBulkAction}
              onClearSelection={clearSelection}
            />
          </>
        )}
      </main>
    </div>
  )
}

export default function App() {
  const { user, isLoading } = useAuth()

  if (isLoading) {
    return <AuthLoadingScreen />
  }

  if (!user) {
    return <SignInForm />
  }

  return <AuthenticatedDashboard />
}
