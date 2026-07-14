import { requireAccessToken } from '../services/auth'
import { supabase } from '../lib/supabase'

export interface RemoteDesktopSessionToken {
  token: string
  session_id: string
  issued_at: number
  expires_at: number
}

export async function requestRemoteDesktopSessionToken(
  deviceId: string,
): Promise<RemoteDesktopSessionToken> {
  const accessToken = await requireAccessToken()

  const { data, error } = await supabase.functions.invoke('remote-desktop-session', {
    body: { device_id: deviceId },
    headers: {
      Authorization: `Bearer ${accessToken}`,
    },
  })

  if (error) {
    throw new Error('Failed to request remote desktop session token')
  }

  if (
    !data ||
    typeof data.token !== 'string' ||
    typeof data.session_id !== 'string' ||
    typeof data.issued_at !== 'number' ||
    typeof data.expires_at !== 'number'
  ) {
    throw new Error('Invalid remote desktop session token response')
  }

  return {
    token: data.token,
    session_id: data.session_id,
    issued_at: data.issued_at,
    expires_at: data.expires_at,
  }
}

export function isSessionTokenExpired(
  expiresAt: number,
  skewSeconds = 5,
): boolean {
  const now = Math.floor(Date.now() / 1000)
  return now >= expiresAt - skewSeconds
}