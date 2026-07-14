import { describe, expect, it } from 'vitest'

import { formatEta, formatTransferSpeed } from './fileTransfer'
import {
  Base64TransferTransport,
  FixedChunkSizeStrategy,
} from './remoteFileTransferTransport'

describe('remoteFileTransferTransport', () => {
  it('round-trips base64 chunks', () => {
    const transport = new Base64TransferTransport()
    const bytes = new Uint8Array([1, 2, 3, 4])
    const encoded = transport.encodeChunk(bytes.buffer)
    expect(typeof encoded).toBe('string')
    expect(transport.decodeChunk(encoded)?.length).toBe(4)
  })

  it('uses configurable chunk size strategy', () => {
    const strategy = new FixedChunkSizeStrategy(131072)
    expect(strategy.chunkSize()).toBe(131072)
  })
})

describe('fileTransfer formatting', () => {
  it('formats speed and eta', () => {
    expect(formatTransferSpeed(2048)).toContain('KB/s')
    expect(formatEta(90)).toContain('m')
  })
})
