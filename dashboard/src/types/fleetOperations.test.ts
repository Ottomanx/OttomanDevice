import { describe, expect, it } from 'vitest'

import type { DeviceCommandType } from '../types/device'
import { bulkActionToCommand } from '../types/fleetOperations'

describe('bulk action command mapping', () => {
  it('maps bulk screenshot to SCREENSHOT', () => {
    expect(bulkActionToCommand('screenshot')).toBe('SCREENSHOT')
  })

  it('maps bulk restart to HEARTBEAT', () => {
    expect(bulkActionToCommand('restart')).toBe('HEARTBEAT')
  })

  it('maps ping and camera test to existing command types', () => {
    const expected: Record<string, DeviceCommandType> = {
      ping: 'PING',
      camera_test: 'CAMERA_TEST',
    }

    expect(bulkActionToCommand('ping')).toBe(expected.ping)
    expect(bulkActionToCommand('camera_test')).toBe(expected.camera_test)
  })
})
