import type { RemoteDesktopConnectionState } from './remoteDesktopLifecycle'

export type StreamHealth = 'Excellent' | 'Good' | 'Fair' | 'Poor' | 'Disconnected'

export const FROZEN_FRAME_THRESHOLD_MS = 2_000
export const PERFORMANCE_LOG_INTERVAL_MS = 30_000
export const METRICS_UPDATE_INTERVAL_MS = 1_000

export interface FrameTimingMetrics {
  captureEncodeMs: number | null
  networkMs: number | null
  decodeRenderMs: number | null
}

export interface StreamPerformanceSnapshot {
  fps: number
  averageLatencyMs: number
  resolution: string
  bitrateKbps: number
  droppedFrames: number
  frameTiming: FrameTimingMetrics
  health: StreamHealth
  adaptiveQualityPercent: number
  adaptiveFpsCap: number | null
  reconnectCount: number
  peakMemoryMb: number | null
}

export interface FrameSample {
  receivedAtMs: number
  serverTimestampMs: number | null
  sequence: number | null
  byteLength: number
  width: number | null
  height: number | null
  displayed: boolean
}

export interface AdaptiveStreamState {
  displayScale: number
  frameSkipInterval: number
  qualityPercent: number
  fpsCap: number | null
  streamThrottled: boolean
}

export const DEFAULT_ADAPTIVE_STATE: AdaptiveStreamState = {
  displayScale: 1,
  frameSkipInterval: 1,
  qualityPercent: 100,
  fpsCap: null,
  streamThrottled: false,
}

const LATENCY_EXCELLENT_MS = 150
const LATENCY_GOOD_MS = 300
const LATENCY_FAIR_MS = 600

export function parseFrameSequence(payload: Record<string, unknown>): number | null {
  const sequence = payload.sequence
  return typeof sequence === 'number' && Number.isFinite(sequence) ? sequence : null
}

export function parseFrameDimensions(
  payload: Record<string, unknown>,
): { width: number | null; height: number | null } {
  const width = payload.width
  const height = payload.height
  return {
    width: typeof width === 'number' && width > 0 ? width : null,
    height: typeof height === 'number' && height > 0 ? height : null,
  }
}

export function parseFrameByteLength(payload: Record<string, unknown>): number {
  const data = payload.data
  if (typeof data !== 'string' || !data) {
    return 0
  }

  return Math.floor((data.length * 3) / 4)
}

export function parseServerTimestampMs(payload: Record<string, unknown>): number | null {
  const timestamp = payload.timestamp
  if (typeof timestamp !== 'string') {
    return null
  }

  const parsed = Date.parse(timestamp)
  return Number.isNaN(parsed) ? null : parsed
}

export function countDroppedFrames(
  previousSequence: number | null,
  nextSequence: number | null,
): number {
  if (previousSequence === null || nextSequence === null) {
    return 0
  }

  if (nextSequence <= previousSequence) {
    return 0
  }

  return Math.max(0, nextSequence - previousSequence - 1)
}

export function estimateNetworkLatencyMs(
  receivedAtMs: number,
  serverTimestampMs: number | null,
): number | null {
  if (serverTimestampMs === null) {
    return null
  }

  return Math.max(0, receivedAtMs - serverTimestampMs)
}

export function estimateCaptureEncodeMs(
  previousServerTimestampMs: number | null,
  serverTimestampMs: number | null,
  networkMs: number | null,
): number | null {
  if (previousServerTimestampMs === null || serverTimestampMs === null) {
    return null
  }

  const interFrameMs = Math.max(0, serverTimestampMs - previousServerTimestampMs)
  if (networkMs === null) {
    return interFrameMs
  }

  return Math.max(0, interFrameMs - networkMs)
}

export function calculateFps(samples: FrameSample[], windowMs: number, nowMs: number): number {
  const displayed = samples.filter(
    (sample) => sample.displayed && nowMs - sample.receivedAtMs <= windowMs,
  )
  if (displayed.length < 2) {
    return displayed.length
  }

  const durationSeconds = Math.max(
    (displayed[displayed.length - 1].receivedAtMs - displayed[0].receivedAtMs) / 1000,
    1,
  )
  return Math.round((displayed.length / durationSeconds) * 10) / 10
}

export function calculateAverageLatencyMs(samples: FrameSample[], windowMs: number, nowMs: number): number {
  const latencies = samples
    .filter((sample) => nowMs - sample.receivedAtMs <= windowMs)
    .map((sample) => estimateNetworkLatencyMs(sample.receivedAtMs, sample.serverTimestampMs))
    .filter((value): value is number => value !== null)

  if (latencies.length === 0) {
    return 0
  }

  const total = latencies.reduce((sum, value) => sum + value, 0)
  return Math.round(total / latencies.length)
}

export function calculateBitrateKbps(samples: FrameSample[], windowMs: number, nowMs: number): number {
  const recent = samples.filter((sample) => nowMs - sample.receivedAtMs <= windowMs)
  if (recent.length === 0) {
    return 0
  }

  const bytes = recent.reduce((sum, sample) => sum + sample.byteLength, 0)
  const durationSeconds = Math.max(
    (recent[recent.length - 1].receivedAtMs - recent[0].receivedAtMs) / 1000,
    1,
  )
  return Math.round((bytes / durationSeconds) / 1024)
}

export function formatResolution(width: number | null, height: number | null): string {
  if (width && height) {
    return `${width}x${height}`
  }
  return 'Unknown'
}

export function calculateStreamHealth(params: {
  connectionState: RemoteDesktopConnectionState
  averageLatencyMs: number
  droppedFrames: number
  reconnectCount: number
}): StreamHealth {
  const { connectionState, averageLatencyMs, droppedFrames, reconnectCount } = params

  if (connectionState === 'DISCONNECTED' || connectionState === 'IDLE' || connectionState === 'ERROR') {
    return 'Disconnected'
  }

  if (connectionState !== 'STREAMING') {
    return reconnectCount > 0 ? 'Poor' : 'Fair'
  }

  if (reconnectCount >= 3 || droppedFrames >= 12 || averageLatencyMs >= LATENCY_FAIR_MS) {
    return 'Poor'
  }

  if (droppedFrames >= 4 || averageLatencyMs >= LATENCY_GOOD_MS) {
    return 'Fair'
  }

  if (averageLatencyMs >= LATENCY_EXCELLENT_MS) {
    return 'Good'
  }

  return 'Excellent'
}

export function getStreamHealthIndicatorClass(health: StreamHealth): string {
  switch (health) {
    case 'Excellent':
      return 'bg-emerald-500/20 text-emerald-300 ring-emerald-500/30'
    case 'Good':
      return 'bg-lime-500/20 text-lime-300 ring-lime-500/30'
    case 'Fair':
      return 'bg-amber-500/20 text-amber-300 ring-amber-500/30'
    case 'Poor':
      return 'bg-rose-500/20 text-rose-300 ring-rose-500/30'
    case 'Disconnected':
    default:
      return 'bg-slate-500/20 text-slate-400 ring-slate-500/30'
  }
}

export function isFrozenFrame(
  lastFrameReceivedAtMs: number | null,
  nowMs: number,
  isStreaming: boolean,
  thresholdMs = FROZEN_FRAME_THRESHOLD_MS,
): boolean {
  if (!isStreaming || lastFrameReceivedAtMs === null) {
    return false
  }

  return nowMs - lastFrameReceivedAtMs > thresholdMs
}

export function shouldSkipFrameForAdaptive(
  frameCounter: number,
  frameSkipInterval: number,
): boolean {
  if (frameSkipInterval <= 1) {
    return false
  }

  return frameCounter % frameSkipInterval !== 0
}

export function adjustAdaptiveStreamState(
  current: AdaptiveStreamState,
  averageLatencyMs: number,
  canStepUp: boolean,
): AdaptiveStreamState {
  if (averageLatencyMs >= LATENCY_FAIR_MS) {
    return {
      displayScale: 0.55,
      frameSkipInterval: 3,
      qualityPercent: 55,
      fpsCap: 1,
      streamThrottled: true,
    }
  }

  if (averageLatencyMs >= LATENCY_GOOD_MS) {
    return {
      displayScale: 0.7,
      frameSkipInterval: 2,
      qualityPercent: 70,
      fpsCap: 2,
      streamThrottled: true,
    }
  }

  if (averageLatencyMs >= LATENCY_EXCELLENT_MS) {
    return {
      displayScale: 0.85,
      frameSkipInterval: 1,
      qualityPercent: 85,
      fpsCap: null,
      streamThrottled: false,
    }
  }

  if (!canStepUp) {
    return current
  }

  if (current.qualityPercent < 100) {
    return {
      displayScale: Math.min(1, current.displayScale + 0.15),
      frameSkipInterval: 1,
      qualityPercent: Math.min(100, current.qualityPercent + 15),
      fpsCap: null,
      streamThrottled: false,
    }
  }

  return DEFAULT_ADAPTIVE_STATE
}

export function shouldThrottleStream(
  health: StreamHealth,
  currentlyThrottled: boolean,
): boolean {
  if (health === 'Poor') {
    return true
  }

  if (currentlyThrottled && (health === 'Fair' || health === 'Good' || health === 'Excellent')) {
    return false
  }

  return currentlyThrottled
}

export function buildPerformanceSnapshot(params: {
  samples: FrameSample[]
  connectionState: RemoteDesktopConnectionState
  droppedFrames: number
  reconnectCount: number
  adaptiveState: AdaptiveStreamState
  frameTiming: FrameTimingMetrics
  peakMemoryMb: number | null
  nowMs: number
}): StreamPerformanceSnapshot {
  const fps = calculateFps(params.samples, METRICS_UPDATE_INTERVAL_MS, params.nowMs)
  const averageLatencyMs = calculateAverageLatencyMs(
    params.samples,
    METRICS_UPDATE_INTERVAL_MS,
    params.nowMs,
  )
  const latest = params.samples.at(-1)
  const resolution = formatResolution(latest?.width ?? null, latest?.height ?? null)
  const bitrateKbps = calculateBitrateKbps(params.samples, METRICS_UPDATE_INTERVAL_MS, params.nowMs)
  const health = calculateStreamHealth({
    connectionState: params.connectionState,
    averageLatencyMs,
    droppedFrames: params.droppedFrames,
    reconnectCount: params.reconnectCount,
  })

  return {
    fps,
    averageLatencyMs,
    resolution,
    bitrateKbps,
    droppedFrames: params.droppedFrames,
    frameTiming: params.frameTiming,
    health,
    adaptiveQualityPercent: params.adaptiveState.qualityPercent,
    adaptiveFpsCap: params.adaptiveState.fpsCap,
    reconnectCount: params.reconnectCount,
    peakMemoryMb: params.peakMemoryMb,
  }
}

export function trimFrameSamples(samples: FrameSample[], maxAgeMs: number, nowMs: number): FrameSample[] {
  return samples.filter((sample) => nowMs - sample.receivedAtMs <= maxAgeMs)
}

export function readPeakMemoryMb(): number | null {
  const memory = performance && 'memory' in performance
    ? (performance as Performance & { memory?: { usedJSHeapSize: number } }).memory
    : undefined

  if (!memory?.usedJSHeapSize) {
    return null
  }

  return Math.round((memory.usedJSHeapSize / (1024 * 1024)) * 10) / 10
}

export function framePayloadToObjectUrl(
  payload: Record<string, unknown>,
): { objectUrl: string; byteLength: number } | null {
  const data = payload.data
  if (typeof data !== 'string' || !data) {
    return null
  }

  const binary = atob(data)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index)
  }

  const blob = new Blob([bytes], { type: 'image/jpeg' })
  return {
    objectUrl: URL.createObjectURL(blob),
    byteLength: bytes.length,
  }
}

export function revokeObjectUrl(objectUrl: string | null): void {
  if (objectUrl && objectUrl.startsWith('blob:')) {
    URL.revokeObjectURL(objectUrl)
  }
}
