/*
  # Add telemetry columns to devices_enhanced
*/

ALTER TABLE devices_enhanced
  ADD COLUMN IF NOT EXISTS cpu_usage double precision,
  ADD COLUMN IF NOT EXISTS ram_usage double precision,
  ADD COLUMN IF NOT EXISTS disk_usage double precision,
  ADD COLUMN IF NOT EXISTS hostname text,
  ADD COLUMN IF NOT EXISTS local_ip text,
  ADD COLUMN IF NOT EXISTS system_uptime bigint,
  ADD COLUMN IF NOT EXISTS camera_available boolean;