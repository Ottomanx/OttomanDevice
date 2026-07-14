import { useCallback, useEffect, useRef, useState } from 'react'

import { FileTransferPanel } from './FileTransferPanel'
import { MonitorSelectorStrip } from './MonitorSelectorStrip'
import { StreamPerformanceOverlay } from './StreamPerformanceOverlay'
import { useDesktopPreview } from '../hooks/useDesktopPreview'
import { useRemoteDesktop } from '../hooks/useRemoteDesktop'
import type { RemoteDesktopConnectionState } from '../utils/remoteDesktopLifecycle'
import { getStreamHealthIndicatorClass } from '../utils/remoteDesktopStreamMetrics'
import type { OnlineStatus } from '../types/device'
import { isAllowedKeyCode, shouldSendTextInput } from '../utils/keyboardInput'
import { getNormalizedImageCoordinates } from '../utils/mouseCoordinates'
import { wheelDeltaToScrollDelta } from '../utils/remoteMouseControl'

interface DesktopPreviewPanelProps {
  deviceId: string
  deviceName: string
  onlineStatus: OnlineStatus
  mouseControlEnabled: boolean
  keyboardControlEnabled: boolean
  clipboardControlEnabled: boolean
  fileTransferEnabled: boolean
  onClose: () => void
}

function connectionIndicatorClass(
  state: RemoteDesktopConnectionState,
  useFallback: boolean,
): string {
  if (useFallback) {
    return 'bg-indigo-500/15 text-indigo-300 ring-indigo-500/30'
  }

  switch (state) {
    case 'STREAMING':
    case 'CONNECTED':
      return 'bg-emerald-500/15 text-emerald-400 ring-emerald-500/30'
    case 'CONNECTING':
    case 'AUTHENTICATING':
      return 'bg-amber-500/15 text-amber-300 ring-amber-500/30'
    case 'ERROR':
      return 'bg-rose-500/15 text-rose-300 ring-rose-500/30'
    case 'DISCONNECTED':
    case 'IDLE':
    default:
      return 'bg-slate-500/15 text-slate-400 ring-slate-500/30'
  }
}

function connectionDotClass(
  state: RemoteDesktopConnectionState,
  useFallback: boolean,
): string {
  if (useFallback) {
    return 'bg-indigo-400'
  }

  switch (state) {
    case 'STREAMING':
    case 'CONNECTED':
      return 'animate-pulse bg-emerald-400'
    case 'CONNECTING':
    case 'AUTHENTICATING':
      return 'animate-pulse bg-amber-400'
    case 'ERROR':
      return 'bg-rose-400'
    case 'DISCONNECTED':
    case 'IDLE':
    default:
      return 'bg-slate-400'
  }
}

function formatSessionDuration(startedAtMs: number): string {
  const seconds = Math.max(0, Math.floor((Date.now() - startedAtMs) / 1000))
  const minutes = Math.floor(seconds / 60)
  const remainingSeconds = seconds % 60
  if (minutes > 0) {
    return `${minutes}m ${remainingSeconds}s`
  }
  return `${remainingSeconds}s`
}

export function DesktopPreviewPanel({
  deviceId,
  deviceName,
  onlineStatus,
  mouseControlEnabled,
  keyboardControlEnabled,
  clipboardControlEnabled,
  fileTransferEnabled,
  onClose,
}: DesktopPreviewPanelProps) {
  const isOffline = onlineStatus === 'offline'
  const viewerRef = useRef<HTMLDivElement | null>(null)
  const imageRef = useRef<HTMLImageElement | null>(null)
  const frameDisplayStartedAtRef = useRef<number | null>(null)

  const {
    connectionState,
    connectionStateLabel,
    connectionMode,
    frameDataUrl,
    isLoading: isRemoteLoading,
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
    clipboardNotification,
    copyToRemote,
    copyFromRemote,
    pushLocalClipboardToRemote,
    pasteRemoteClipboardLocally,
    clearClipboardNotification,
    fileTransferProgress,
    transferHistory,
    uploadFile,
    downloadFile,
    cancelFileTransfer,
    pauseFileTransfer,
    resumeFileTransfer,
    retryFileTransfer,
    monitors,
    selectedMonitorNumber,
    monitorSwitchInProgress,
    selectMonitor,
    streamPerformance,
    streamHealth,
    isFrozenFrame,
    adaptiveDisplayScale,
    recordFrameRendered,
    showStreamDebugTimings,
  } = useRemoteDesktop(deviceId, { enabled: !isOffline })

  const [sessionDurationLabel, setSessionDurationLabel] = useState<string | null>(null)

  useEffect(() => {
    if (!activeSessionInfo?.startedAt) {
      setSessionDurationLabel(null)
      return
    }

    const startedAt = activeSessionInfo.startedAt

    const updateDuration = () => {
      setSessionDurationLabel(formatSessionDuration(startedAt))
    }

    updateDuration()
    const timerId = window.setInterval(updateDuration, 1000)
    return () => window.clearInterval(timerId)
  }, [activeSessionInfo?.startedAt])

  const useSupabasePreview = useFallback && connectionMode === 'fallback' && !isOffline

  const {
    frameUrl: fallbackFrameUrl,
    isLoading: isFallbackLoading,
    hasError: fallbackHasError,
    lastRefreshed: fallbackLastRefreshed,
    onFrameLoad,
    onFrameError,
  } = useDesktopPreview(useSupabasePreview ? deviceId : null)

  const activeFrameUrl = useSupabasePreview ? fallbackFrameUrl : frameDataUrl
  const isLoading = useSupabasePreview ? isFallbackLoading : isRemoteLoading
  const lastUpdated = useSupabasePreview ? fallbackLastRefreshed : lastFrameTimestamp

  const showWaiting = isOffline || (useSupabasePreview && fallbackHasError)
  const showFrozenWaiting =
    !useSupabasePreview && isFrozenFrame && connectionState === 'STREAMING'
  const showLiveImage = Boolean(activeFrameUrl) && !showWaiting && !showFrozenWaiting

  useEffect(() => {
    if (activeFrameUrl && !useSupabasePreview) {
      frameDisplayStartedAtRef.current = Date.now()
    }
  }, [activeFrameUrl, useSupabasePreview])

  const handleRemoteFrameLoad = useCallback(() => {
    if (frameDisplayStartedAtRef.current !== null) {
      recordFrameRendered(frameDisplayStartedAtRef.current)
      frameDisplayStartedAtRef.current = null
    }
  }, [recordFrameRendered])

  const controlActive = remoteControlActive && mouseControlEnabled
  const keyboardActive = remoteControlActive && keyboardControlEnabled
  const clipboardActive = remoteControlActive && clipboardControlEnabled
  const fileTransferActive = remoteControlActive && fileTransferEnabled
  const streamingInputEnabled = connectionState === 'STREAMING'
  const clipboardInputEnabled = streamingInputEnabled && clipboardActive
  const [mouseCaptureActive, setMouseCaptureActive] = useState(false)
  const mouseCaptureRef = useRef(false)

  const mouseInputActive = streamingInputEnabled && controlActive && mouseCaptureRef.current

  const releaseMouseCapture = useCallback(() => {
    mouseCaptureRef.current = false
    setMouseCaptureActive(false)
  }, [])

  useEffect(() => {
    if (!mouseCaptureActive) {
      return
    }

    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        releaseMouseCapture()
      }
    }

    window.addEventListener('keydown', handleEscape)
    return () => window.removeEventListener('keydown', handleEscape)
  }, [mouseCaptureActive, releaseMouseCapture])

  useEffect(() => {
    if (!controlActive || !streamingInputEnabled) {
      releaseMouseCapture()
    }
  }, [controlActive, releaseMouseCapture, streamingInputEnabled])

  useEffect(() => {
    if (!clipboardNotification) {
      return
    }

    const timerId = window.setTimeout(() => {
      clearClipboardNotification()
    }, 5000)

    return () => window.clearTimeout(timerId)
  }, [clearClipboardNotification, clipboardNotification])

  const handleMouseMove = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (!mouseInputActive || !viewerRef.current || !imageRef.current) {
        return
      }

      const point = getNormalizedImageCoordinates(
        viewerRef.current,
        imageRef.current,
        event.clientX,
        event.clientY,
      )
      if (!point) {
        return
      }

      sendMouseMove(point.x, point.y)
    },
    [mouseInputActive, sendMouseMove],
  )

  const handleClick = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (!mouseInputActive || !viewerRef.current || !imageRef.current) {
        return
      }

      event.preventDefault()

      const point = getNormalizedImageCoordinates(
        viewerRef.current,
        imageRef.current,
        event.clientX,
        event.clientY,
      )
      if (!point) {
        return
      }

      sendMouseMove(point.x, point.y)
      sendMouseClick('left')
    },
    [mouseInputActive, sendMouseClick, sendMouseMove],
  )

  const handleDoubleClick = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (!mouseInputActive || !viewerRef.current || !imageRef.current) {
        return
      }

      event.preventDefault()

      const point = getNormalizedImageCoordinates(
        viewerRef.current,
        imageRef.current,
        event.clientX,
        event.clientY,
      )
      if (!point) {
        return
      }

      sendMouseMove(point.x, point.y)
      sendMouseDoubleClick()
    },
    [mouseInputActive, sendMouseDoubleClick, sendMouseMove],
  )

  const handleWheel = useCallback(
    (event: React.WheelEvent<HTMLDivElement>) => {
      if (!mouseInputActive) {
        return
      }

      event.preventDefault()
      const delta = wheelDeltaToScrollDelta(event.deltaY)
      if (delta !== 0) {
        sendMouseScroll(delta)
      }
    },
    [mouseInputActive, sendMouseScroll],
  )

  const handleContextMenu = useCallback(
    (event: React.MouseEvent<HTMLDivElement>) => {
      if (!mouseInputActive || !viewerRef.current || !imageRef.current) {
        return
      }

      event.preventDefault()

      const point = getNormalizedImageCoordinates(
        viewerRef.current,
        imageRef.current,
        event.clientX,
        event.clientY,
      )
      if (!point) {
        return
      }

      sendMouseMove(point.x, point.y)
      sendMouseClick('right')
    },
    [mouseInputActive, sendMouseClick, sendMouseMove],
  )

  const handleKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (!streamingInputEnabled || !keyboardActive) {
        return
      }

      if (shouldSendTextInput(event.key)) {
        event.preventDefault()
        sendTextInput(event.key)
        return
      }

      if (!isAllowedKeyCode(event.code)) {
        return
      }

      event.preventDefault()
      sendKeyDown(event.code)
    },
    [keyboardActive, sendKeyDown, sendTextInput, streamingInputEnabled],
  )

  const handleKeyUp = useCallback(
    (event: React.KeyboardEvent<HTMLDivElement>) => {
      if (!streamingInputEnabled || !keyboardActive) {
        return
      }

      if (shouldSendTextInput(event.key)) {
        return
      }

      if (!isAllowedKeyCode(event.code)) {
        return
      }

      event.preventDefault()
      sendKeyUp(event.code)
    },
    [keyboardActive, sendKeyUp, streamingInputEnabled],
  )

  const handleViewerMouseDown = useCallback(() => {
    if (streamingInputEnabled && controlActive) {
      mouseCaptureRef.current = true
      setMouseCaptureActive(true)
      viewerRef.current?.focus()
    }
  }, [controlActive, streamingInputEnabled])

  const handleClose = useCallback(() => {
    releaseSession()
    onClose()
  }, [onClose, releaseSession])

  const handleCopyToRemote = useCallback(async () => {
    if (!clipboardActive) {
      return
    }

    clearClipboardNotification()
    await copyToRemote()
  }, [clearClipboardNotification, clipboardActive, copyToRemote])

  const handleCopyFromRemote = useCallback(async () => {
    if (!clipboardActive) {
      return
    }

    clearClipboardNotification()
    await copyFromRemote()
  }, [clearClipboardNotification, clipboardActive, copyFromRemote])

  const handlePasteToLocal = useCallback(async () => {
    if (!clipboardActive) {
      return
    }

    await pasteRemoteClipboardLocally()
  }, [clipboardActive, pasteRemoteClipboardLocally])

  const handleClipboardCopy = useCallback(() => {
    if (!clipboardInputEnabled) {
      return
    }

    void pushLocalClipboardToRemote()
  }, [clipboardInputEnabled, pushLocalClipboardToRemote])

  const handleClipboardCut = useCallback(() => {
    if (!clipboardInputEnabled) {
      return
    }

    void pushLocalClipboardToRemote()
  }, [clipboardInputEnabled, pushLocalClipboardToRemote])

  const controllerDisplayName =
    activeSessionInfo?.controllerName || activeSessionInfo?.userId || 'Unknown user'

  return (
    <section className="mb-8 overflow-hidden rounded-2xl border border-slate-800 bg-slate-900/80 shadow-xl shadow-black/20 backdrop-blur">
      <div className="flex flex-col gap-4 border-b border-slate-800 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-indigo-400">
            Remote Desktop Preview
          </p>
          <h2 className="mt-1 truncate text-lg font-semibold text-white">{deviceName}</h2>
          <p className="mt-1 truncate font-mono text-xs text-slate-500">{deviceId}</p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <span
            className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wide ring-1 ring-inset ${connectionIndicatorClass(connectionState, useFallback)}`}
          >
            <span
              className={`h-2 w-2 rounded-full ${connectionDotClass(connectionState, useFallback)}`}
            />
            {useFallback ? 'Fallback' : connectionStateLabel}
          </span>

          {!useSupabasePreview && connectionState === 'STREAMING' && (
            <span
              className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold uppercase tracking-wide ring-1 ring-inset ${getStreamHealthIndicatorClass(streamHealth)}`}
            >
              Stream {streamHealth}
            </span>
          )}

          {mouseCaptureActive && controlActive && (
            <span className="inline-flex items-center gap-2 rounded-full bg-cyan-500/15 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-cyan-300 ring-1 ring-inset ring-cyan-500/30">
              <span className="h-2 w-2 animate-pulse rounded-full bg-cyan-400" />
              Remote Control Active
            </span>
          )}

          {keyboardActive && (
            <span className="inline-flex items-center gap-2 rounded-full bg-violet-500/15 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-violet-300 ring-1 ring-inset ring-violet-500/30">
              <span className="h-2 w-2 animate-pulse rounded-full bg-violet-400" />
              Keyboard Active
            </span>
          )}

          {clipboardActive && (
            <span className="inline-flex items-center gap-2 rounded-full bg-sky-500/15 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-sky-300 ring-1 ring-inset ring-sky-500/30">
              Clipboard Sync
            </span>
          )}

          {isControlledByOther && (
            <span className="inline-flex items-center gap-2 rounded-full bg-rose-500/15 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-rose-300 ring-1 ring-inset ring-rose-500/30">
              Device is currently controlled
            </span>
          )}

          {remoteControlActive && !mouseControlEnabled && (
            <span className="inline-flex items-center gap-2 rounded-full bg-slate-500/15 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-slate-400 ring-1 ring-inset ring-slate-500/30">
              View only
            </span>
          )}

          {lastUpdated && !isOffline && (
            <span className="text-xs text-slate-500">
              Last frame {lastUpdated.toLocaleTimeString()}
              {isLoading && (
                <span className="ml-2 inline-flex items-center gap-1 text-indigo-300">
                  <span className="h-2 w-2 animate-spin rounded-full border border-indigo-300 border-t-transparent" />
                  Updating
                </span>
              )}
            </span>
          )}

          <button
            type="button"
            onClick={handleClose}
            className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-300 transition hover:bg-slate-700"
          >
            Close
          </button>
        </div>
      </div>

      {clipboardActive && (
        <div className="flex flex-wrap items-center gap-3 border-b border-slate-800 bg-slate-950/40 px-5 py-3">
          <button
            type="button"
            onClick={() => void handleCopyToRemote()}
            className="rounded-lg border border-sky-700/50 bg-sky-500/10 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-sky-200 transition hover:bg-sky-500/20"
          >
            Copy to remote
          </button>
          <button
            type="button"
            onClick={() => void handleCopyFromRemote()}
            className="rounded-lg border border-sky-700/50 bg-sky-500/10 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-sky-200 transition hover:bg-sky-500/20"
          >
            Copy from remote
          </button>
          <button
            type="button"
            onClick={() => void handlePasteToLocal()}
            className="rounded-lg border border-sky-700/50 bg-sky-500/10 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-sky-200 transition hover:bg-sky-500/20"
          >
            Paste to local
          </button>
          {clipboardNotification && (
            <span className="text-xs text-amber-300">{clipboardNotification}</span>
          )}
        </div>
      )}

      <MonitorSelectorStrip
        monitors={monitors}
        selectedNumber={selectedMonitorNumber}
        switchInProgress={monitorSwitchInProgress}
        onSelect={selectMonitor}
      />

      <FileTransferPanel
        enabled={fileTransferActive}
        progress={fileTransferProgress}
        history={transferHistory}
        onUpload={uploadFile}
        onDownload={downloadFile}
        onCancel={cancelFileTransfer}
        onPause={pauseFileTransfer}
        onResume={resumeFileTransfer}
        onRetry={retryFileTransfer}
      />

      {(isControlledByOther ||
        ((connectionState === 'STREAMING' || connectionState === 'CONNECTED') &&
          activeSessionInfo)) && (
        <div className="border-b border-slate-800 bg-slate-950/50 px-5 py-3">
          <p className="text-sm text-slate-300">
            {isControlledByOther
              ? 'Device is currently controlled'
              : 'You are controlling this device'}
          </p>
          <p className="mt-1 text-xs text-slate-500">
            Controller:{' '}
            <span className="font-medium text-slate-300">{controllerDisplayName}</span>
            {sessionDurationLabel && (
              <span className="ml-3">
                Session duration:{' '}
                <span className="font-medium text-slate-300">{sessionDurationLabel}</span>
              </span>
            )}
          </p>
        </div>
      )}

      <div
        ref={viewerRef}
        tabIndex={streamingInputEnabled && keyboardActive ? 0 : undefined}
        className={`relative flex min-h-[280px] items-center justify-center bg-slate-950/60 p-4 outline-none focus:ring-2 focus:ring-violet-500/40 sm:min-h-[420px] ${
          streamingInputEnabled && controlActive ? 'cursor-crosshair' : ''
        }`}
        onMouseMove={streamingInputEnabled ? handleMouseMove : undefined}
        onMouseDown={streamingInputEnabled ? handleViewerMouseDown : undefined}
        onClick={streamingInputEnabled ? handleClick : undefined}
        onDoubleClick={streamingInputEnabled ? handleDoubleClick : undefined}
        onWheel={streamingInputEnabled ? handleWheel : undefined}
        onContextMenu={streamingInputEnabled ? handleContextMenu : undefined}
        onKeyDown={streamingInputEnabled ? handleKeyDown : undefined}
        onKeyUp={streamingInputEnabled ? handleKeyUp : undefined}
        onCopy={clipboardInputEnabled ? handleClipboardCopy : undefined}
        onCut={clipboardInputEnabled ? handleClipboardCut : undefined}
      >
        {isLoading && !showWaiting && (
          <div className="absolute inset-0 z-10 flex items-center justify-center bg-slate-950/40 backdrop-blur-[1px]">
            <div className="flex items-center gap-3 rounded-xl border border-slate-800 bg-slate-900/90 px-4 py-3 text-sm text-slate-300">
              <span className="h-4 w-4 animate-spin rounded-full border-2 border-slate-600 border-t-indigo-400" />
              Loading preview...
            </div>
          </div>
        )}

        {showFrozenWaiting && (
          <div className="absolute inset-0 z-20 flex items-center justify-center bg-slate-950/70 backdrop-blur-[1px]">
            <div className="text-center">
              <p className="text-sm font-medium text-amber-200">Waiting for new frames...</p>
              <p className="mt-2 text-xs text-slate-500">
                The live stream paused. It will recover automatically when frames resume.
              </p>
            </div>
          </div>
        )}

        {showWaiting ? (
          <div className="text-center">
            <p className="text-sm font-medium text-slate-300">
              {isOffline ? 'Desktop preview unavailable' : 'Waiting for desktop stream'}
            </p>
            <p className="mt-2 max-w-md text-xs text-slate-500">
              {isOffline
                ? 'The device is offline. Preview will resume when the agent reconnects.'
                : useSupabasePreview
                  ? 'Ensure the device agent is running and the desktop-preview bucket is public.'
                  : 'Connecting to the device remote desktop stream. Fallback preview will be used if the connection fails.'}
            </p>
          </div>
        ) : showLiveImage ? (
          <>
            <img
              ref={imageRef}
              key={useSupabasePreview ? fallbackFrameUrl ?? 'fallback' : frameDataUrl ?? 'remote'}
              src={activeFrameUrl ?? undefined}
              alt={`Desktop preview for ${deviceName}`}
              className="pointer-events-none max-h-[65vh] w-full max-w-full rounded-lg object-contain"
              style={{
                transform: `scale(${adaptiveDisplayScale})`,
                transformOrigin: 'center center',
              }}
              onLoad={useSupabasePreview ? onFrameLoad : handleRemoteFrameLoad}
              onError={useSupabasePreview ? onFrameError : undefined}
              draggable={false}
            />
            {!useSupabasePreview && connectionState === 'STREAMING' && (
              <StreamPerformanceOverlay
                performance={streamPerformance}
                showDebugTimings={showStreamDebugTimings}
              />
            )}
          </>
        ) : (
          <div className="text-center">
            <p className="text-sm font-medium text-slate-300">Preparing live stream...</p>
          </div>
        )}
      </div>
    </section>
  )
}
