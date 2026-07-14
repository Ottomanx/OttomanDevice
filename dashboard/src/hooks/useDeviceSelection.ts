import { useCallback, useState } from 'react'

import {
  areAllDevicesSelected,
  clearDeviceSelection,
  selectAllDeviceIds,
  toggleDeviceSelection,
} from '../utils/deviceSelection'

interface UseDeviceSelectionResult {
  selectedDeviceIds: Set<string>
  selectedCount: number
  isAllSelected: (deviceIds: readonly string[]) => boolean
  isSelected: (deviceId: string) => boolean
  toggleDevice: (deviceId: string) => void
  selectAll: (deviceIds: readonly string[]) => void
  clearSelection: () => void
}

export function useDeviceSelection(): UseDeviceSelectionResult {
  const [selectedDeviceIds, setSelectedDeviceIds] = useState<Set<string>>(() => new Set())

  const toggleDevice = useCallback((deviceId: string) => {
    setSelectedDeviceIds((current) => toggleDeviceSelection(current, deviceId))
  }, [])

  const selectAll = useCallback((deviceIds: readonly string[]) => {
    setSelectedDeviceIds((current) => {
      if (areAllDevicesSelected(deviceIds, current)) {
        return clearDeviceSelection()
      }

      return selectAllDeviceIds(deviceIds)
    })
  }, [])

  const clearSelection = useCallback(() => {
    setSelectedDeviceIds(clearDeviceSelection())
  }, [])

  const isAllSelected = useCallback(
    (deviceIds: readonly string[]) => areAllDevicesSelected(deviceIds, selectedDeviceIds),
    [selectedDeviceIds],
  )

  const isSelected = useCallback(
    (deviceId: string) => selectedDeviceIds.has(deviceId),
    [selectedDeviceIds],
  )

  return {
    selectedDeviceIds,
    selectedCount: selectedDeviceIds.size,
    isAllSelected,
    isSelected,
    toggleDevice,
    selectAll,
    clearSelection,
  }
}
