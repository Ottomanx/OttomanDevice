import { describe, expect, it } from 'vitest'

import {
  areAllDevicesSelected,
  clearDeviceSelection,
  isDeviceSelected,
  selectAllDeviceIds,
  toggleDeviceSelection,
} from './deviceSelection'

describe('device multi-select', () => {
  it('toggles a device in and out of selection', () => {
    let selected = clearDeviceSelection()

    selected = toggleDeviceSelection(selected, 'device-a')
    expect(isDeviceSelected(selected, 'device-a')).toBe(true)

    selected = toggleDeviceSelection(selected, 'device-a')
    expect(isDeviceSelected(selected, 'device-a')).toBe(false)
  })

  it('selects all device ids', () => {
    const selected = selectAllDeviceIds(['device-a', 'device-b', 'device-c'])

    expect(selected.size).toBe(3)
    expect(areAllDevicesSelected(['device-a', 'device-b', 'device-c'], selected)).toBe(true)
  })

  it('reports select all only when every device is selected', () => {
    const partial = toggleDeviceSelection(clearDeviceSelection(), 'device-a')

    expect(areAllDevicesSelected(['device-a', 'device-b'], partial)).toBe(false)
    expect(areAllDevicesSelected(['device-a'], partial)).toBe(true)
  })
})
