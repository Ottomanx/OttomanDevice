/*
  # MVP devices_enhanced table

  First production table for OttomanDevice self-registration and heartbeats.
  Standalone schema — no dependency on prior migrations.
*/

CREATE TABLE devices_enhanced (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  device_id text UNIQUE NOT NULL,
  computer_name text,
  operating_system text,
  python_version text,
  firmware_version text,
  status text,
  last_online_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE devices_enhanced ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow select devices_enhanced"
  ON devices_enhanced
  FOR SELECT
  TO anon, authenticated
  USING (true);

CREATE POLICY "Allow insert devices_enhanced"
  ON devices_enhanced
  FOR INSERT
  TO anon, authenticated
  WITH CHECK (true);

CREATE POLICY "Allow update devices_enhanced"
  ON devices_enhanced
  FOR UPDATE
  TO anon, authenticated
  USING (true)
  WITH CHECK (true);