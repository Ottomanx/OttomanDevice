export const MOUSE_MOVE_MAX_EVENTS_PER_SECOND = 60
export const MOUSE_MOVE_MIN_INTERVAL_MS = 1000 / MOUSE_MOVE_MAX_EVENTS_PER_SECOND

export interface NormalizedPoint {
  x: number
  y: number
}

export function normalizePointerOnImage(
  mouseX: number,
  mouseY: number,
  imageWidth: number,
  imageHeight: number,
): NormalizedPoint | null {
  if (imageWidth <= 0 || imageHeight <= 0) {
    return null
  }

  if (mouseX < 0 || mouseY < 0 || mouseX > imageWidth || mouseY > imageHeight) {
    return null
  }

  return {
    x: mouseX / imageWidth,
    y: mouseY / imageHeight,
  }
}

export function areDuplicateCoordinates(
  previous: NormalizedPoint | null,
  next: NormalizedPoint,
): boolean {
  if (!previous) {
    return false
  }

  return previous.x === next.x && previous.y === next.y
}

export class MouseMoveThrottler {
  private lastSentAt: number | null = null
  private lastPoint: NormalizedPoint | null = null

  shouldSend(point: NormalizedPoint, nowMs = Date.now()): boolean {
    if (areDuplicateCoordinates(this.lastPoint, point)) {
      return false
    }

    if (this.lastSentAt !== null && nowMs - this.lastSentAt < MOUSE_MOVE_MIN_INTERVAL_MS) {
      return false
    }

    this.lastPoint = point
    this.lastSentAt = nowMs
    return true
  }

  reset(): void {
    this.lastSentAt = null
    this.lastPoint = null
  }
}

export function wheelDeltaToScrollDelta(deltaY: number): number {
  if (deltaY === 0) {
    return 0
  }

  return deltaY > 0 ? -120 : 120
}
