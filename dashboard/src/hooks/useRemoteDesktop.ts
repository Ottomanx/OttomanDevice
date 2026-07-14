import { useCallback, useEffect, useRef, useState } from 'react'

import {
  REMOTE_DESKTOP_MAX_RECONNECT_ATTEMPTS,
  REMOTE_DESKTOP_SUBPROTOCOL,
  getRemoteDesktopWebSocketUrl,
} from '../config/remoteDesktop'
import {
  isSessionTokenExpired,
  requestRemoteDesktopSessionToken,
} from '../services/remoteDesktopSession'
import { MouseMoveThrottler } from '../utils/remoteMouseControl'
import {
  assembleDownloadChunks,
  createTransferId,
  readFileInChunks,
  triggerBrowserDownload,
  type FileTransferProgress,
} from '../utils/fileTransfer'
import { useRemoteDesktopStreamMetrics } from './useRemoteDesktopStreamMetrics'
import { RemoteDesktopConnectionManager } from '../utils/remoteDesktopConnectionManager'
import {
  getConnectionStateLabel,
  type RemoteDesktopConnectionState,
} from '../utils/remoteDesktopLifecycle'
import {
  framePayloadToObjectUrl,
  revokeObjectUrl,
  type StreamHealth,
  type StreamPerformanceSnapshot,
} from '../utils/remoteDesktopStreamMetrics'

export type { RemoteDesktopConnectionState }

/** @deprecated Use RemoteDesktopConnectionState */
export type ConnectionMode =
  | 'connecting'
  | 'live'
  | 'reconnecting'
  | 'offline'
  | 'fallback'

export interface ActiveSessionInfo {
  userId: string | null
  controllerName: string | null
  sessionId: string | null
  startedAt: number | null
}

interface RemoteDesktopMessage {
  type: string
  session_id?: string | null
  seq?: number | null
  ts?: number
  payload?: Record<string, unknown>
}

interface UseRemoteDesktopResult {
  connectionState: RemoteDesktopConnectionState
  connectionStateLabel: string
  /** @deprecated Prefer connectionState */
  connectionMode: ConnectionMode
  frameDataUrl: string | null
  isLoading: boolean
  lastFrameTimestamp: Date | null
  useFallback: boolean
  remoteControlActive: boolean
  sendMouseMove: (x: number, y: number) => void
  sendMouseClick: (button: 'left' | 'right') => void
  sendMouseDoubleClick: () => void
  sendMouseScroll: (delta: number) => void
  sendKeyDown: (key: string) => void
  sendKeyUp: (key: string) => void
  sendTextInput: (text: string) => void
  activeSessionInfo: ActiveSessionInfo | null
  isControlledByOther: boolean
  releaseSession: () => void
  remoteClipboardText: string | null
  copyToRemote: () => Promise<void>
  copyFromRemote: () => Promise<void>
  fileTransferProgress: FileTransferProgress | null
  uploadFile: (relativePath: string, file: File) => Promise<void>
  downloadFile: (relativePath: string) => Promise<void>
  cancelFileTransfer: (transferId: string) => void
  streamPerformance: StreamPerformanceSnapshot
  streamHealth: StreamHealth
  isFrozenFrame: boolean
  adaptiveDisplayScale: number
  recordFrameRendered: (displayStartedAtMs: number) => void
  showStreamDebugTimings: boolean
}

interface UseRemoteDesktopOptions {
  enabled?: boolean
}

function buildOutboundMessage(
  type: string,
  sessionId: string | null,
  seq: number,
  payload?: Record<string, unknown>,
): string {
  return JSON.stringify({
    type,
    session_id: sessionId,
    seq,
    ts: Date.now(),
    payload: payload ?? {},
  })
}

function parseFrameTimestamp(payload: Record<string, unknown>): Date | null {
  const timestamp = payload.timestamp
  if (typeof timestamp === 'string') {
    const parsed = new Date(timestamp)
    if (!Number.isNaN(parsed.getTime())) {
      return parsed
    }
  }
  return new Date()
}

function parseSessionInfo(payload: Record<string, unknown>): ActiveSessionInfo | null {
  if (payload.active !== true) {
    return null
  }

  return {
    userId: typeof payload.user_id === 'string' ? payload.user_id : null,
    controllerName:
      typeof payload.controller_name === 'string' ? payload.controller_name : null,
    sessionId: typeof payload.session_id === 'string' ? payload.session_id : null,
    startedAt: typeof payload.started_at === 'number' ? payload.started_at : null,
  }
}

function mapConnectionStateToMode(
  state: RemoteDesktopConnectionState,
  useFallback: boolean,
  enabled: boolean,
  deviceId: string | null,
): ConnectionMode {
  if (!enabled || !deviceId) {
    return 'offline'
  }

  if (useFallback) {
    return 'fallback'
  }

  switch (state) {
    case 'STREAMING':
    case 'CONNECTED':
      return 'live'
    case 'CONNECTING':
    case 'AUTHENTICATING':
      return 'connecting'
    case 'DISCONNECTED':
      return 'reconnecting'
    case 'ERROR':
    case 'IDLE':
    default:
      return 'offline'
  }
}

function initialConnectionState(
  enabled: boolean,
  deviceId: string | null,
): RemoteDesktopConnectionState {
  return enabled && deviceId ? 'CONNECTING' : 'DISCONNECTED'
}

export function useRemoteDesktop(
  deviceId: string | null,
  options: UseRemoteDesktopOptions = {},
): UseRemoteDesktopResult {
  const enabled = options.enabled ?? true

  const [connectionState, setConnectionState] = useState<RemoteDesktopConnectionState>(
    () => initialConnectionState(enabled, deviceId),
  )
  const [frameDataUrl, setFrameDataUrl] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(() => Boolean(enabled && deviceId))
  const [lastFrameTimestamp, setLastFrameTimestamp] = useState<Date | null>(null)
  const [useFallback, setUseFallback] = useState(() => !enabled)
  const [activeSessionInfo, setActiveSessionInfo] = useState<ActiveSessionInfo | null>(null)
  const [isControlledByOther, setIsControlledByOther] = useState(false)
  const [remoteClipboardText, setRemoteClipboardText] = useState<string | null>(null)
  const [fileTransferProgress, setFileTransferProgress] = useState<FileTransferProgress | null>(
    null,
  )

  const managerRef = useRef<RemoteDesktopConnectionManager | null>(null)
  const deviceIdRef = useRef(deviceId)
  const hasAuthenticatedRef = useRef(false)
  const clipboardRequestRef = useRef<((text: string) => void) | null>(null)
  const activeTransferIdRef = useRef<string | null>(null)
  const downloadChunksRef = useRef<Map<string, Map<number, string>>>(new Map())
  const downloadPathsRef = useRef<Map<string, string>>(new Map())
  const outboundSeqRef = useRef(0)
  const frameObjectUrlRef = useRef<string | null>(null)
  const [reconnectCount, setReconnectCount] = useState(0)
  const recordIncomingFrameRef = useRef<(payload: Record<string, unknown>) => boolean>(() => true)
  const mouseMoveThrottlerRef = useRef(new MouseMoveThrottler())

  deviceIdRef.current = deviceId

  const sendMessage = useCallback((type: string, payload?: Record<string, unknown>) => {
    const manager = managerRef.current
    const socket = manager?.websocket
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      return
    }

    outboundSeqRef.current += 1
    socket.send(
      buildOutboundMessage(
        type,
        manager.currentSessionId,
        outboundSeqRef.current,
        payload,
      ),
    )
  }, [])

  const resetTransferState = useCallback(() => {
    clipboardRequestRef.current = null
    activeTransferIdRef.current = null
    downloadChunksRef.current.clear()
    downloadPathsRef.current.clear()
    setFileTransferProgress(null)
  }, [])

  const enterFallback = useCallback(() => {
    const manager = managerRef.current
    manager?.close(true)
    setUseFallback(true)
    setIsLoading(false)
    manager?.markError()
  }, [])

  const remoteControlActive =
    connectionState === 'STREAMING' && !useFallback && frameDataUrl !== null

  const sendMouseMove = useCallback(
    (x: number, y: number) => {
      if (!remoteControlActive) {
        return
      }

      const point = {
        x: Math.max(0, Math.min(1, x)),
        y: Math.max(0, Math.min(1, y)),
      }

      if (!mouseMoveThrottlerRef.current.shouldSend(point)) {
        return
      }

      sendMessage('MOUSE_MOVE', point)
    },
    [remoteControlActive, sendMessage],
  )

  const sendMouseClick = useCallback(
    (button: 'left' | 'right') => {
      if (!remoteControlActive) {
        return
      }
      sendMessage('MOUSE_CLICK', { button })
    },
    [remoteControlActive, sendMessage],
  )

  const sendMouseDoubleClick = useCallback(() => {
    if (!remoteControlActive) {
      return
    }
    sendMessage('MOUSE_DOUBLE_CLICK')
  }, [remoteControlActive, sendMessage])

  const sendMouseScroll = useCallback(
    (delta: number) => {
      if (!remoteControlActive || delta === 0) {
        return
      }
      sendMessage('MOUSE_SCROLL', { delta })
    },
    [remoteControlActive, sendMessage],
  )

  const sendKeyDown = useCallback(
    (key: string) => {
      if (!remoteControlActive) {
        return
      }
      sendMessage('KEY_DOWN', { key })
    },
    [remoteControlActive, sendMessage],
  )

  const sendKeyUp = useCallback(
    (key: string) => {
      if (!remoteControlActive) {
        return
      }
      sendMessage('KEY_UP', { key })
    },
    [remoteControlActive, sendMessage],
  )

  const sendTextInput = useCallback(
    (text: string) => {
      if (!remoteControlActive) {
        return
      }
      sendMessage('TEXT_INPUT', { text })
    },
    [remoteControlActive, sendMessage],
  )

  const requestRemoteClipboard = useCallback((): Promise<string> => {
    return new Promise((resolve, reject) => {
      if (!remoteControlActive) {
        reject(new Error('Remote desktop is not active'))
        return
      }

      clipboardRequestRef.current = resolve
      sendMessage('CLIPBOARD_GET')

      window.setTimeout(() => {
        if (clipboardRequestRef.current === resolve) {
          clipboardRequestRef.current = null
          reject(new Error('Clipboard request timed out'))
        }
      }, 5000)
    })
  }, [remoteControlActive, sendMessage])

  const copyToRemote = useCallback(async () => {
    if (!remoteControlActive) {
      return
    }

    const text = await navigator.clipboard.readText()
    sendMessage('CLIPBOARD_SET', { text })
  }, [remoteControlActive, sendMessage])

  const copyFromRemote = useCallback(async () => {
    const text = await requestRemoteClipboard()
    await navigator.clipboard.writeText(text)
    setRemoteClipboardText(text)
  }, [requestRemoteClipboard])

  const cancelFileTransfer = useCallback(
    (transferId: string) => {
      if (activeTransferIdRef.current === transferId) {
        activeTransferIdRef.current = null
      }
      sendMessage('FILE_UPLOAD', { transfer_id: transferId, cancel: true })
      sendMessage('FILE_DOWNLOAD', { transfer_id: transferId, cancel: true })
      downloadChunksRef.current.delete(transferId)
      downloadPathsRef.current.delete(transferId)
      setFileTransferProgress((current) =>
        current?.transferId === transferId
          ? { ...current, status: 'cancelled' }
          : current,
      )
    },
    [sendMessage],
  )

  const uploadFile = useCallback(
    async (relativePath: string, file: File) => {
      if (!remoteControlActive) {
        throw new Error('Remote desktop is not active')
      }

      const transferId = createTransferId()
      activeTransferIdRef.current = transferId
      setFileTransferProgress({
        transferId,
        direction: 'upload',
        transferred: 0,
        total: file.size,
        path: relativePath,
        status: 'active',
      })

      sendMessage('FILE_UPLOAD', {
        transfer_id: transferId,
        path: relativePath,
        size: file.size,
      })

      await readFileInChunks(file, async (chunk) => {
        if (activeTransferIdRef.current !== transferId) {
          return
        }
        sendMessage('FILE_UPLOAD', { transfer_id: transferId, chunk })
      })
    },
    [remoteControlActive, sendMessage],
  )

  const downloadFile = useCallback(
    async (relativePath: string) => {
      if (!remoteControlActive) {
        throw new Error('Remote desktop is not active')
      }

      const transferId = createTransferId()
      activeTransferIdRef.current = transferId
      downloadChunksRef.current.set(transferId, new Map())
      downloadPathsRef.current.set(transferId, relativePath)
      setFileTransferProgress({
        transferId,
        direction: 'download',
        transferred: 0,
        total: 0,
        path: relativePath,
        status: 'active',
      })

      sendMessage('FILE_DOWNLOAD', {
        transfer_id: transferId,
        path: relativePath,
      })
    },
    [remoteControlActive, sendMessage],
  )

  const handleUnexpectedDisconnect = useCallback(() => {
    setReconnectCount((count) => count + 1)
    hasAuthenticatedRef.current = false
    setActiveSessionInfo(null)
    setIsControlledByOther(false)
    resetTransferState()
    setRemoteClipboardText(null)
    setIsLoading(true)
  }, [resetTransferState])

  const handleThrottleStream = useCallback(
    (throttle: boolean) => {
      if (!hasAuthenticatedRef.current) {
        return
      }

      sendMessage(throttle ? 'STOP_STREAM' : 'START_STREAM')
    },
    [sendMessage],
  )

  const isStreaming = connectionState === 'STREAMING'
  const {
    performance: streamPerformance,
    isFrozenFrame,
    adaptiveState,
    recordIncomingFrame,
    recordDecodeRenderMs,
    reset: resetStreamMetrics,
  } = useRemoteDesktopStreamMetrics({
    connectionState,
    isStreaming,
    reconnectCount,
    onThrottleStream: handleThrottleStream,
  })

  recordIncomingFrameRef.current = recordIncomingFrame

  const recordFrameRendered = useCallback(
    (displayStartedAtMs: number) => {
      recordDecodeRenderMs(Date.now() - displayStartedAtMs)
    },
    [recordDecodeRenderMs],
  )

  const releaseSession = useCallback(() => {
    const manager = managerRef.current
    if (hasAuthenticatedRef.current && manager?.websocket?.readyState === WebSocket.OPEN) {
      sendMessage('SESSION_RELEASE')
    }

    hasAuthenticatedRef.current = false
    setActiveSessionInfo(null)
    setIsControlledByOther(false)
    revokeObjectUrl(frameObjectUrlRef.current)
    frameObjectUrlRef.current = null
    setFrameDataUrl(null)
    resetStreamMetrics()
    manager?.close(true)
    setIsLoading(false)
  }, [resetStreamMetrics, sendMessage])

  const handleMessage = useCallback(
    (raw: string) => {
      const manager = managerRef.current
      if (!manager) {
        return
      }

      let message: RemoteDesktopMessage
      try {
        message = JSON.parse(raw) as RemoteDesktopMessage
      } catch {
        return
      }

      const payload = message.payload ?? {}

      if (message.session_id) {
        manager.setSessionId(message.session_id)
      }

      switch (message.type) {
        case 'HELLO': {
          if (
            typeof payload.device_id === 'string' &&
            payload.device_id !== deviceIdRef.current
          ) {
            manager.dropSocketAndReconnect()
            break
          }

          if (typeof payload.session_id === 'string') {
            manager.setSessionId(payload.session_id)
          }

          const sessionToken = manager.currentSessionToken
          if (!sessionToken || isSessionTokenExpired(sessionToken.expires_at)) {
            manager.teardownSocket()
            manager.resetReconnectAttempts()
            void manager.open()
            break
          }

          manager.markAuthenticating()
          sendMessage('AUTH', { token: sessionToken.token })
          break
        }
        case 'AUTH': {
          if (payload.authenticated === true) {
            hasAuthenticatedRef.current = true
            manager.markConnected()
            sendMessage('START_STREAM')
          } else {
            manager.dropSocketAndReconnect()
          }
          break
        }
        case 'SESSION_INFO': {
          const info = parseSessionInfo(payload)
          if (info) {
            setActiveSessionInfo(info)
            setIsControlledByOther(!hasAuthenticatedRef.current)
          } else {
            setActiveSessionInfo(null)
            setIsControlledByOther(false)
          }
          break
        }
        case 'SESSION_RELEASE': {
          setActiveSessionInfo(null)
          setIsControlledByOther(false)
          break
        }
        case 'CLIPBOARD_GET': {
          const text = typeof payload.text === 'string' ? payload.text : ''
          if (clipboardRequestRef.current) {
            clipboardRequestRef.current(text)
            clipboardRequestRef.current = null
          }
          setRemoteClipboardText(text)
          break
        }
        case 'CLIPBOARD_CHANGED': {
          const text = typeof payload.text === 'string' ? payload.text : ''
          setRemoteClipboardText(text)
          break
        }
        case 'FILE_PROGRESS': {
          const transferId =
            typeof payload.transfer_id === 'string' ? payload.transfer_id : null
          if (!transferId) {
            break
          }
          const transferred =
            typeof payload.transferred === 'number' ? payload.transferred : 0
          const total = typeof payload.total === 'number' ? payload.total : 0
          const direction = payload.direction === 'download' ? 'download' : 'upload'
          setFileTransferProgress((current) => {
            if (current?.transferId !== transferId) {
              return {
                transferId,
                direction,
                transferred,
                total,
                path: downloadPathsRef.current.get(transferId) ?? '',
                status: 'active',
              }
            }
            return {
              ...current,
              transferred,
              total,
              direction,
              status: 'active',
            }
          })
          break
        }
        case 'FILE_COMPLETE': {
          const transferId =
            typeof payload.transfer_id === 'string' ? payload.transfer_id : null
          if (!transferId) {
            break
          }
          const path = typeof payload.path === 'string' ? payload.path : ''
          const size = typeof payload.size === 'number' ? payload.size : 0
          if (activeTransferIdRef.current === transferId) {
            activeTransferIdRef.current = null
          }
          setFileTransferProgress({
            transferId,
            direction:
              downloadPathsRef.current.has(transferId) &&
              downloadChunksRef.current.has(transferId)
                ? 'download'
                : 'upload',
            transferred: size,
            total: size,
            path,
            status: 'complete',
          })
          downloadChunksRef.current.delete(transferId)
          downloadPathsRef.current.delete(transferId)
          break
        }
        case 'FILE_ERROR': {
          const transferId =
            typeof payload.transfer_id === 'string' ? payload.transfer_id : null
          const code = typeof payload.code === 'string' ? payload.code : 'ERROR'
          const errorMessage =
            typeof payload.message === 'string' ? payload.message : 'Transfer failed'
          if (transferId && activeTransferIdRef.current === transferId) {
            activeTransferIdRef.current = null
          }
          if (transferId) {
            downloadChunksRef.current.delete(transferId)
            downloadPathsRef.current.delete(transferId)
          }
          setFileTransferProgress((current) =>
            transferId && current?.transferId === transferId
              ? {
                  ...current,
                  status: code === 'CANCELLED' ? 'cancelled' : 'error',
                  errorMessage,
                }
              : current,
          )
          break
        }
        case 'FILE_DOWNLOAD': {
          const transferId =
            typeof payload.transfer_id === 'string' ? payload.transfer_id : null
          const chunk = typeof payload.chunk === 'string' ? payload.chunk : null
          const offset = typeof payload.offset === 'number' ? payload.offset : 0
          const isFinal = payload.final === true
          if (!transferId || !chunk) {
            break
          }

          const chunks = downloadChunksRef.current.get(transferId) ?? new Map()
          chunks.set(offset, chunk)
          downloadChunksRef.current.set(transferId, chunks)

          if (!isFinal) {
            break
          }

          const relativePath = downloadPathsRef.current.get(transferId) ?? 'download'
          const data = assembleDownloadChunks(chunks)
          const filename = relativePath.split('/').pop() || 'download'
          triggerBrowserDownload(filename, data)
          break
        }
        case 'START_STREAM': {
          if (payload.streaming === true) {
            manager.markConnected()
          }
          break
        }
        case 'FRAME': {
          const shouldDisplay = recordIncomingFrameRef.current(payload)
          if (!shouldDisplay) {
            break
          }

          const frameObject = framePayloadToObjectUrl(payload)
          if (!frameObject) {
            break
          }

          revokeObjectUrl(frameObjectUrlRef.current)
          frameObjectUrlRef.current = frameObject.objectUrl
          setFrameDataUrl(frameObject.objectUrl)
          setLastFrameTimestamp(parseFrameTimestamp(payload))
          setIsLoading(false)
          manager.markStreaming()
          break
        }
        case 'PING': {
          sendMessage('PONG')
          break
        }
        case 'ERROR': {
          const code = payload.code
          if (code === 'TOKEN_EXPIRED' || code === 'TOKEN_REUSED') {
            manager.teardownSocket()
            manager.resetReconnectAttempts()
            void manager.open()
          } else if (code === 'AUTH_FAILED' || code === 'SESSION_BUSY') {
            if (code === 'SESSION_BUSY') {
              enterFallback()
            } else {
              manager.dropSocketAndReconnect()
            }
          } else if (code === 'TIMEOUT') {
            manager.dropSocketAndReconnect()
          }
          break
        }
        default:
          break
      }
    },
    [enterFallback, sendMessage],
  )

  const enterFallbackRef = useRef(enterFallback)
  const handleMessageRef = useRef(handleMessage)
  const handleUnexpectedDisconnectRef = useRef(handleUnexpectedDisconnect)
  const resetStreamMetricsRef = useRef(resetStreamMetrics)
  const resetTransferStateRef = useRef(resetTransferState)
  const sendMessageRef = useRef(sendMessage)

  enterFallbackRef.current = enterFallback
  handleMessageRef.current = handleMessage
  handleUnexpectedDisconnectRef.current = handleUnexpectedDisconnect
  resetStreamMetricsRef.current = resetStreamMetrics
  resetTransferStateRef.current = resetTransferState
  sendMessageRef.current = sendMessage

  useEffect(() => {
    const manager = new RemoteDesktopConnectionManager({
      createWebSocket: (url, protocol) => new WebSocket(url, protocol),
      getWebSocketUrl: getRemoteDesktopWebSocketUrl,
      subprotocol: REMOTE_DESKTOP_SUBPROTOCOL,
      fetchSessionToken: async (targetDeviceId, signal) => {
        if (signal.aborted) {
          throw new DOMException('Aborted', 'AbortError')
        }
        return requestRemoteDesktopSessionToken(targetDeviceId)
      },
      onStateChange: (state) => {
        setConnectionState(state)
        if (state === 'CONNECTING') {
          setIsLoading(true)
        }
      },
      onSocketOpen: () => {
        outboundSeqRef.current = 0
        hasAuthenticatedRef.current = false
        setActiveSessionInfo(null)
        setIsControlledByOther(false)
        setRemoteClipboardText(null)
        resetTransferStateRef.current()
        resetStreamMetricsRef.current()
        mouseMoveThrottlerRef.current.reset()
        setReconnectCount(0)
        revokeObjectUrl(frameObjectUrlRef.current)
        frameObjectUrlRef.current = null
        setFrameDataUrl(null)
        setUseFallback(false)
        sendMessageRef.current('HELLO')
      },
      onSocketMessage: (_socket, data) => {
        handleMessageRef.current(data)
      },
      onUnexpectedDisconnect: () => handleUnexpectedDisconnectRef.current(),
      onReconnectLimitReached: () => enterFallbackRef.current(),
      maxReconnectAttempts: REMOTE_DESKTOP_MAX_RECONNECT_ATTEMPTS,
      log: (message) => {
        console.info(message)
      },
      setTimeoutFn: (callback: () => void, delay: number) => window.setTimeout(callback, delay),
      clearTimeoutFn: (id: number) => window.clearTimeout(id),
    })

    managerRef.current = manager
    manager.configure(deviceId, enabled)

    if (!deviceId || !enabled) {
      manager.dispose()
      setUseFallback(true)
      revokeObjectUrl(frameObjectUrlRef.current)
      frameObjectUrlRef.current = null
      setFrameDataUrl(null)
      setIsLoading(false)
      setLastFrameTimestamp(null)
      resetStreamMetricsRef.current()
      return () => {
        revokeObjectUrl(frameObjectUrlRef.current)
        frameObjectUrlRef.current = null
        manager.dispose()
        managerRef.current = null
      }
    }

    manager.resetReconnectAttempts()
    setUseFallback(false)
    setFrameDataUrl(null)
    setLastFrameTimestamp(null)
    setIsLoading(true)
    void manager.open()

    return () => {
      revokeObjectUrl(frameObjectUrlRef.current)
      frameObjectUrlRef.current = null
      resetStreamMetrics()
      manager.dispose()
      managerRef.current = null
    }
  }, [deviceId, enabled])

  const connectionMode = mapConnectionStateToMode(
    connectionState,
    useFallback,
    enabled,
    deviceId,
  )

  return {
    connectionState,
    connectionStateLabel: getConnectionStateLabel(connectionState),
    connectionMode,
    frameDataUrl,
    isLoading,
    lastFrameTimestamp,
    useFallback,
    remoteControlActive,
    sendMouseMove,
    sendMouseClick,
    sendMouseDoubleClick,
    sendMouseScroll,
    sendKeyDown,
    sendKeyUp,
    sendTextInput,
    activeSessionInfo,
    isControlledByOther,
    releaseSession,
    remoteClipboardText,
    copyToRemote,
    copyFromRemote,
    fileTransferProgress,
    uploadFile,
    downloadFile,
    cancelFileTransfer,
    streamPerformance,
    streamHealth: streamPerformance.health,
    isFrozenFrame,
    adaptiveDisplayScale: adaptiveState.displayScale,
    recordFrameRendered,
    showStreamDebugTimings: import.meta.env.DEV,
  }
}
