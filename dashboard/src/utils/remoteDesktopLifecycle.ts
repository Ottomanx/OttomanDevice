export type RemoteDesktopConnectionState =
  | 'IDLE'
  | 'CONNECTING'
  | 'AUTHENTICATING'
  | 'CONNECTED'
  | 'STREAMING'
  | 'DISCONNECTED'
  | 'ERROR'

export const REMOTE_DESKTOP_RECONNECT_DELAYS_MS = [1_000, 2_000, 5_000, 10_000] as const

export function formatStateTransition(
  from: RemoteDesktopConnectionState,
  to: RemoteDesktopConnectionState,
): string {
  return `[RemoteDesktop] ${from} -> ${to}`
}

export function getReconnectDelayMs(attempt: number): number {
  if (attempt <= 0) {
    return REMOTE_DESKTOP_RECONNECT_DELAYS_MS[0]
  }

  const index = Math.min(attempt - 1, REMOTE_DESKTOP_RECONNECT_DELAYS_MS.length - 1)
  return REMOTE_DESKTOP_RECONNECT_DELAYS_MS[index]
}

export function shouldIgnoreDuplicateConnect(
  state: RemoteDesktopConnectionState,
): boolean {
  return state === 'CONNECTING' || state === 'STREAMING'
}

export function getConnectionStateLabel(
  state: RemoteDesktopConnectionState,
): string {
  switch (state) {
    case 'CONNECTING':
      return 'Connecting...'
    case 'AUTHENTICATING':
      return 'Authenticating...'
    case 'CONNECTED':
      return 'Connected'
    case 'STREAMING':
      return 'Streaming'
    case 'DISCONNECTED':
      return 'Disconnected'
    case 'ERROR':
      return 'Error'
    case 'IDLE':
    default:
      return 'Disconnected'
  }
}

export function destroyWebSocket(socket: WebSocket | undefined): void {
  if (socket === undefined) {
    return
  }

  socket.onopen = null
  socket.onmessage = null
  socket.onerror = null
  socket.onclose = null

  if (socket.readyState !== WebSocket.CLOSED && socket.readyState !== WebSocket.CLOSING) {
    socket.close()
  }
}
