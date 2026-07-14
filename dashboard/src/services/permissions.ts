import { supabase } from '../lib/supabase'
import { normalizePermissions, type PermissionKey } from '../types/permissions'

export async function fetchUserPermissions(userId: string): Promise<PermissionKey[]> {
  const { data, error } = await supabase.rpc('get_user_permissions', {
    p_user_id: userId,
  })

  if (error) {
    throw new Error('Failed to load user permissions')
  }

  return normalizePermissions(data)
}