export const MAX_CLIPBOARD_TEXT_LENGTH = 262_144
export const CLIPBOARD_NOTIFICATION_MIN_INTERVAL_MS = 3000

/**
 * Performance target (acceptance criterion, not enforced in tests):
 * average sync latency < 300 ms, maximum < 700 ms.
 */

export type ClipboardApplyError = 'permission_denied' | 'not_available' | 'unknown'

export interface ClipboardApplyResult {
  applied: boolean
  error?: ClipboardApplyError
}

export interface ClipboardNotificationDecision {
  message: string
  display: boolean
}

export function validateClipboardText(value: unknown): string | null {
  if (typeof value !== 'string') {
    return null
  }

  if (value.length > MAX_CLIPBOARD_TEXT_LENGTH) {
    return null
  }

  if (value.includes('\u0000')) {
    return null
  }

  return value
}

export function clipboardTextHash(text: string): string {
  return `${text.length}:${text}`
}

export function shouldSyncClipboardText(
  previousHash: string | null,
  text: string,
): boolean {
  const nextHash = clipboardTextHash(text)
  return previousHash !== nextHash
}

export function classifyClipboardWriteError(error: unknown): ClipboardApplyError {
  if (error instanceof DOMException) {
    if (error.name === 'NotAllowedError') {
      return 'permission_denied'
    }
    if (error.name === 'SecurityError' || error.name === 'NotSupportedError') {
      return 'not_available'
    }
  }

  return 'unknown'
}

export async function applyRemoteClipboardLocally(
  text: string,
): Promise<ClipboardApplyResult> {
  if (!validateClipboardText(text)) {
    return { applied: false, error: 'unknown' }
  }

  if (!navigator.clipboard?.writeText) {
    return { applied: false, error: 'not_available' }
  }

  try {
    await navigator.clipboard.writeText(text)
    return { applied: true }
  } catch (error) {
    return {
      applied: false,
      error: classifyClipboardWriteError(error),
    }
  }
}

export async function readLocalClipboardText(): Promise<string | null> {
  if (!navigator.clipboard?.readText) {
    return null
  }

  try {
    const text = await navigator.clipboard.readText()
    return validateClipboardText(text)
  } catch {
    return null
  }
}

export class ClipboardNotificationThrottler {
  private lastDisplayedAt: number | null = null

  resolve(message: string, nowMs = Date.now()): ClipboardNotificationDecision {
    if (this.lastDisplayedAt === null) {
      this.lastDisplayedAt = nowMs
      return { message, display: true }
    }

    if (nowMs - this.lastDisplayedAt >= CLIPBOARD_NOTIFICATION_MIN_INTERVAL_MS) {
      this.lastDisplayedAt = nowMs
      return { message, display: true }
    }

    return { message, display: false }
  }

  reset(): void {
    this.lastDisplayedAt = null
  }
}
