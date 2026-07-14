import { supabase } from '../lib/supabase'
import type { ScreenshotItem } from '../types/device'

const SCREENSHOTS_BUCKET = 'screenshots'
const SCREENSHOT_LIMIT = 12

export async function listDeviceScreenshots(deviceId: string): Promise<ScreenshotItem[]> {
  const { data, error } = await supabase.storage.from(SCREENSHOTS_BUCKET).list(deviceId, {
    limit: SCREENSHOT_LIMIT,
    sortBy: { column: 'name', order: 'desc' },
  })

  if (error) {
    throw new Error(error.message)
  }

  return (data ?? [])
    .filter((item) => item.name.endsWith('.png'))
    .map((item) => {
      const { data: urlData } = supabase.storage
        .from(SCREENSHOTS_BUCKET)
        .getPublicUrl(`${deviceId}/${item.name}`)

      return {
        name: item.name,
        url: urlData.publicUrl,
        createdAt: item.created_at ?? item.updated_at ?? null,
      }
    })
}
