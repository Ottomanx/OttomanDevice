import { supabase } from '../lib/supabase'
import type { DeviceEnhanced } from '../types/device'
import type { DeviceGroup, InventoryDevice } from '../types/inventory'
import { dedupeDevices } from '../utils/deviceStatus'
import { computeTagSyncPlan, normalizeInventoryDevice } from '../utils/inventoryQuery'

interface DeviceTagRow {
  device_id: string
  tag: string
}

interface InventoryDeviceRow extends DeviceEnhanced {
  device_group_members:
    | { group_id: string; device_groups: { id: string; name: string } | null }
    | { group_id: string; device_groups: { id: string; name: string } | null }[]
    | null
  device_tags: DeviceTagRow[] | null
}

function resolveGroupFromRow(
  members: InventoryDeviceRow['device_group_members'],
): { groupId: string | null; groupName: string | null } {
  if (!members) {
    return { groupId: null, groupName: null }
  }

  const member = Array.isArray(members) ? members[0] : members
  if (!member) {
    return { groupId: null, groupName: null }
  }

  const group = member.device_groups
  if (!group || Array.isArray(group)) {
    return { groupId: member.group_id, groupName: null }
  }

  return { groupId: group.id, groupName: group.name }
}

export function mapInventoryRows(rows: InventoryDeviceRow[]): InventoryDevice[] {
  return rows.map((row) => {
    const { groupId, groupName } = resolveGroupFromRow(row.device_group_members)
    const tags = (row.device_tags ?? []).map((entry) => entry.tag)
    const { device_group_members: _members, device_tags: _tags, ...device } = row
    return normalizeInventoryDevice(device, groupId, groupName, tags)
  })
}

export async function fetchInventoryDevices(): Promise<InventoryDevice[]> {
  const { data, error } = await supabase
    .from('devices_enhanced')
    .select(
      `
        *,
        device_group_members(group_id, device_groups(id, name)),
        device_tags(tag)
      `,
    )
    .order('last_online_at', { ascending: false, nullsFirst: false })

  if (error) {
    throw new Error(error.message)
  }

  return mapInventoryRows(dedupeDevices((data ?? []) as InventoryDeviceRow[]))
}

export async function fetchDeviceGroups(): Promise<DeviceGroup[]> {
  const { data, error } = await supabase
    .from('device_groups')
    .select('id, name, created_at')
    .order('name', { ascending: true })

  if (error) {
    throw new Error(error.message)
  }

  return (data ?? []) as DeviceGroup[]
}

export async function fetchInventoryTags(): Promise<string[]> {
  const { data, error } = await supabase.from('device_tags').select('tag').order('tag', { ascending: true })

  if (error) {
    throw new Error(error.message)
  }

  const uniqueTags = new Set<string>()
  for (const row of data ?? []) {
    if (row.tag) {
      uniqueTags.add(row.tag)
    }
  }

  return [...uniqueTags].sort((a, b) => a.localeCompare(b))
}

export async function createDeviceGroup(name: string): Promise<DeviceGroup> {
  const trimmed = name.trim()
  if (!trimmed) {
    throw new Error('Group name is required')
  }

  const { data, error } = await supabase
    .from('device_groups')
    .insert({ name: trimmed })
    .select('id, name, created_at')
    .single()

  if (error) {
    throw new Error(error.message)
  }

  return data as DeviceGroup
}

export async function assignDeviceGroup(deviceId: string, groupId: string | null): Promise<void> {
  if (!groupId) {
    const { error } = await supabase.from('device_group_members').delete().eq('device_id', deviceId)
    if (error) {
      throw new Error(error.message)
    }
    return
  }

  const { error } = await supabase
    .from('device_group_members')
    .upsert({ device_id: deviceId, group_id: groupId }, { onConflict: 'device_id' })

  if (error) {
    throw new Error(error.message)
  }
}

export async function assignDeviceTags(deviceId: string, currentTags: string[], nextTags: string[]): Promise<void> {
  const { toAdd, toRemove } = computeTagSyncPlan(currentTags, nextTags)

  if (toRemove.length > 0) {
    const { error } = await supabase
      .from('device_tags')
      .delete()
      .eq('device_id', deviceId)
      .in('tag', toRemove)

    if (error) {
      throw new Error(error.message)
    }
  }

  if (toAdd.length > 0) {
    const { error } = await supabase
      .from('device_tags')
      .insert(toAdd.map((tag) => ({ device_id: deviceId, tag })))

    if (error) {
      throw new Error(error.message)
    }
  }
}
