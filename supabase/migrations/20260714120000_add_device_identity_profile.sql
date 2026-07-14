/*
  # Sprint 42 device identity profile columns
*/

ALTER TABLE devices_enhanced
  ADD COLUMN IF NOT EXISTS installation_id text,
  ADD COLUMN IF NOT EXISTS architecture text,
  ADD COLUMN IF NOT EXISTS cpu_model text,
  ADD COLUMN IF NOT EXISTS ram_total_mb integer,
  ADD COLUMN IF NOT EXISTS application_version text,
  ADD COLUMN IF NOT EXISTS runtime_version text,
  ADD COLUMN IF NOT EXISTS certificate_fingerprint text,
  ADD COLUMN IF NOT EXISTS device_profile jsonb,
  ADD COLUMN IF NOT EXISTS first_boot_timestamp timestamptz,
  ADD COLUMN IF NOT EXISTS registration_signature text;
