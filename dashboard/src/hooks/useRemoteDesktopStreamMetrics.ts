import { useCallback, useEffect, useRef, useState } from 'react'

import type { RemoteDesktopConnectionState } from '../utils/remoteDesktopLifecycle'
import {
  adjustAdaptiveStreamState,
  buildPerformanceSnapshot,
  calculateAverageLatencyMs,
  countDroppedFrames,
  DEFAULT_ADAPTIVE_STATE,
  estimateCaptureEncodeMs,
  estimateNetworkLatencyMs,
  FROZEN_FRAME_THRESHOLD_MS,
  isFrozenFrame,
  METRICS_UPDATE_INTERVAL_MS,
  parseFrameByteLength,
  parseFrameDimensions,
  parseFrameSequence,
  parseServerTimestampMs,
  PERFORMANCE_LOG_INTERVAL_MS,
  readPeakMemoryMb,
  shouldSkipFrameForAdaptive,
  shouldThrottleStream,
  trimFrameSamples,
  type AdaptiveStreamState,
  type FrameSample,
  type FrameTimingMetrics,
  type StreamPerformanceSnapshot,
} from '../utils/remoteDesktopStreamMetrics'

interface UseRemoteDesktopStreamMetricsOptions {
  connectionState: RemoteDesktopConnectionState
  isStreaming: boolean
  reconnectCount: number
  onThrottleStream?: (throttle: boolean) => void
}

interface UseRemoteDesktopStreamMetricsResult {
  performance: StreamPerformanceSnapshot
  isFrozenFrame: boolean
  adaptiveState: AdaptiveStreamState
  recordIncomingFrame: (payload: Record<string, unknown>) => boolean
  recordDecodeRenderMs: (decodeRenderMs: number) => void
  reset: () => void
}

const SAMPLE_RETENTION_MS = 60_000
const ADAPTIVE_STEP_UP_COOLDOWN_MS = 3_000

export function useRemoteDesktopStreamMetrics(
  options: UseRemoteDesktopStreamMetricsOptions,
): UseRemoteDesktopStreamMetricsResult {
  const { connectionState, isStreaming, reconnectCount, onThrottleStream } = options

  const [performance, setPerformance] = useState<StreamPerformanceSnapshot>(() =>
    buildPerformanceSnapshot({
      samples: [],
      connectionState,
      droppedFrames: 0,
      reconnectCount,
      adaptiveState: DEFAULT_ADAPTIVE_STATE,
      frameTiming: {
        captureEncodeMs: null,
        networkMs: null,
        decodeRenderMs: null,
      },
      peakMemoryMb: readPeakMemoryMb(),
      nowMs: Date.now(),
    }),
  )
  const [isFrozen, setIsFrozen] = useState(false)
  const [adaptiveState, setAdaptiveState] = useState<AdaptiveStreamState>(DEFAULT_ADAPTIVE_STATE)

  const samplesRef = useRef<FrameSample[]>([])
  const droppedFramesRef = useRef(0)
  const lastSequenceRef = useRef<number | null>(null)
  const lastServerTimestampRef = useRef<number | null>(null)
  const lastFrameReceivedAtRef = useRef<number | null>(null)
  const frameCounterRef = useRef(0)
  const frameTimingRef = useRef<FrameTimingMetrics>({
    captureEncodeMs: null,
    networkMs: null,
    decodeRenderMs: null,
  })
  const adaptiveStateRef = useRef<AdaptiveStreamState>(DEFAULT_ADAPTIVE_STATE)
  const lastAdaptiveStepUpAtRef = useRef(0)
  const peakMemoryRef = useRef<number | null>(readPeakMemoryMb())
  const streamThrottledRef = useRef(false)

  const refreshMetrics = useCallback(() => {
    const nowMs = Date.now()
    const peakMemoryMb = readPeakMemoryMb()
    if (peakMemoryMb !== null) {
      peakMemoryRef.current =
        peakMemoryRef.current === null
          ? peakMemoryMb
          : Math.max(peakMemoryRef.current, peakMemoryMb)
    }

  const averageLatencyMs = calculateAverageLatencyMs(
      samplesRef.current,
      METRICS_UPDATE_INTERVAL_MS,
      nowMs,
    )
    const canStepUp = nowMs - lastAdaptiveStepUpAtRef.current >= ADAPTIVE_STEP_UP_COOLDOWN_MS
    const nextAdaptive = adjustAdaptiveStreamState(
      adaptiveStateRef.current,
      averageLatencyMs,
      canStepUp,
    )

    if (
      nextAdaptive.qualityPercent !== adaptiveStateRef.current.qualityPercent ||
      nextAdaptive.frameSkipInterval !== adaptiveStateRef.current.frameSkipInterval
    ) {
      if (nextAdaptive.qualityPercent > adaptiveStateRef.current.qualityPercent) {
        lastAdaptiveStepUpAtRef.current = nowMs
      }
      adaptiveStateRef.current = nextAdaptive
      setAdaptiveState(nextAdaptive)
    }

    const snapshot = buildPerformanceSnapshot({
      samples: samplesRef.current,
      connectionState,
      droppedFrames: droppedFramesRef.current,
      reconnectCount,
      adaptiveState: adaptiveStateRef.current,
      frameTiming: frameTimingRef.current,
      peakMemoryMb: peakMemoryRef.current,
      nowMs,
    })

    setPerformance(snapshot)
    setIsFrozen(isFrozenFrame(lastFrameReceivedAtRef.current, nowMs, isStreaming))

    const shouldThrottle = shouldThrottleStream(snapshot.health, streamThrottledRef.current)
    if (shouldThrottle !== streamThrottledRef.current) {
      streamThrottledRef.current = shouldThrottle
      onThrottleStream?.(shouldThrottle)
    }
  }, [connectionState, isStreaming, onThrottleStream, reconnectCount])

  const recordIncomingFrame = useCallback((payload: Record<string, unknown>): boolean => {
    const receivedAtMs = Date.now()
    const sequence = parseFrameSequence(payload)
    const serverTimestampMs = parseServerTimestampMs(payload)
    const { width, height } = parseFrameDimensions(payload)
    const byteLength = parseFrameByteLength(payload)

    droppedFramesRef.current += countDroppedFrames(lastSequenceRef.current, sequence)
    if (sequence !== null) {
      lastSequenceRef.current = sequence
    }

    const networkMs = estimateNetworkLatencyMs(receivedAtMs, serverTimestampMs)
    const captureEncodeMs = estimateCaptureEncodeMs(
      lastServerTimestampRef.current,
      serverTimestampMs,
      networkMs,
    )
    if (serverTimestampMs !== null) {
      lastServerTimestampRef.current = serverTimestampMs
    }

    frameTimingRef.current = {
      captureEncodeMs,
      networkMs,
      decodeRenderMs: frameTimingRef.current.decodeRenderMs,
    }

    frameCounterRef.current += 1
    const shouldSkip = shouldSkipFrameForAdaptive(
      frameCounterRef.current,
      adaptiveStateRef.current.frameSkipInterval,
    )

    const sample: FrameSample = {
      receivedAtMs,
      serverTimestampMs,
      sequence,
      byteLength,
      width,
      height,
      displayed: !shouldSkip,
    }

    samplesRef.current = trimFrameSamples(
      [...samplesRef.current, sample],
      SAMPLE_RETENTION_MS,
      receivedAtMs,
    )

    if (!shouldSkip) {
      lastFrameReceivedAtRef.current = receivedAtMs
    }

    return !shouldSkip
  }, [])

  const recordDecodeRenderMs = useCallback((decodeRenderMs: number) => {
    frameTimingRef.current = {
      ...frameTimingRef.current,
      decodeRenderMs: Math.max(0, Math.round(decodeRenderMs)),
    }
  }, [])

  const reset = useCallback(() => {
    samplesRef.current = []
    droppedFramesRef.current = 0
    lastSequenceRef.current = null
    lastServerTimestampRef.current = null
    lastFrameReceivedAtRef.current = null
    frameCounterRef.current = 0
    frameTimingRef.current = {
      captureEncodeMs: null,
      networkMs: null,
      decodeRenderMs: null,
    }
    adaptiveStateRef.current = DEFAULT_ADAPTIVE_STATE
    streamThrottledRef.current = false
    lastAdaptiveStepUpAtRef.current = 0
    peakMemoryRef.current = readPeakMemoryMb()
    setAdaptiveState(DEFAULT_ADAPTIVE_STATE)
    setIsFrozen(false)
    setPerformance(
      buildPerformanceSnapshot({
        samples: [],
        connectionState,
        droppedFrames: 0,
        reconnectCount,
        adaptiveState: DEFAULT_ADAPTIVE_STATE,
        frameTiming: frameTimingRef.current,
        peakMemoryMb: peakMemoryRef.current,
        nowMs: Date.now(),
      }),
    )
  }, [connectionState, reconnectCount])

  useEffect(() => {
    const metricsTimer = window.setInterval(refreshMetrics, METRICS_UPDATE_INTERVAL_MS)
    const frozenTimer = window.setInterval(() => {
      setIsFrozen(
        isFrozenFrame(lastFrameReceivedAtRef.current, Date.now(), isStreaming, FROZEN_FRAME_THRESHOLD_MS),
      )
    }, 250)

    const logTimer = window.setInterval(() => {
      if (!isStreaming) {
        return
      }

      const snapshot = buildPerformanceSnapshot({
        samples: samplesRef.current,
        connectionState,
        droppedFrames: droppedFramesRef.current,
        reconnectCount,
        adaptiveState: adaptiveStateRef.current,
        frameTiming: frameTimingRef.current,
        peakMemoryMb: peakMemoryRef.current,
        nowMs: Date.now(),
      })

      console.info('[RemoteDesktop][Performance]', {
        averageFps: snapshot.fps,
        averageLatencyMs: snapshot.averageLatencyMs,
        droppedFrames: snapshot.droppedFrames,
        reconnectCount: snapshot.reconnectCount,
        peakMemoryMb: snapshot.peakMemoryMb,
        health: snapshot.health,
      })
    }, PERFORMANCE_LOG_INTERVAL_MS)

    return () => {
      window.clearInterval(metricsTimer)
      window.clearInterval(frozenTimer)
      window.clearInterval(logTimer)
    }
  }, [connectionState, isStreaming, reconnectCount, refreshMetrics])

  useEffect(() => {
    if (!isStreaming) {
      setIsFrozen(false)
    }
  }, [isStreaming])

  return {
    performance,
    isFrozenFrame: isFrozen,
    adaptiveState,
    recordIncomingFrame,
    recordDecodeRenderMs,
    reset,
  }
}
