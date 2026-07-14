import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  RemoteDesktopConnectionManager,
  type RemoteDesktopSessionToken,
} from './remoteDesktopConnectionManager'

const SESSION_TOKEN: RemoteDesktopSessionToken = {
  token: 'session-token',
  session_id: 'session-1',
  issued_at: 1,
  expires_at: 9_999_999_999,
}

class MockWebSocket {
  static readonly CONNECTING = 0
  static readonly OPEN = 1
  static readonly CLOSING = 2
  static readonly CLOSED = 3

  readonly url: string
  readonly protocol: string
  readyState = MockWebSocket.CONNECTING
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null
  sent: string[] = []

  constructor(url: string, protocol: string) {
    this.url = url
    this.protocol = protocol
    MockWebSocket.instances.push(this)
  }

  static instances: MockWebSocket[] = []

  send(data: string): void {
    this.sent.push(data)
  }

  close(code?: number): void {
    void code
    this.readyState = MockWebSocket.CLOSED
    this.onclose?.()
  }

  simulateOpen(): void {
    this.readyState = MockWebSocket.OPEN
    this.onopen?.()
  }

  simulateMessage(data: string): void {
    this.onmessage?.({ data })
  }

  simulateClose(): void {
    this.readyState = MockWebSocket.CLOSED
    this.onclose?.()
  }
}

describe('RemoteDesktopConnectionManager', () => {
  let manager: RemoteDesktopConnectionManager
  let states: string[]
  let logs: string[]
  let pendingTimeouts: Array<{ callback: () => void; delay: number }>
  let fetchSessionToken: ReturnType<typeof vi.fn>
  let onReconnectLimitReached: ReturnType<typeof vi.fn>

  beforeEach(() => {
    MockWebSocket.instances = []
    states = []
    logs = []
    pendingTimeouts = []
    fetchSessionToken = vi.fn(async () => SESSION_TOKEN)
    onReconnectLimitReached = vi.fn()

    manager = new RemoteDesktopConnectionManager({
      createWebSocket: (url, protocol) => new MockWebSocket(url, protocol) as unknown as WebSocket,
      getWebSocketUrl: () => 'ws://127.0.0.1:9842/remote-desktop/v1',
      subprotocol: 'ottoman-remote-desktop.v1',
      fetchSessionToken,
      onStateChange: (state) => {
        states.push(state)
      },
      onSocketOpen: () => {
        const socket = MockWebSocket.instances.at(-1)
        socket?.send('HELLO')
      },
      onSocketMessage: () => {},
      onUnexpectedDisconnect: () => {},
      onReconnectLimitReached,
      maxReconnectAttempts: 4,
      log: (message) => {
        logs.push(message)
      },
      setTimeoutFn: (callback: () => void, delay: number) => {
        pendingTimeouts.push({ callback, delay })
        return pendingTimeouts.length
      },
      clearTimeoutFn: () => {},
    })

    manager.configure('device-1', true)
  })

  afterEach(() => {
    manager.dispose()
  })

  it('opens a websocket session', async () => {
    await manager.open()

    expect(fetchSessionToken).toHaveBeenCalledOnce()
    expect(MockWebSocket.instances).toHaveLength(1)
    expect(manager.connectionState).toBe('CONNECTING')
    expect(states).toContain('CONNECTING')
    expect(logs).toContain('[RemoteDesktop] IDLE -> CONNECTING')
  })

  it('closes manually without scheduling reconnect', async () => {
    await manager.open()
    const socket = MockWebSocket.instances[0]
    socket.simulateOpen()

    manager.close(true)

    expect(manager.connectionState).toBe('DISCONNECTED')
    expect(manager.websocket).toBeUndefined()
    expect(pendingTimeouts).toHaveLength(0)

    await manager.open()
    expect(fetchSessionToken).toHaveBeenCalledTimes(2)
  })

  it('reopens after manual close', async () => {
    await manager.open()
    manager.close(true)

    await manager.open()

    expect(MockWebSocket.instances).toHaveLength(2)
    expect(manager.connectionState).toBe('CONNECTING')
  })

  it('ignores duplicate connect requests while connecting', async () => {
    const openPromise = manager.open()
    await manager.open()
    await openPromise

    expect(fetchSessionToken).toHaveBeenCalledOnce()
    expect(MockWebSocket.instances).toHaveLength(1)
  })

  it('ignores duplicate connect requests while streaming', async () => {
    await manager.open()
    manager.markStreaming()

    await manager.open()

    expect(fetchSessionToken).toHaveBeenCalledOnce()
    expect(MockWebSocket.instances).toHaveLength(1)
  })

  it('schedules reconnect after unexpected disconnect', async () => {
    await manager.open()
    const socket = MockWebSocket.instances[0]
    socket.simulateOpen()
    socket.simulateClose()

    expect(states).toContain('DISCONNECTED')
    expect(pendingTimeouts).toHaveLength(1)
    expect(pendingTimeouts[0]?.delay).toBe(1_000)
  })

  it('uses reconnect backoff delays', async () => {
    await manager.open()
    MockWebSocket.instances[0].simulateClose()

    expect(pendingTimeouts[0]?.delay).toBe(1_000)

    pendingTimeouts[0]?.callback()
    await Promise.resolve()
    MockWebSocket.instances[1].simulateClose()

    expect(pendingTimeouts[1]?.delay).toBe(2_000)

    pendingTimeouts[1]?.callback()
    await Promise.resolve()
    MockWebSocket.instances[2].simulateClose()

    expect(pendingTimeouts[2]?.delay).toBe(5_000)

    pendingTimeouts[2]?.callback()
    await Promise.resolve()
    MockWebSocket.instances[3].simulateClose()

    expect(pendingTimeouts[3]?.delay).toBe(10_000)
  })

  it('does not reconnect after manual close', async () => {
    await manager.open()
    const socket = MockWebSocket.instances[0]
    socket.simulateOpen()

    manager.close(true)
    socket.simulateClose()

    expect(pendingTimeouts).toHaveLength(0)
    expect(manager.connectionState).toBe('DISCONNECTED')
  })

  it('cleans up timers, websocket, and abort controller on dispose', async () => {
    const abortSpy = vi.spyOn(AbortController.prototype, 'abort')

    const openPromise = manager.open()
    manager.dispose()
    await openPromise

    expect(manager.connectionState).toBe('DISCONNECTED')
    expect(manager.websocket).toBeUndefined()
    expect(abortSpy).toHaveBeenCalled()
    expect(pendingTimeouts).toHaveLength(0)

    abortSpy.mockRestore()
  })

  it('aborts pending session fetch before creating a new session', async () => {
    fetchSessionToken
      .mockImplementationOnce((_deviceId, signal) =>
        new Promise<RemoteDesktopSessionToken>((_resolve, reject) => {
          signal.addEventListener('abort', () => {
            reject(new DOMException('Aborted', 'AbortError'))
          })
        }),
      )
      .mockResolvedValue(SESSION_TOKEN)

    const firstOpen = manager.open()
    await Promise.resolve()
    manager.close(true)
    await manager.open()
    await firstOpen

    expect(fetchSessionToken).toHaveBeenCalledTimes(2)
  })

  it('stops reconnecting after the configured attempt limit', async () => {
    await manager.open()
    MockWebSocket.instances[0].simulateClose()

    for (let attempt = 0; attempt < 4; attempt += 1) {
      pendingTimeouts.at(-1)?.callback()
      await Promise.resolve()
      MockWebSocket.instances.at(-1)?.simulateClose()
    }

    expect(onReconnectLimitReached).toHaveBeenCalledOnce()
  })
})