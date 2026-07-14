import { describe, expect, it } from 'vitest'

import {
  adjustAdaptiveStreamState,
  calculateAverageLatencyMs,
  calculateFps,
  calculateStreamHealth,
  countDroppedFrames,
  DEFAULT_ADAPTIVE_STATE,
  estimateCaptureEncodeMs,
  estimateNetworkLatencyMs,
  formatResolution,
  isFrozenFrame,
  shouldSkipFrameForAdaptive,
  shouldThrottleStream,
  type FrameSample,
} from './remoteDesktopStreamMetrics'

describe('remoteDesktopStreamMetrics', () => {
  it('counts dropped frames from sequence gaps', () => {
    expect(countDroppedFrames(10, 12)).toBe(1)
    expect(countDroppedFrames(10, 10)).toBe(0)
    expect(countDroppedFrames(null, 3)).toBe(0)
  })

  it('estimates network latency from server timestamp', () => {
    expect(estimateNetworkLatencyMs(1_500, 1_000)).toBe(500)
    expect(estimateNetworkLatencyMs(900, 1_000)).toBe(0)
    expect(estimateNetworkLatencyMs(1_500, null)).toBeNull()
  })

  it('estimates capture and encode time from frame spacing', () => {
    expect(estimateCaptureEncodeMs(1_000, 1_500, 100)).toBe(400)
    expect(estimateCaptureEncodeMs(null, 1_500, 100)).toBeNull()
  })

  it('calculates fps and average latency from recent samples', () => {
    const nowMs = 10_000
    const samples: FrameSample[] = [
      {
        receivedAtMs: 9_200,
        serverTimestampMs: 9_100,
        sequence: 1,
        byteLength: 1_024,
        width: 1280,
        height: 720,
        displayed: true,
      },
      {
        receivedAtMs: 9_700,
        serverTimestampMs: 9_600,
        sequence: 2,
        byteLength: 1_024,
        width: 1280,
        height: 720,
        displayed: true,
      },
    ]

    expect(calculateFps(samples, 1_000, nowMs)).toBe(2)
    expect(calculateAverageLatencyMs(samples, 1_000, nowMs)).toBe(100)
    expect(formatResolution(1280, 720)).toBe('1280x720')
  })

  it('calculates stream health from latency, drops, and reconnect count', () => {
    expect(
      calculateStreamHealth({
        connectionState: 'STREAMING',
        averageLatencyMs: 120,
        droppedFrames: 0,
        reconnectCount: 0,
      }),
    ).toBe('Excellent')

    expect(
      calculateStreamHealth({
        connectionState: 'STREAMING',
        averageLatencyMs: 250,
        droppedFrames: 5,
        reconnectCount: 1,
      }),
    ).toBe('Fair')

    expect(
      calculateStreamHealth({
        connectionState: 'STREAMING',
        averageLatencyMs: 700,
        droppedFrames: 15,
        reconnectCount: 4,
      }),
    ).toBe('Poor')

    expect(
      calculateStreamHealth({
        connectionState: 'DISCONNECTED',
        averageLatencyMs: 0,
        droppedFrames: 0,
        reconnectCount: 0,
      }),
    ).toBe('Disconnected')
  })

  it('detects frozen frames after two seconds without new frames', () => {
    expect(isFrozenFrame(1_000, 2_500, true)).toBe(false)
    expect(isFrozenFrame(1_000, 3_100, true)).toBe(true)
    expect(isFrozenFrame(1_000, 3_100, false)).toBe(false)
  })

  it('reduces adaptive quality when latency increases', () => {
    const reduced = adjustAdaptiveStreamState(DEFAULT_ADAPTIVE_STATE, 650, false)
    expect(reduced.qualityPercent).toBe(55)
    expect(reduced.frameSkipInterval).toBe(3)
    expect(reduced.streamThrottled).toBe(true)
  })

  it('restores adaptive quality gradually when latency recovers', () => {
    const reduced = adjustAdaptiveStreamState(DEFAULT_ADAPTIVE_STATE, 650, false)
    const restored = adjustAdaptiveStreamState(reduced, 120, true)
    expect(restored.qualityPercent).toBeGreaterThan(reduced.qualityPercent)
    expect(restored.streamThrottled).toBe(false)
  })

  it('skips frames according to adaptive interval', () => {
    expect(shouldSkipFrameForAdaptive(1, 2)).toBe(true)
    expect(shouldSkipFrameForAdaptive(2, 2)).toBe(false)
    expect(shouldSkipFrameForAdaptive(2, 1)).toBe(false)
  })

  it('throttles stream only for poor health and releases after recovery', () => {
    expect(shouldThrottleStream('Poor', false)).toBe(true)
    expect(shouldThrottleStream('Excellent', true)).toBe(false)
    expect(shouldThrottleStream('Good', true)).toBe(false)
  })
})
