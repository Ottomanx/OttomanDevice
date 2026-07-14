import { useState } from 'react'

import type { DeviceGroup, InventoryDevice } from '../types/inventory'
import { getDeviceDisplayName } from '../utils/inventoryQuery'
import { formatPercent, formatRelativeTime } from '../utils/format'
import { getStatusLabel } from '../utils/deviceStatus'
import { StatusBadge } from './StatusBadge'

interface InventoryTableProps {
  devices: InventoryDevice[]
  groups: DeviceGroup[]
  isLoading: boolean
  onAssignGroup: (deviceId: string, groupId: string | null) => Promise<void>
  onAssignTags: (deviceId: string, currentTags: string[], nextTags: string[]) => Promise<void>
  onCreateGroup: (name: string) => Promise<void>
}

export function InventoryTable({
  devices,
  groups,
  isLoading,
  onAssignGroup,
  onAssignTags,
  onCreateGroup,
}: InventoryTableProps) {
  if (isLoading && devices.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-800 bg-slate-900/40 px-6 py-16 text-center text-slate-400">
        Loading inventory…
      </div>
    )
  }

  if (devices.length === 0) {
    return (
      <div className="rounded-2xl border border-dashed border-slate-800 bg-slate-900/40 px-6 py-16 text-center text-slate-400">
        No devices match the current search and filters.
      </div>
    )
  }

  return (
    <div className="overflow-x-auto rounded-2xl border border-slate-800 bg-slate-900/70">
      <table className="min-w-full divide-y divide-slate-800 text-left text-sm">
        <thead className="bg-slate-950/70 text-xs uppercase tracking-wide text-slate-500">
          <tr>
            <th className="px-4 py-3">Device name</th>
            <th className="px-4 py-3">Status</th>
            <th className="px-4 py-3">Last seen</th>
            <th className="px-4 py-3">Firmware</th>
            <th className="px-4 py-3">OS</th>
            <th className="px-4 py-3">CPU</th>
            <th className="px-4 py-3">RAM</th>
            <th className="px-4 py-3">IP address</th>
            <th className="px-4 py-3">Tags</th>
            <th className="px-4 py-3">Group</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800 text-slate-200">
          {devices.map((device) => (
            <InventoryRow
              key={device.device_id}
              device={device}
              groups={groups}
              onAssignGroup={onAssignGroup}
              onAssignTags={onAssignTags}
              onCreateGroup={onCreateGroup}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}

interface InventoryRowProps {
  device: InventoryDevice
  groups: DeviceGroup[]
  onAssignGroup: (deviceId: string, groupId: string | null) => Promise<void>
  onAssignTags: (deviceId: string, currentTags: string[], nextTags: string[]) => Promise<void>
  onCreateGroup: (name: string) => Promise<void>
}

function InventoryRow({ device, groups, onAssignGroup, onAssignTags, onCreateGroup }: InventoryRowProps) {
  const [isSavingGroup, setIsSavingGroup] = useState(false)
  const [isSavingTags, setIsSavingTags] = useState(false)
  const [tagInput, setTagInput] = useState('')

  const handleGroupChange = async (groupId: string) => {
    setIsSavingGroup(true)
    try {
      await onAssignGroup(device.device_id, groupId || null)
    } finally {
      setIsSavingGroup(false)
    }
  }

  const handleAddTag = async () => {
    const nextTag = tagInput.trim()
    if (!nextTag || device.tags.includes(nextTag)) {
      setTagInput('')
      return
    }

    setIsSavingTags(true)
    try {
      await onAssignTags(device.device_id, device.tags, [...device.tags, nextTag])
      setTagInput('')
    } finally {
      setIsSavingTags(false)
    }
  }

  const handleRemoveTag = async (tag: string) => {
    setIsSavingTags(true)
    try {
      await onAssignTags(
        device.device_id,
        device.tags,
        device.tags.filter((current) => current !== tag),
      )
    } finally {
      setIsSavingTags(false)
    }
  }

  const handleCreateGroup = async () => {
    const name = window.prompt('New group name')
    if (!name) {
      return
    }

    setIsSavingGroup(true)
    try {
      await onCreateGroup(name)
    } finally {
      setIsSavingGroup(false)
    }
  }

  return (
    <tr className="align-top hover:bg-slate-950/40">
      <td className="px-4 py-3">
        <p className="font-medium text-white">{getDeviceDisplayName(device)}</p>
        <p className="font-mono text-xs text-slate-500">{device.device_id}</p>
      </td>
      <td className="px-4 py-3">
        <StatusBadge status={device.online_status} />
        <p className="mt-1 text-xs text-slate-500">{getStatusLabel(device.online_status)}</p>
      </td>
      <td className="px-4 py-3">{formatRelativeTime(device.last_online_at)}</td>
      <td className="px-4 py-3">{device.firmware_version ?? '—'}</td>
      <td className="px-4 py-3">{device.operating_system ?? '—'}</td>
      <td className="px-4 py-3">{formatPercent(device.cpu_usage)}</td>
      <td className="px-4 py-3">{formatPercent(device.ram_usage)}</td>
      <td className="px-4 py-3">{device.local_ip ?? '—'}</td>
      <td className="px-4 py-3">
        <div className="flex flex-wrap gap-1">
          {device.tags.map((tag) => (
            <button
              key={tag}
              type="button"
              disabled={isSavingTags}
              onClick={() => void handleRemoveTag(tag)}
              className="rounded-full border border-indigo-500/30 bg-indigo-500/10 px-2 py-0.5 text-xs text-indigo-200 transition hover:border-rose-500/40 hover:bg-rose-500/10 hover:text-rose-200 disabled:opacity-50"
              title="Remove tag"
            >
              {tag} 뿯½
            </button>
          ))}
        </div>
        <div className="mt-2 flex gap-2">
          <input
            type="text"
            value={tagInput}
            onChange={(event) => setTagInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault()
                void handleAddTag()
              }
            }}
            placeholder="Add tag"
            className="w-full min-w-[120px] rounded-lg border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-white outline-none focus:border-indigo-400"
          />
          <button
            type="button"
            disabled={isSavingTags}
            onClick={() => void handleAddTag()}
            className="rounded-lg border border-slate-700 px-2 py-1 text-xs text-slate-200 hover:border-indigo-400 disabled:opacity-50"
          >
            Add
          </button>
        </div>
      </td>
      <td className="px-4 py-3">
        <div className="flex min-w-[160px] flex-col gap-2">
          <select
            value={device.group_id ?? ''}
            disabled={isSavingGroup}
            onChange={(event) => void handleGroupChange(event.target.value)}
            className="rounded-lg border border-slate-700 bg-slate-950 px-2 py-1 text-xs text-white outline-none focus:border-indigo-400 disabled:opacity-50"
          >
            <option value="">No group</option>
            {groups.map((group) => (
              <option key={group.id} value={group.id}>
                {group.name}
              </option>
            ))}
          </select>
          <button
            type="button"
            disabled={isSavingGroup}
            onClick={() => void handleCreateGroup()}
            className="rounded-lg border border-slate-700 px-2 py-1 text-xs text-slate-300 hover:border-indigo-400 hover:text-white disabled:opacity-50"
          >
            New group
          </button>
        </div>
      </td>
    </tr>
  )
}
