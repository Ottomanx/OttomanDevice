from pathlib import Path

p = Path(__file__).resolve().parents[1] / "dashboard" / "src" / "hooks" / "useRemoteDesktop.ts"
text = p.read_text(encoding="utf-8")

replacements = [
    (
        "import {\n  assembleDownloadChunks,\n  createTransferId,\n  readFileInChunks,\n  triggerBrowserDownload,\n  type FileTransferProgress,\n} from '../utils/fileTransfer'",
        "import {\n  type FileTransferProgress,\n  type TransferHistoryEntry,\n} from '../utils/fileTransfer'\nimport { RemoteFileTransferController } from '../utils/remoteFileTransfer'",
    ),
    (
        "  fileTransferProgress: FileTransferProgress | null\n  uploadFile: (relativePath: string, file: File) => Promise<void>\n  downloadFile: (relativePath: string) => Promise<void>\n  cancelFileTransfer: (transferId: string) => void",
        "  fileTransferProgress: FileTransferProgress | null\n  transferHistory: TransferHistoryEntry[]\n  uploadFile: (relativePath: string, file: File) => Promise<void>\n  downloadFile: (relativePath: string) => Promise<void>\n  cancelFileTransfer: (transferId: string) => void\n  pauseFileTransfer: (transferId: string) => void\n  resumeFileTransfer: (transferId: string) => void\n  retryFileTransfer: (transferId: string) => void",
    ),
    (
        "  const [fileTransferProgress, setFileTransferProgress] = useState<FileTransferProgress | null>(\n    null,\n  )",
        "  const [fileTransferProgress, setFileTransferProgress] = useState<FileTransferProgress | null>(\n    null,\n  )\n  const [transferHistory, setTransferHistory] = useState<TransferHistoryEntry[]>([])",
    ),
    (
        "  const activeTransferIdRef = useRef<string | null>(null)\n  const downloadChunksRef = useRef<Map<string, Map<number, string>>>(new Map())\n  const downloadPathsRef = useRef<Map<string, string>>(new Map())",
        "  const fileTransferControllerRef = useRef<RemoteFileTransferController | null>(null)",
    ),
]

for old, new in replacements:
    if old not in text:
        raise SystemExit(f"missing block: {old[:60]}...")
    text = text.replace(old, new, 1)

# resetTransferState
old_reset = """  const resetTransferState = useCallback(() => {
    clipboardRequestRef.current = null
    activeTransferIdRef.current = null
    downloadChunksRef.current.clear()
    downloadPathsRef.current.clear()
    setFileTransferProgress(null)
  }, [])"""

new_reset = """  const resetTransferState = useCallback(() => {
    clipboardRequestRef.current = null
    fileTransferControllerRef.current?.reset()
    setFileTransferProgress(null)
    setTransferHistory([])
  }, [])"""

if old_reset not in text:
    raise SystemExit("missing resetTransferState")
text = text.replace(old_reset, new_reset, 1)

# Replace file transfer callbacks block
old_callbacks = """  const cancelFileTransfer = useCallback(
    (transferId: string) => {
      if (activeTransferIdRef.current === transferId) {
        activeTransferIdRef.current = null
      }
      sendMessage('FILE_UPLOAD', { transfer_id: transferId, cancel: true })
      sendMessage('FILE_DOWNLOAD', { transfer_id: transferId, cancel: true })
      downloadChunksRef.current.delete(transferId)
      downloadPathsRef.current.delete(transferId)
      setFileTransferProgress((current) =>
        current?.transferId === transferId
          ? { ...current, status: 'cancelled' }
          : current,
      )
    },
    [sendMessage],
  )

  const uploadFile = useCallback(
    async (relativePath: string, file: File) => {
      if (!remoteControlActive) {
        throw new Error('Remote desktop is not active')
      }

      const transferId = createTransferId()
      activeTransferIdRef.current = transferId
      setFileTransferProgress({
        transferId,
        direction: 'upload',
        transferred: 0,
        total: file.size,
        path: relativePath,
        status: 'active',
      })

      sendMessage('FILE_UPLOAD', {
        transfer_id: transferId,
        path: relativePath,
        size: file.size,
      })

      await readFileInChunks(file, async (chunk) => {
        if (activeTransferIdRef.current !== transferId) {
          return
        }
        sendMessage('FILE_UPLOAD', { transfer_id: transferId, chunk })
      })
    },
    [remoteControlActive, sendMessage],
  )

  const downloadFile = useCallback(
    async (relativePath: string) => {
      if (!remoteControlActive) {
        throw new Error('Remote desktop is not active')
      }

      const transferId = createTransferId()
      activeTransferIdRef.current = transferId
      downloadChunksRef.current.set(transferId, new Map())
      downloadPathsRef.current.set(transferId, relativePath)
      setFileTransferProgress({
        transferId,
        direction: 'download',
        transferred: 0,
        total: 0,
        path: relativePath,
        status: 'active',
      })

      sendMessage('FILE_DOWNLOAD', {
        transfer_id: transferId,
        path: relativePath,
      })
    },
    [remoteControlActive, sendMessage],
  )"""

new_callbacks = """  const getFileTransferController = useCallback(() => {
    if (!fileTransferControllerRef.current) {
      const controller = new RemoteFileTransferController(sendMessage)
      controller.onProgressChange = setFileTransferProgress
      controller.onHistoryChange = setTransferHistory
      fileTransferControllerRef.current = controller
    } else {
      fileTransferControllerRef.current.setSendMessage(sendMessage)
    }
    return fileTransferControllerRef.current
  }, [sendMessage])

  const cancelFileTransfer = useCallback(
    (transferId: string) => {
      getFileTransferController().cancelTransfer(transferId)
    },
    [getFileTransferController],
  )

  const pauseFileTransfer = useCallback(
    (transferId: string) => {
      getFileTransferController().pauseTransfer(transferId)
    },
    [getFileTransferController],
  )

  const resumeFileTransfer = useCallback(
    (transferId: string) => {
      getFileTransferController().resumeTransfer(transferId)
    },
    [getFileTransferController],
  )

  const retryFileTransfer = useCallback(
    (transferId: string) => {
      getFileTransferController().retryTransfer(transferId)
    },
    [getFileTransferController],
  )

  const uploadFile = useCallback(
    async (relativePath: string, file: File) => {
      if (!remoteControlActive) {
        throw new Error('Remote desktop is not active')
      }
      await getFileTransferController().uploadFile(relativePath, file)
    },
    [getFileTransferController, remoteControlActive],
  )

  const downloadFile = useCallback(
    async (relativePath: string) => {
      if (!remoteControlActive) {
        throw new Error('Remote desktop is not active')
      }
      getFileTransferController().downloadFile(relativePath)
    },
    [getFileTransferController, remoteControlActive],
  )"""

if old_callbacks not in text:
    raise SystemExit("missing file transfer callbacks")
text = text.replace(old_callbacks, new_callbacks, 1)

# Replace FILE_* message handlers with controller delegation
old_handlers = """        case 'FILE_PROGRESS': {
          const transferId =
            typeof payload.transfer_id === 'string' ? payload.transfer_id : null
          if (!transferId) {
            break
          }
          const transferred =
            typeof payload.transferred === 'number' ? payload.transferred : 0
          const total = typeof payload.total === 'number' ? payload.total : 0
          const direction = payload.direction === 'download' ? 'download' : 'upload'
          setFileTransferProgress((current) => {
            if (current?.transferId !== transferId) {
              return {
                transferId,
                direction,
                transferred,
                total,
                path: downloadPathsRef.current.get(transferId) ?? '',
                status: 'active',
              }
            }
            return {
              ...current,
              transferred,
              total,
              direction,
              status: 'active',
            }
          })
          break
        }
        case 'FILE_COMPLETE': {
          const transferId =
            typeof payload.transfer_id === 'string' ? payload.transfer_id : null
          if (!transferId) {
            break
          }
          const path = typeof payload.path === 'string' ? payload.path : ''
          const size = typeof payload.size === 'number' ? payload.size : 0
          if (activeTransferIdRef.current === transferId) {
            activeTransferIdRef.current = null
          }
          setFileTransferProgress({
            transferId,
            direction:
              downloadPathsRef.current.has(transferId) &&
              downloadChunksRef.current.has(transferId)
                ? 'download'
                : 'upload',
            transferred: size,
            total: size,
            path,
            status: 'complete',
          })
          downloadChunksRef.current.delete(transferId)
          downloadPathsRef.current.delete(transferId)
          break
        }
        case 'FILE_ERROR': {
          const transferId =
            typeof payload.transfer_id === 'string' ? payload.transfer_id : null
          const code = typeof payload.code === 'string' ? payload.code : 'ERROR'
          const errorMessage =
            typeof payload.message === 'string' ? payload.message : 'Transfer failed'
          if (transferId && activeTransferIdRef.current === transferId) {
            activeTransferIdRef.current = null
          }
          if (transferId) {
            downloadChunksRef.current.delete(transferId)
            downloadPathsRef.current.delete(transferId)
          }
          setFileTransferProgress((current) =>
            transferId && current?.transferId === transferId
              ? {
                  ...current,
                  status: code === 'CANCELLED' ? 'cancelled' : 'error',
                  errorMessage,
                }
              : current,
          )
          break
        }
        case 'FILE_DOWNLOAD': {
          const transferId =
            typeof payload.transfer_id === 'string' ? payload.transfer_id : null
          const chunk = typeof payload.chunk === 'string' ? payload.chunk : null
          const offset = typeof payload.offset === 'number' ? payload.offset : 0
          const isFinal = payload.final === true
          if (!transferId || !chunk) {
            break
          }

          const chunks = downloadChunksRef.current.get(transferId) ?? new Map()
          chunks.set(offset, chunk)
          downloadChunksRef.current.set(transferId, chunks)

          if (!isFinal) {
            break
          }

          const relativePath = downloadPathsRef.current.get(transferId) ?? 'download'
          const data = assembleDownloadChunks(chunks)
          const filename = relativePath.split('/').pop() || 'download'
          triggerBrowserDownload(filename, data)
          break
        }"""

new_handlers = """        case 'FILE_PROGRESS':
        case 'FILE_COMPLETE':
        case 'FILE_ERROR':
        case 'FILE_DOWNLOAD': {
          getFileTransferController().handleMessage(message.type, payload)
          break
        }"""

if old_handlers not in text:
    raise SystemExit("missing FILE handlers")
text = text.replace(old_handlers, new_handlers, 1)

# Add resume on stream start
old_stream = """        case 'START_STREAM': {
          if (payload.streaming === true) {
            manager.markConnected()
          }"""

new_stream = """        case 'START_STREAM': {
          if (payload.streaming === true) {
            manager.markConnected()
            getFileTransferController().resumePendingAfterReconnect()
          }"""

if old_stream not in text:
    raise SystemExit("missing START_STREAM handler")
text = text.replace(old_stream, new_stream, 1)

# Return object
old_return = """    fileTransferProgress,
    uploadFile,
    downloadFile,
    cancelFileTransfer,"""

new_return = """    fileTransferProgress,
    transferHistory,
    uploadFile,
    downloadFile,
    cancelFileTransfer,
    pauseFileTransfer,
    resumeFileTransfer,
    retryFileTransfer,"""

if old_return not in text:
    raise SystemExit("missing return fields")
text = text.replace(old_return, new_return, 1)

p.write_text(text, encoding="utf-8")
print("patched useRemoteDesktop.ts")
