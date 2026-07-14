import {
  loadLastSelectedMonitor,
  saveLastSelectedMonitor,
} from './remoteMonitorStore'

export type MonitorOrientation = 'landscape' | 'portrait'

export interface MonitorView {
  number: number
  width: number
  height: number
  isPrimary: boolean
  orientation: MonitorOrientation
}

export type SendMessageFn = (type: string, payload?: Record<string, unknown>) => void

interface ParsedMonitorList {
  monitors: MonitorView[]
  idByNumber: Map<number, string>
  selectedNumber: number | null
}

export class RemoteMonitorController {
  private sendMessage: SendMessageFn
  private deviceId: string | null = null
  private monitors: MonitorView[] = []
  private idByNumber = new Map<number, string>()
  private selectedNumber: number | null = null
  private switchInProgress = false

  onMonitorsChange: ((monitors: MonitorView[], selectedNumber: number | null) => void) | null =
    null
  onSwitchStateChange: ((inProgress: boolean) => void) | null = null

  constructor(sendMessage: SendMessageFn) {
    this.sendMessage = sendMessage
  }

  setSendMessage(sendMessage: SendMessageFn): void {
    this.sendMessage = sendMessage
  }

  setDeviceId(deviceId: string | null): void {
    this.deviceId = deviceId
  }

  reset(): void {
    this.monitors = []
    this.idByNumber.clear()
    this.selectedNumber = null
    this.switchInProgress = false
    this.notifyMonitors()
    this.onSwitchStateChange?.(false)
  }

  getMonitors(): MonitorView[] {
    return this.monitors
  }

  getSelectedNumber(): number | null {
    return this.selectedNumber
  }

  isSwitchInProgress(): boolean {
    return this.switchInProgress
  }

  handleMessage(type: string, payload: Record<string, unknown>): void {
    switch (type) {
      case 'MONITOR_LIST':
        this.applyMonitorList(payload)
        break
      case 'MONITOR_SELECT':
        this.handleSelectAck(payload)
        break
      case 'MONITOR_CHANGED':
        this.applyMonitorList(payload)
        break
      default:
        break
    }
  }

  selectMonitorByNumber(monitorNumber: number): void {
    const monitorId = this.idByNumber.get(monitorNumber)
    if (!monitorId || this.selectedNumber === monitorNumber) {
      return
    }
    this.switchInProgress = true
    this.onSwitchStateChange?.(true)
    this.sendMessage('MONITOR_SELECT', { monitor_id: monitorId })
  }

  restorePreferredMonitor(): void {
    if (!this.deviceId || this.monitors.length === 0) {
      return
    }
    const stored = loadLastSelectedMonitor(this.deviceId)
    if (stored !== null && this.idByNumber.has(stored)) {
      this.selectMonitorByNumber(stored)
      return
    }
    const primary = this.monitors.find((monitor) => monitor.isPrimary)
    if (primary && primary.number !== this.selectedNumber) {
      this.selectMonitorByNumber(primary.number)
    }
  }

  private applyMonitorList(payload: Record<string, unknown>): void {
    const parsed = parseMonitorListPayload(payload)
    this.monitors = parsed.monitors
    this.idByNumber = parsed.idByNumber
    this.selectedNumber = parsed.selectedNumber
    this.notifyMonitors()
  }

  private handleSelectAck(payload: Record<string, unknown>): void {
    this.switchInProgress = false
    this.onSwitchStateChange?.(false)
    const accepted = payload.accepted === true
    if (!accepted) {
      return
    }
    const number = typeof payload.number === 'number' ? payload.number : null
    if (number !== null) {
      this.selectedNumber = number
      if (this.deviceId) {
        saveLastSelectedMonitor(this.deviceId, number)
      }
      this.notifyMonitors()
    }
  }

  private notifyMonitors(): void {
    this.onMonitorsChange?.(this.monitors, this.selectedNumber)
  }
}

export function parseMonitorListPayload(payload: Record<string, unknown>): ParsedMonitorList {
  const rawMonitors = payload.monitors
  const monitors: MonitorView[] = []
  const idByNumber = new Map<number, string>()
  let selectedNumber: number | null = null

  const selectedId = typeof payload.selected_id === 'string' ? payload.selected_id : null

  if (Array.isArray(rawMonitors)) {
    for (const entry of rawMonitors) {
      if (!entry || typeof entry !== 'object') {
        continue
      }
      const record = entry as Record<string, unknown>
      const number = typeof record.number === 'number' ? record.number : null
      const width = typeof record.width === 'number' ? record.width : null
      const height = typeof record.height === 'number' ? record.height : null
      const id = typeof record.id === 'string' ? record.id : null
      if (number === null || width === null || height === null || !id) {
        continue
      }
      const orientation = record.orientation === 'portrait' ? 'portrait' : 'landscape'
      monitors.push({
        number,
        width,
        height,
        isPrimary: record.is_primary === true,
        orientation,
      })
      idByNumber.set(number, id)
      if (selectedId === id) {
        selectedNumber = number
      }
    }
  }

  monitors.sort((left, right) => left.number - right.number)
  return { monitors, idByNumber, selectedNumber }
}

export function formatMonitorResolution(width: number, height: number): string {
  return `${width}\u00d7${height}`
}
