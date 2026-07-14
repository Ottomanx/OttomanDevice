import { createClient } from 'npm:@supabase/supabase-js@2'
import * as jose from 'npm:jose'

const corsHeaders = {
  'Access-Control-Allow-Origin': '*',
  'Access-Control-Allow-Headers': 'authorization, x-client-info, apikey, content-type',
  'Access-Control-Allow-Methods': 'POST, OPTIONS',
}

const TOKEN_TTL_SECONDS = 60

interface SessionRequestBody {
  device_id?: string
}

function withCorsHeaders(headers: Record<string, string> = {}): HeadersInit {
  return {
    ...corsHeaders,
    ...headers,
  }
}

function corsResponse(
  body: BodyInit | null,
  init: ResponseInit = {},
): Response {
  const headers = withCorsHeaders(
    Object.fromEntries(new Headers(init.headers).entries()),
  )

  return new Response(body, {
    ...init,
    headers,
  })
}

function jsonResponse(body: unknown, status = 200): Response {
  return corsResponse(JSON.stringify(body), {
    status,
    headers: {
      'Content-Type': 'application/json',
    },
  })
}

Deno.serve(async (req) => {
  try {
    if (req.method === 'OPTIONS') {
      return corsResponse(null, { status: 204 })
    }

    if (req.method !== 'POST') {
      return jsonResponse({ error: 'Method not allowed' }, 405)
    }

    const supabaseUrl = Deno.env.get('SUPABASE_URL')
    const supabaseAnonKey = Deno.env.get('SUPABASE_ANON_KEY')
    const supabaseServiceRoleKey = Deno.env.get('SUPABASE_SERVICE_ROLE_KEY')
    const jwtSecret = Deno.env.get('REMOTE_DESKTOP_JWT_SECRET')

    if (!supabaseUrl || !supabaseAnonKey || !supabaseServiceRoleKey || !jwtSecret) {
      return jsonResponse({ error: 'Server misconfigured' }, 500)
    }

    const authHeader = req.headers.get('Authorization')
    if (!authHeader?.startsWith('Bearer ')) {
      return jsonResponse({ error: 'Unauthorized' }, 401)
    }

    const userClient = createClient(supabaseUrl, supabaseAnonKey, {
      global: { headers: { Authorization: authHeader } },
    })

    const accessToken = authHeader.replace('Bearer ', '')
    const {
      data: { user },
      error: userError,
    } = await userClient.auth.getUser(accessToken)

    if (userError || !user) {
      return jsonResponse({ error: 'Unauthorized' }, 401)
    }

    let body: SessionRequestBody
    try {
      body = (await req.json()) as SessionRequestBody
    } catch {
      return jsonResponse({ error: 'Invalid request body' }, 400)
    }

    const deviceId = body.device_id?.trim()
    if (!deviceId) {
      return jsonResponse({ error: 'device_id is required' }, 400)
    }

    const adminClient = createClient(supabaseUrl, supabaseServiceRoleKey)
    const { data: device, error: deviceError } = await adminClient
      .from('devices_enhanced')
      .select('device_id')
      .eq('device_id', deviceId)
      .maybeSingle()

    if (deviceError || !device) {
      return jsonResponse({ error: 'Device not found' }, 404)
    }

    const { data: permissionsData, error: permissionsError } = await adminClient.rpc(
      'get_user_permissions',
      { p_user_id: user.id },
    )

    if (permissionsError) {
      return jsonResponse({ error: 'Failed to load permissions' }, 500)
    }

    const permissions = Array.isArray(permissionsData)
      ? permissionsData.filter((value): value is string => typeof value === 'string')
      : []

    if (!permissions.includes('desktop')) {
      return jsonResponse({ error: 'Forbidden' }, 403)
    }

    const issuedAt = Math.floor(Date.now() / 1000)
    const expiresAt = issuedAt + TOKEN_TTL_SECONDS
    const sessionId = crypto.randomUUID()
    const jti = crypto.randomUUID()

    const signingKey = new TextEncoder().encode(jwtSecret)
    const controllerName =
      (typeof user.user_metadata?.full_name === 'string' && user.user_metadata.full_name) ||
      user.email ||
      user.id

    const token = await new jose.SignJWT({
      device_id: deviceId,
      session_id: sessionId,
      permissions: [...permissions].sort(),
      user_id: user.id,
      controller_name: controllerName,
    })
      .setProtectedHeader({ alg: 'HS256' })
      .setIssuedAt(issuedAt)
      .setExpirationTime(expiresAt)
      .setJti(jti)
      .sign(signingKey)

    return jsonResponse({
      token,
      session_id: sessionId,
      issued_at: issuedAt,
      expires_at: expiresAt,
    })
  } catch {
    return jsonResponse({ error: 'Internal server error' }, 500)
  }
})
