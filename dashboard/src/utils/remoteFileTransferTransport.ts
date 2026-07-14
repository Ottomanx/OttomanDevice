export interface TransferTransport {
  encodeChunk(data: ArrayBuffer): string | ArrayBuffer
  decodeChunk(value: unknown): Uint8Array | null
}

export class Base64TransferTransport implements TransferTransport {
  encodeChunk(data: ArrayBuffer): string {
    const bytes = new Uint8Array(data)
    let binary = ''
    for (let index = 0; index < bytes.length; index += 1) {
      binary += String.fromCharCode(bytes[index]!)
    }
    return btoa(binary)
  }

  decodeChunk(value: unknown): Uint8Array | null {
    if (typeof value !== 'string' || !value) {
      return null
    }
    try {
      const binary = atob(value)
      const bytes = new Uint8Array(binary.length)
      for (let index = 0; index < binary.length; index += 1) {
        bytes[index] = binary.charCodeAt(index)
      }
      return bytes
    } catch {
      return null
    }
  }
}

export class BinaryTransferTransport implements TransferTransport {
  encodeChunk(data: ArrayBuffer): ArrayBuffer {
    return data
  }

  decodeChunk(value: unknown): Uint8Array | null {
    if (value instanceof ArrayBuffer) {
      return new Uint8Array(value)
    }
    if (ArrayBuffer.isView(value)) {
      return new Uint8Array(value.buffer, value.byteOffset, value.byteLength)
    }
    return null
  }
}

export interface BandwidthLimiter {
  acquire(nbytes: number): Promise<void>
  report(nbytes: number): Promise<void>
}

export class NoOpBandwidthLimiter implements BandwidthLimiter {
  async acquire(_nbytes: number): Promise<void> {
    return
  }

  async report(_nbytes: number): Promise<void> {
    return
  }
}

export interface ChunkSizeStrategy {
  chunkSize(): number
  onChunkSent?(nbytes: number, elapsedMs: number): void
}

export class FixedChunkSizeStrategy implements ChunkSizeStrategy {
  private readonly size: number

  constructor(size: number) {
    if (size <= 0) {
      throw new Error('chunk size must be positive')
    }
    this.size = size
  }

  chunkSize(): number {
    return this.size
  }
}
