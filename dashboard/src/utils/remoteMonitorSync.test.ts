import { describe, expect, it } from 'vitest'

import {
  formatMonitorResolution,
  parseMonitorListPayload,
} from './remoteMonitorSync'

describe('remoteMonitorSync', () => {
  it('parses monitor list without exposing ids in view models', () => {
    const parsed = parseMonitorListPayload({
      selected_id: 'display-2',
      monitors: [
        {
          id: 'display-1',
          number: 1,
          width: 1920,
          height: 1080,
          is_primary: true,
          orientation: 'landscape',
        },
        {
          id: 'display-2',
          number: 2,
          width: 1280,
          height: 720,
          is_primary: false,
          orientation: 'landscape',
        },
      ],
    })

    expect(parsed.monitors).toHaveLength(2)
    expect(parsed.monitors[0]).toEqual({
      number: 1,
      width: 1920,
      height: 1080,
      isPrimary: true,
      orientation: 'landscape',
    })
    expect(parsed.monitors[0]).not.toHaveProperty('id')
    expect(parsed.selectedNumber).toBe(2)
    expect(parsed.idByNumber.get(2)).toBe('display-2')
  })

  it('formats resolution label', () => {
    expect(formatMonitorResolution(1920, 1080)).toBe('1920×1080')
  })
})
