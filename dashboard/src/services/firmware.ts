import { supabase } from '../lib/supabase'
import type { FirmwarePackage, FirmwareRelease, FirmwareUploadInput } from '../types/firmware'
import { computeFileSha256 } from '../utils/firmwareHash'

const FIRMWARE_BUCKET = 'firmware'

interface FirmwareReleaseRow {
  id: string
  package_id: string
  release_notes: string
  published: boolean
  published_at: string | null
  created_at: string
  firmware_packages:
    | {
        id: string
        version: string
        file_name: string
        storage_path: string
        sha256: string
        signature: string
        file_size_bytes: number
        created_at: string
      }
    | {
        id: string
        version: string
        file_name: string
        storage_path: string
        sha256: string
        signature: string
        file_size_bytes: number
        created_at: string
      }[]
    | null
}

function resolvePackage(packageData: FirmwareReleaseRow['firmware_packages']): FirmwarePackage {
  if (!packageData) {
    throw new Error('Firmware package metadata is missing')
  }

  if (Array.isArray(packageData)) {
    if (!packageData[0]) {
      throw new Error('Firmware package metadata is missing')
    }
    return packageData[0]
  }

  return packageData
}

function mapReleaseRow(row: FirmwareReleaseRow): FirmwareRelease {
  return {
    id: row.id,
    package_id: row.package_id,
    release_notes: row.release_notes,
    published: row.published,
    published_at: row.published_at,
    created_at: row.created_at,
    package: resolvePackage(row.firmware_packages),
  }
}

export async function fetchFirmwareReleases(): Promise<FirmwareRelease[]> {
  const { data, error } = await supabase
    .from('firmware_releases')
    .select(
      `
        id,
        package_id,
        release_notes,
        published,
        published_at,
        created_at,
        firmware_packages (
          id,
          version,
          file_name,
          storage_path,
          sha256,
          signature,
          file_size_bytes,
          created_at
        )
      `,
    )
    .order('created_at', { ascending: false })

  if (error) {
    throw new Error(error.message)
  }

  return ((data ?? []) as unknown as FirmwareReleaseRow[]).map(mapReleaseRow)
}

async function signFirmwareHash(sha256: string): Promise<string> {
  const { data, error } = await supabase.rpc('sign_firmware_hash', { p_sha256: sha256 })

  if (error) {
    throw new Error(error.message)
  }

  if (typeof data !== 'string') {
    throw new Error('Invalid firmware signature response')
  }

  return data
}

export async function uploadFirmwarePackage(input: FirmwareUploadInput): Promise<FirmwareRelease> {
  const version = input.version.trim()
  if (!version) {
    throw new Error('Version is required')
  }

  const sha256 = await computeFileSha256(input.file)
  const signature = await signFirmwareHash(sha256)
  const storagePath = `${version}/${input.file.name}`

  const { error: uploadError } = await supabase.storage
    .from(FIRMWARE_BUCKET)
    .upload(storagePath, input.file, {
      upsert: true,
      contentType: input.file.type || 'application/octet-stream',
    })

  if (uploadError) {
    throw new Error(uploadError.message)
  }

  const { data: packageRow, error: packageError } = await supabase
    .from('firmware_packages')
    .insert({
      version,
      file_name: input.file.name,
      storage_path: storagePath,
      sha256,
      signature,
      file_size_bytes: input.file.size,
    })
    .select('id')
    .single()

  if (packageError) {
    throw new Error(packageError.message)
  }

  const { data: releaseRow, error: releaseError } = await supabase
    .from('firmware_releases')
    .insert({
      package_id: packageRow.id,
      release_notes: input.releaseNotes.trim(),
      published: false,
    })
    .select(
      `
        id,
        package_id,
        release_notes,
        published,
        published_at,
        created_at,
        firmware_packages (
          id,
          version,
          file_name,
          storage_path,
          sha256,
          signature,
          file_size_bytes,
          created_at
        )
      `,
    )
    .single()

  if (releaseError) {
    throw new Error(releaseError.message)
  }

  return mapReleaseRow(releaseRow as unknown as FirmwareReleaseRow)
}

export async function setFirmwareReleasePublished(
  releaseId: string,
  published: boolean,
): Promise<void> {
  const { error } = await supabase
    .from('firmware_releases')
    .update({
      published,
      published_at: published ? new Date().toISOString() : null,
    })
    .eq('id', releaseId)

  if (error) {
    throw new Error(error.message)
  }
}
