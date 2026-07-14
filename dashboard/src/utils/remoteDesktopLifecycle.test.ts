import { describe, expect, it } from 'vitest'

import {
  REMOTE_DESKTOP_RECONNECT_DELAYS_MS,
  formatStateTransition,
  getConnectionStateLabel,
  getReconnectDelayMs,
  shouldIgnoreDuplicateConnect,
} from './remoteDesktopLifecycle'

describe('remoteDesktopLifecycle', () => {
  it('formats state transitions for logging', () => {
    expect(formatStateTransition('IDLE', 'CONNECTING')).toBe(
      '[RemoteDesktop] IDLE -> CONNECTING',
    )
  })

  it('uses reconnect backoff delays of 1s, 2s, 5s, and 10s max', () => {
    expect(REMOTE_DESKTOP_RECONNECT_DELAYS_MS).toEqual([1_000, 2_000, 5_000, 10_000])
    expect(getReconnectDelayMs(1)).toBe(1_000)
    expect(getReconnectDelayMs(2)).toBe(2_000)
    expect(getReconnectDelayMs(3)).toBe(5_000)
    expect(getReconnectDelayMs(4)).toBe(10_000)
    expect(getReconnectDelayMs(99)).toBe(10_000)
  })

  it('ignores duplicate connect requests while connecting or streaming', () => {
    expect(shouldIgnoreDuplicateConnect('CONNECTING')).toBe(true)
    expect(shouldIgnoreDuplicateConnect('STREAMING')).toBe(true)
    expect(shouldIgnoreDuplicateConnect('AUTHENTICATING')).toBe(false)
    expect(shouldIgnoreDuplicateConnect('CONNECTED')).toBe(false)
    expect(shouldIgnoreDuplicateConnect('DISCONNECTED')).toBe(false)
  })

  it('maps connection states to dashboard labels', () => {
    expect(getConnectionStateLabel('CONNECTING')).toBe('Connecting...')
    expect(getConnectionStateLabel('AUTHENTICATING')).toBe('Authenticating...')
    expect(getConnectionStateLabel('CONNECTED')).toBe('Connected')
    expect(getConnectionStateLabel('STREAMING')).toBe('Streaming')
    expect(getConnectionStateLabel('DISCONNECTED')).toBe('Disconnected')
    expect(getConnectionStateLabel('ERROR')).toBe('Error')
  })
})