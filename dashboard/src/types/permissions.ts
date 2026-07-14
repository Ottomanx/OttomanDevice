export const Permission = {
  Desktop: 'desktop',
  Mouse: 'mouse',
  Keyboard: 'keyboard',
  Clipboard: 'clipboard',
  FileTransfer: 'file_transfer',
  Ota: 'ota',
  Restart: 'restart',
  Camera: 'camera',
  Microphone: 'microphone',
} as const

export type PermissionKey = (typeof Permission)[keyof typeof Permission]

export const ALL_PERMISSIONS: readonly PermissionKey[] = [
  Permission.Desktop,
  Permission.Mouse,
  Permission.Keyboard,
  Permission.Clipboard,
  Permission.FileTransfer,
  Permission.Ota,
  Permission.Restart,
  Permission.Camera,
  Permission.Microphone,
]

export function normalizePermissions(values: unknown): PermissionKey[] {
  if (!Array.isArray(values)) {
    return []
  }

  const allowed = new Set<string>(ALL_PERMISSIONS)
  return values.filter(
    (value): value is PermissionKey =>
      typeof value === 'string' && allowed.has(value),
  )
}

export function hasPermission(
  permissions: readonly string[],
  permission: PermissionKey,
): boolean {
  return permissions.includes(permission)
}
