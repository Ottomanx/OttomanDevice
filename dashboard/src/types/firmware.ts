export interface FirmwarePackage {
  id: string
  version: string
  file_name: string
  storage_path: string
  sha256: string
  signature: string
  file_size_bytes: number
  created_at: string
}

export interface FirmwareRelease {
  id: string
  package_id: string
  release_notes: string
  published: boolean
  published_at: string | null
  created_at: string
  package: FirmwarePackage
}

export interface FirmwareUploadInput {
  file: File
  version: string
  releaseNotes: string
}
