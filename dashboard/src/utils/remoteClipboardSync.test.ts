import { describe, expect, it, vi } from 'vitest'

import {
  CLIPBOARD_NOTIFICATION_MIN_INTERVAL_MS,
  ClipboardNotificationThrottler,
  MAX_CLIPBOARD_TEXT_LENGTH,
  applyRemoteClipboardLocally,
  clipboardTextHash,
  shouldSyncClipboardText,
  validateClipboardText,
} from './remoteClipboardSync'

describe('validateClipboardText', () => {
  it('accepts text up to 256 KB', () => {
    const text = 'a'.repeat(MAX_CLIPBOARD_TEXT_LENGTH)
    expect(validateClipboardText(text)).toBe(text)
  })

  it('rejects oversized and invalid payloads', () => {
    expect(validateClipboardText('a'.repeat(MAX_CLIPBOARD_TEXT_LENGTH + 1))).toBeNull()
    expect(validateClipboardText(null)).toBeNull()
    expect(validateClipboardText(123)).toBeNull()
    expect(validateClipboardText('a\u0000b')).toBeNull()
  })
})

describe('shouldSyncClipboardText', () => {
  it('deduplicates identical clipboard text', () => {
    const text = 'same text'
    const hash = clipboardTextHash(text)

    expect(shouldSyncClipboardText(null, text)).toBe(true)
    expect(shouldSyncClipboardText(hash, text)).toBe(false)
    expect(shouldSyncClipboardText(hash, 'different')).toBe(true)
  })
})

describe('applyRemoteClipboardLocally', () => {
  it('applies remote clipboard text when write succeeds', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal('navigator', {
      clipboard: { writeText },
    })

    const result = await applyRemoteClipboardLocally('remote text')

    expect(result).toEqual({ applied: true })
    expect(writeText).toHaveBeenCalledWith('remote text')
    vi.unstubAllGlobals()
  })

  it('falls back when browser clipboard write fails', async () => {
    const writeText = vi.fn().mockRejectedValue(new DOMException('denied', 'NotAllowedError'))
    vi.stubGlobal('navigator', {
      clipboard: { writeText },
    })

    const result = await applyRemoteClipboardLocally('remote text')

    expect(result).toEqual({ applied: false, error: 'permission_denied' })
    vi.unstubAllGlobals()
  })
})

describe('ClipboardNotificationThrottler', () => {
  it('limits notifications to one every 3 seconds', () => {
    const throttler = new ClipboardNotificationThrottler()

    expect(throttler.resolve('first', 0)).toEqual({ message: 'first', display: true })
    expect(throttler.resolve('second', 1000)).toEqual({
      message: 'second',
      display: false,
    })
    expect(throttler.resolve('third', CLIPBOARD_NOTIFICATION_MIN_INTERVAL_MS)).toEqual({
      message: 'third',
      display: true,
    })
  })

  it('replaces the previous notification message without stacking', () => {
    const throttler = new ClipboardNotificationThrottler()
    const first = throttler.resolve('first', 0)
    const replaced = throttler.resolve('replacement', 500)

    expect(first.display).toBe(true)
    expect(replaced).toEqual({ message: 'replacement', display: false })
  })
})
