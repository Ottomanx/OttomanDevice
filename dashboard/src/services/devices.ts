import { supabase } from '../lib/supabase'
import type { DeviceEnhanced } from '../types/device'
import { dedupeDevices } from '../utils/deviceStatus'

export async function fetchDevices(): Promise<DeviceEnhanced[]> {
  const { data, error } = await supabase
    .from('devices_enhanced')
    .select('*')
    .order('last_online_at', { ascending: false, nullsFirst: false })

  if (error) {
    throw new Error(error.message)
  }

  return dedupeDevices((data ?? []) as DeviceEnhanced[])
}
