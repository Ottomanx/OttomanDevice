import { supabase } from '../lib/supabase'

const DESKTOP_PREVIEW_BUCKET = 'desktop-preview'
const LATEST_FRAME_NAME = 'latest.jpg'

export function getDesktopPreviewUrl(deviceId: string, cacheBust: number): string {
  const { data } = supabase.storage
    .from(DESKTOP_PREVIEW_BUCKET)
    .getPublicUrl(`${deviceId}/${LATEST_FRAME_NAME}`)

  return `${data.publicUrl}?t=${cacheBust}`
}
