import {
  formatStateTransition,
  getReconnectDelayMs,
  shouldIgnoreDuplicateConnect,
  type RemoteDesktopConnectionState,
} from './remoteDesktopLifecycle'

export interface RemoteDesktopSessionToken {
  token: string
  session_id: string
  issued_at: number
  expires_at: number
}

export interface RemoteDesktopConnectionManagerOptions {
  createWebSocket: (url: string, protocol: string) => WebSocket
  getWebSocketUrl: () => string
  subprotocol: string
  fetchSessionToken: (deviceId: string, signal: AbortSignal) => Promise<RemoteDesktopSessionToken>
  onStateChange: (state: RemoteDesktopConnectionState) => void
  onSocketOpen: (socket: WebSocket) => void
  onSocketMessage: (socket: WebSocket, data: string) => void
  onUnexpectedDisconnect: () => void
  onReconnectLimitReached?: () => void
  maxReconnectAttempts?: number
  log?: (message: string) => void
  setTimeoutFn?: (callback: () => void, delay: number) => number
  clearTimeoutFn?: (id: number) => void
}

export class RemoteDesktopConnectionManager {
  private state: RemoteDesktopConnectionState = 'IDLE'
  private socket: WebSocket | undefined = undefined
  private reconnectTimer: number | null = null
  private abortController: AbortController | null = null
  private manualClose = false
  private reconnectAttempt = 0
  private sessionId: string | null = null
  private sessionToken: RemoteDesktopSessionToken | null = null
  private deviceId: string | null = null
  private enabled = true
  private disposed = false

  private readonly options: RemoteDesktopConnectionManagerOptions
  private readonly setTimeoutFn: (callback: () => void, delay: number) => number
  private readonly clearTimeoutFn: (id: number) => void
  private readonly maxReconnectAttempts: number

  constructor(options: RemoteDesktopConnectionManagerOptions) {
    this.options = options
    this.setTimeoutFn = options.setTimeoutFn ?? ((callback, delay) => setTimeout(callback, delay) as unknown as number)
    this.clearTimeoutFn = options.clearTimeoutFn ?? ((id) => clearTimeout(id))
    this.maxReconnectAttempts = options.maxReconnectAttempts ?? Number.POSITIVE_INFINITY
  }

  get connectionState(): RemoteDesktopConnectionState {
    return this.state
  }

  get currentSessionId(): string | null {
    return this.sessionId
  }

  get currentSessionToken(): RemoteDesktopSessionToken | null {
    return this.sessionToken
  }

  get websocket(): WebSocket | undefined {
    return this.socket
  }

  setSessionId(sessionId: string | null): void {
    this.sessionId = sessionId
  }

  transition(next: RemoteDesktopConnectionState): void {
    if (this.state === next) {
      return
    }

    const message = formatStateTransition(this.state, next)
    this.options.log?.(message)
    this.state = next
    this.options.onStateChange(next)
  }

  clearReconnectTimer(): void {
    if (this.reconnectTimer !== null) {
      this.clearTimeoutFn(this.reconnectTimer)
      this.reconnectTimer = null
    }
  }

  abortPendingRequests(): void {
    if (this.abortController) {
      this.abortController.abort()
      this.abortController = null
    }
  }

  clearSession(): void {
    this.sessionToken = null
    this.sessionId = null
  }

  teardownSocket(closeCode?: number): void {
    const socket = this.socket
    this.socket = undefined

    if (socket === undefined) {
      return
    }

    socket.onopen = null
    socket.onmessage = null
    socket.onerror = null
    socket.onclose = null

    if (socket.readyState !== WebSocket.CLOSED && socket.readyState !== WebSocket.CLOSING) {
      socket.close(closeCode)
    }
  }

  prepareForSession(): void {
    this.clearReconnectTimer()
    this.abortPendingRequests()
    this.clearSession()
    this.teardownSocket()
  }

  configure(deviceId: string | null, enabled: boolean): void {
    this.deviceId = deviceId
    this.enabled = enabled
  }

  async open(): Promise<void> {
    if (this.disposed || !this.enabled || !this.deviceId) {
      return
    }

    if (shouldIgnoreDuplicateConnect(this.state)) {
      return
    }

    this.teardownSocket()
    this.clearReconnectTimer()
    this.abortPendingRequests()
    this.clearSession()
    this.manualClose = false
    this.transition('CONNECTING')

    this.abortController = new AbortController()
    const signal = this.abortController.signal

    try {
      const sessionToken = await this.options.fetchSessionToken(this.deviceId, signal)
      if (signal.aborted || this.disposed || this.manualClose) {
        this.cancelConnecting()
        return
      }

      this.sessionToken = sessionToken
      this.sessionId = sessionToken.session_id
    } catch {
      if (signal.aborted || this.disposed || this.manualClose) {
        this.cancelConnecting()
        return
      }

      this.transition('ERROR')
      this.scheduleReconnect()
      return
    }

    let socket: WebSocket
    try {
      socket = this.options.createWebSocket(
        this.options.getWebSocketUrl(),
        this.options.subprotocol,
      )
    } catch {
      this.transition('ERROR')
      this.scheduleReconnect()
      return
    }

    this.socket = socket

    socket.onopen = () => {
      if (this.socket !== socket) {
        return
      }
      this.options.onSocketOpen(socket)
    }

    socket.onmessage = (event) => {
      if (this.socket !== socket) {
        return
      }
      this.options.onSocketMessage(socket, String(event.data))
    }

    socket.onerror = () => {
      if (this.socket !== socket) {
        return
      }
      if (socket.readyState === WebSocket.CLOSED) {
        this.handleUnexpectedSocketClose()
      }
    }

    socket.onclose = () => {
      if (this.socket === socket) {
        this.socket = undefined
      }
      this.handleUnexpectedSocketClose()
    }
  }

  markAuthenticating(): void {
    this.transition('AUTHENTICATING')
  }

  markConnected(): void {
    this.transition('CONNECTED')
  }

  markStreaming(): void {
    this.reconnectAttempt = 0
    this.transition('STREAMING')
  }

  markError(): void {
    this.transition('ERROR')
  }

  close(manual: boolean): void {
    this.manualClose = manual
    this.clearReconnectTimer()
    this.abortPendingRequests()
    this.clearSession()
    this.teardownSocket(manual ? 1000 : undefined)
    this.transition('DISCONNECTED')
  }

  dropSocketAndReconnect(): void {
    this.teardownSocket()
    this.scheduleReconnect()
  }

  dispose(): void {
    this.disposed = true
    this.manualClose = true
    this.clearReconnectTimer()
    this.abortPendingRequests()
    this.clearSession()
    this.teardownSocket(1000)
    this.transition('DISCONNECTED')
  }

  shouldAutoReconnect(): boolean {
    return !this.manualClose && !this.disposed && this.enabled && Boolean(this.deviceId)
  }

  scheduleReconnect(): void {
    if (!this.shouldAutoReconnect()) {
      return
    }

    this.reconnectAttempt += 1
    if (this.reconnectAttempt > this.maxReconnectAttempts) {
      this.options.onReconnectLimitReached?.()
      return
    }

    const delay = getReconnectDelayMs(this.reconnectAttempt)
    this.clearReconnectTimer()
    this.transition('DISCONNECTED')

    this.reconnectTimer = this.setTimeoutFn(() => {
      this.reconnectTimer = null
      void this.open()
    }, delay)
  }


  private cancelConnecting(): void {
    if (this.state === 'CONNECTING') {
      this.transition('DISCONNECTED')
    }
  }

  resetReconnectAttempts(): void {
    this.reconnectAttempt = 0
  }

  private handleUnexpectedSocketClose(): void {
    if (this.manualClose || this.disposed) {
      return
    }

    if (!this.shouldAutoReconnect()) {
      if (this.state !== 'DISCONNECTED' && this.state !== 'IDLE') {
        this.transition('DISCONNECTED')
      }
      return
    }

    this.options.onUnexpectedDisconnect()
    this.scheduleReconnect()
  }
}
