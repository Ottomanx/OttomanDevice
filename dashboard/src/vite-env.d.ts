/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SUPABASE_URL: string
  readonly VITE_SUPABASE_ANON_KEY: string
  readonly VITE_REMOTE_DESKTOP_HOST?: string
  readonly VITE_REMOTE_DESKTOP_PORT?: string
  readonly VITE_REMOTE_DESKTOP_PATH?: string
  readonly VITE_REMOTE_DESKTOP_SUBPROTOCOL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
