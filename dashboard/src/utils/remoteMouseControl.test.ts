import { describe, expect, it } from 'vitest'

import {
  MOUSE_MOVE_MIN_INTERVAL_MS,
  MouseMoveThrottler,
  areDuplicateCoordinates,
  normalizePointerOnImage,
  wheelDeltaToScrollDelta,
} from './remoteMouseControl'

describe('normalizePointerOnImage', () => {
  it('maps pointer position to normalized coordinates', () => {
    expect(normalizePointerOnImage(530, 410, 1000, 1000)).toEqual({ x: 0.53, y: 0.41 })
  })

  it('returns null when pointer is outside the image bounds', () => {
    expect(normalizePointerOnImage(-1, 10, 100, 100)).toBeNull()
    expect(normalizePointerOnImage(10, 101, 100, 100)).toBeNull()
  })
})

describe('areDuplicateCoordinates', () => {
  it('detects duplicate normalized points', () => {
    const point = { x: 0.5, y: 0.5 }
    expect(areDuplicateCoordinates(point, point)).toBe(true)
    expect(areDuplicateCoordinates(null, point)).toBe(false)
    expect(areDuplicateCoordinates({ x: 0.1, y: 0.2 }, { x: 0.2, y: 0.2 })).toBe(false)
  })
})

describe('MouseMoveThrottler', () => {
  it('ignores duplicate coordinates', () => {
    const throttler = new MouseMoveThrottler()
    const point = { x: 0.5, y: 0.5 }

    expect(throttler.shouldSend(point, 1000)).toBe(true)
    expect(throttler.shouldSend(point, 1100)).toBe(false)
  })

  it('limits move events to 60 per second', () => {
    const throttler = new MouseMoveThrottler()
    const interval = Math.ceil(MOUSE_MOVE_MIN_INTERVAL_MS)

    expect(throttler.shouldSend({ x: 0.1, y: 0.2 }, 0)).toBe(true)
    expect(throttler.shouldSend({ x: 0.2, y: 0.2 }, interval - 1)).toBe(false)
    expect(throttler.shouldSend({ x: 0.3, y: 0.2 }, interval)).toBe(true)
  })
})

describe('wheelDeltaToScrollDelta', () => {
  it('maps wheel direction to signed scroll deltas', () => {
    expect(wheelDeltaToScrollDelta(120)).toBe(-120)
    expect(wheelDeltaToScrollDelta(-120)).toBe(120)
    expect(wheelDeltaToScrollDelta(0)).toBe(0)
  })
})
