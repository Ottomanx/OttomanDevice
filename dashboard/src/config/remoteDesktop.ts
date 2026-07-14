export const REMOTE_DESKTOP_HOST =
  import.meta.env.VITE_REMOTE_DESKTOP_HOST ?? '127.0.0.1'

export const REMOTE_DESKTOP_PORT = Number(
  import.meta.env.VITE_REMOTE_DESKTOP_PORT ?? '9842',
)

export const REMOTE_DESKTOP_PATH =
  import.meta.env.VITE_REMOTE_DESKTOP_PATH ?? '/remote-desktop/v1'

export const REMOTE_DESKTOP_SUBPROTOCOL =
  import.meta.env.VITE_REMOTE_DESKTOP_SUBPROTOCOL ?? 'ottoman-remote-desktop.v1'

export const REMOTE_DESKTOP_RECONNECT_BASE_MS = 1_000
export const REMOTE_DESKTOP_RECONNECT_MAX_MS = 10_000
export const REMOTE_DESKTOP_MAX_RECONNECT_ATTEMPTS = 5

export function getRemoteDesktopWebSocketUrl(): string {
  return `ws://${REMOTE_DESKTOP_HOST}:${REMOTE_DESKTOP_PORT}${REMOTE_DESKTOP_PATH}`
}
