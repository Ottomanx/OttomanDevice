import { supabase } from '../lib/supabase'
import type { DeviceCommand, DeviceCommandType } from '../types/device'

const COMMAND_STATUS_PENDING = 'PENDING'

export async function createDeviceCommand(
  deviceId: string,
  command: DeviceCommandType,
): Promise<DeviceCommand> {
  const { data, error } = await supabase
    .from('device_commands')
    .insert({
      device_id: deviceId,
      command,
      status: COMMAND_STATUS_PENDING,
    })
    .select('*')
    .single()

  if (error) {
    throw new Error(error.message)
  }

  return data as DeviceCommand
}

export async function fetchDeviceCommand(commandId: string): Promise<DeviceCommand> {
  const { data, error } = await supabase
    .from('device_commands')
    .select('*')
    .eq('id', commandId)
    .single()

  if (error) {
    throw new Error(error.message)
  }

  return data as DeviceCommand
}
