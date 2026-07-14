import { describe, expect, it } from 'vitest'

import { otaInstallResult, otaStatusLabel } from '../types/ota'

describe('ota status presentation', () => {
  it('labels install lifecycle states', () => {
    expect(otaStatusLabel('downloading')).toBe('Downloading')
    expect(otaStatusLabel('verifying')).toBe('Verifying')
    expect(otaStatusLabel('installing')).toBe('Installing')
    expect(otaStatusLabel('completed')).toBe('Completed')
    expect(otaStatusLabel('rollback')).toBe('Rollback')
  })

  it('shows install result for completed and failed states', () => {
    expect(otaInstallResult('completed', 'Firmware 0.2.0 installed successfully')).toContain('installed')
    expect(otaInstallResult('failed', 'Install failed and rolled back to 0.1.0')).toContain('rolled back')
    expect(otaInstallResult('rollback', 'Install failed; rolling back')).toContain('rolling back')
  })
})
