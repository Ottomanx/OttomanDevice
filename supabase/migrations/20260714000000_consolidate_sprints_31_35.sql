/*
  # Consolidated Sprint 31-35 schema (idempotent)

  Creates every table, function, storage bucket, RLS policy, and seed row
  required for Inventory, Permissions, Fleet Operations, and OTA.

  Safe to run multiple times. Preserves existing data.
*/

-- ---------------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------------
-- Core device tables (MVP + telemetry)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS devices_enhanced (
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

ALTER TABLE devices_enhanced
  ADD COLUMN IF NOT EXISTS cpu_usage double precision,
  ADD COLUMN IF NOT EXISTS ram_usage double precision,
  ADD COLUMN IF NOT EXISTS disk_usage double precision,
  ADD COLUMN IF NOT EXISTS hostname text,
  ADD COLUMN IF NOT EXISTS local_ip text,
  ADD COLUMN IF NOT EXISTS system_uptime bigint,
  ADD COLUMN IF NOT EXISTS camera_available boolean;

CREATE TABLE IF NOT EXISTS device_commands (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  device_id text NOT NULL,
  command text NOT NULL,
  status text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  executed_at timestamptz
);

-- ---------------------------------------------------------------------------
-- Permissions (Sprint 29/30 + clipboard + file transfer)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS operator_roles (
  role_name text PRIMARY KEY,
  display_name text NOT NULL,
  permissions text[] NOT NULL DEFAULT '{}',
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS operator_role_assignments (
  user_id uuid NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  role_name text NOT NULL REFERENCES operator_roles(role_name) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, role_name)
);

INSERT INTO operator_roles (role_name, display_name, permissions) VALUES
  ('viewer', 'Viewer', ARRAY['desktop']::text[]),
  ('operator', 'Operator', ARRAY['desktop', 'mouse']::text[]),
  ('technician', 'Technician', ARRAY['desktop', 'mouse', 'camera', 'restart']::text[]),
  (
    'admin',
    'Administrator',
    ARRAY['desktop', 'mouse', 'keyboard', 'ota', 'restart', 'camera', 'microphone']::text[]
  )
ON CONFLICT (role_name) DO NOTHING;

UPDATE operator_roles
SET permissions = array_append(permissions, 'clipboard')
WHERE role_name = 'admin'
  AND NOT ('clipboard' = ANY(permissions));

UPDATE operator_roles
SET permissions = array_append(permissions, 'file_transfer')
WHERE role_name = 'admin'
  AND NOT ('file_transfer' = ANY(permissions));

CREATE OR REPLACE FUNCTION public.get_user_permissions(p_user_id uuid)
RETURNS text[]
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT COALESCE(
    (
      SELECT ARRAY(
        SELECT DISTINCT permission
        FROM operator_role_assignments AS assignments
        JOIN operator_roles AS roles ON roles.role_name = assignments.role_name
        CROSS JOIN LATERAL unnest(roles.permissions) AS permission
        WHERE assignments.user_id = p_user_id
        ORDER BY permission
      )
    ),
    ARRAY['desktop', 'mouse']::text[]
  );
$$;

GRANT EXECUTE ON FUNCTION public.get_user_permissions(uuid) TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- Inventory (Sprint 31)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS device_groups (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name text NOT NULL UNIQUE,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS device_group_members (
  device_id text PRIMARY KEY REFERENCES devices_enhanced(device_id) ON DELETE CASCADE,
  group_id uuid NOT NULL REFERENCES device_groups(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_device_group_members_group_id
  ON device_group_members(group_id);

CREATE TABLE IF NOT EXISTS device_tags (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  device_id text NOT NULL REFERENCES devices_enhanced(device_id) ON DELETE CASCADE,
  tag text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT device_tags_device_id_tag_key UNIQUE (device_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_device_tags_device_id ON device_tags(device_id);
CREATE INDEX IF NOT EXISTS idx_device_tags_tag ON device_tags(tag);

-- ---------------------------------------------------------------------------
-- OTA (Sprint 33-34)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS firmware_packages (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  version text NOT NULL UNIQUE,
  file_name text NOT NULL,
  storage_path text NOT NULL UNIQUE,
  sha256 text NOT NULL,
  signature text NOT NULL,
  file_size_bytes bigint NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS firmware_releases (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  package_id uuid NOT NULL UNIQUE REFERENCES firmware_packages(id) ON DELETE CASCADE,
  release_notes text NOT NULL DEFAULT '',
  published boolean NOT NULL DEFAULT false,
  published_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_firmware_releases_published
  ON firmware_releases(published, created_at DESC);

CREATE TABLE IF NOT EXISTS device_ota_status (
  device_id text PRIMARY KEY REFERENCES devices_enhanced(device_id) ON DELETE CASCADE,
  current_version text,
  target_version text,
  status text NOT NULL DEFAULT 'idle',
  message text,
  package_id uuid REFERENCES firmware_packages(id) ON DELETE SET NULL,
  updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE device_ota_status
  ADD COLUMN IF NOT EXISTS progress integer NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS ota_config (
  key text PRIMARY KEY,
  value text NOT NULL
);

INSERT INTO ota_config (key, value)
VALUES ('signing_secret', 'dev-ota-signing-secret-change-in-production')
ON CONFLICT (key) DO NOTHING;

CREATE OR REPLACE FUNCTION public.sign_firmware_hash(p_sha256 text)
RETURNS text
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  signing_secret text;
BEGIN
  SELECT value
  INTO signing_secret
  FROM ota_config
  WHERE key = 'signing_secret';

  IF signing_secret IS NULL OR signing_secret = '' THEN
    RAISE EXCEPTION 'OTA signing secret is not configured';
  END IF;

  RETURN encode(
    hmac(decode(p_sha256, 'hex'), signing_secret, 'sha256'),
    'hex'
  );
END;
$$;

GRANT EXECUTE ON FUNCTION public.sign_firmware_hash(text) TO anon, authenticated;

-- ---------------------------------------------------------------------------
-- Storage buckets
-- ---------------------------------------------------------------------------

INSERT INTO storage.buckets (id, name, public)
VALUES
  ('firmware', 'firmware', false),
  ('screenshots', 'screenshots', true),
  ('desktop-preview', 'desktop-preview', true)
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Row level security
-- ---------------------------------------------------------------------------

ALTER TABLE devices_enhanced ENABLE ROW LEVEL SECURITY;
ALTER TABLE device_commands ENABLE ROW LEVEL SECURITY;
ALTER TABLE operator_roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE operator_role_assignments ENABLE ROW LEVEL SECURITY;
ALTER TABLE device_groups ENABLE ROW LEVEL SECURITY;
ALTER TABLE device_group_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE device_tags ENABLE ROW LEVEL SECURITY;
ALTER TABLE firmware_packages ENABLE ROW LEVEL SECURITY;
ALTER TABLE firmware_releases ENABLE ROW LEVEL SECURITY;
ALTER TABLE device_ota_status ENABLE ROW LEVEL SECURITY;
ALTER TABLE ota_config ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "Allow select devices_enhanced" ON devices_enhanced;
CREATE POLICY "Allow select devices_enhanced"
  ON devices_enhanced FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow insert devices_enhanced" ON devices_enhanced;
CREATE POLICY "Allow insert devices_enhanced"
  ON devices_enhanced FOR INSERT TO anon, authenticated WITH CHECK (true);

DROP POLICY IF EXISTS "Allow update devices_enhanced" ON devices_enhanced;
CREATE POLICY "Allow update devices_enhanced"
  ON devices_enhanced FOR UPDATE TO anon, authenticated USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow select device_commands" ON device_commands;
CREATE POLICY "Allow select device_commands"
  ON device_commands FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow insert device_commands" ON device_commands;
CREATE POLICY "Allow insert device_commands"
  ON device_commands FOR INSERT TO anon, authenticated WITH CHECK (true);

DROP POLICY IF EXISTS "Allow update device_commands" ON device_commands;
CREATE POLICY "Allow update device_commands"
  ON device_commands FOR UPDATE TO anon, authenticated USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow read operator_roles" ON operator_roles;
CREATE POLICY "Allow read operator_roles"
  ON operator_roles FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow read own role assignments" ON operator_role_assignments;
CREATE POLICY "Allow read own role assignments"
  ON operator_role_assignments FOR SELECT TO authenticated USING (auth.uid() = user_id);

DROP POLICY IF EXISTS "Allow select device_groups" ON device_groups;
CREATE POLICY "Allow select device_groups"
  ON device_groups FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow insert device_groups" ON device_groups;
CREATE POLICY "Allow insert device_groups"
  ON device_groups FOR INSERT TO anon, authenticated WITH CHECK (true);

DROP POLICY IF EXISTS "Allow update device_groups" ON device_groups;
CREATE POLICY "Allow update device_groups"
  ON device_groups FOR UPDATE TO anon, authenticated USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow delete device_groups" ON device_groups;
CREATE POLICY "Allow delete device_groups"
  ON device_groups FOR DELETE TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow select device_group_members" ON device_group_members;
CREATE POLICY "Allow select device_group_members"
  ON device_group_members FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow insert device_group_members" ON device_group_members;
CREATE POLICY "Allow insert device_group_members"
  ON device_group_members FOR INSERT TO anon, authenticated WITH CHECK (true);

DROP POLICY IF EXISTS "Allow update device_group_members" ON device_group_members;
CREATE POLICY "Allow update device_group_members"
  ON device_group_members FOR UPDATE TO anon, authenticated USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow delete device_group_members" ON device_group_members;
CREATE POLICY "Allow delete device_group_members"
  ON device_group_members FOR DELETE TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow select device_tags" ON device_tags;
CREATE POLICY "Allow select device_tags"
  ON device_tags FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow insert device_tags" ON device_tags;
CREATE POLICY "Allow insert device_tags"
  ON device_tags FOR INSERT TO anon, authenticated WITH CHECK (true);

DROP POLICY IF EXISTS "Allow delete device_tags" ON device_tags;
CREATE POLICY "Allow delete device_tags"
  ON device_tags FOR DELETE TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow select firmware_packages" ON firmware_packages;
CREATE POLICY "Allow select firmware_packages"
  ON firmware_packages FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow insert firmware_packages" ON firmware_packages;
CREATE POLICY "Allow insert firmware_packages"
  ON firmware_packages FOR INSERT TO anon, authenticated WITH CHECK (true);

DROP POLICY IF EXISTS "Allow select firmware_releases" ON firmware_releases;
CREATE POLICY "Allow select firmware_releases"
  ON firmware_releases FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow insert firmware_releases" ON firmware_releases;
CREATE POLICY "Allow insert firmware_releases"
  ON firmware_releases FOR INSERT TO anon, authenticated WITH CHECK (true);

DROP POLICY IF EXISTS "Allow update firmware_releases" ON firmware_releases;
CREATE POLICY "Allow update firmware_releases"
  ON firmware_releases FOR UPDATE TO anon, authenticated USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow select device_ota_status" ON device_ota_status;
CREATE POLICY "Allow select device_ota_status"
  ON device_ota_status FOR SELECT TO anon, authenticated USING (true);

DROP POLICY IF EXISTS "Allow insert device_ota_status" ON device_ota_status;
CREATE POLICY "Allow insert device_ota_status"
  ON device_ota_status FOR INSERT TO anon, authenticated WITH CHECK (true);

DROP POLICY IF EXISTS "Allow update device_ota_status" ON device_ota_status;
CREATE POLICY "Allow update device_ota_status"
  ON device_ota_status FOR UPDATE TO anon, authenticated USING (true) WITH CHECK (true);

DROP POLICY IF EXISTS "Allow select ota_config" ON ota_config;
CREATE POLICY "Allow select ota_config"
  ON ota_config FOR SELECT TO anon, authenticated USING (true);

-- Storage policies (firmware, screenshots, desktop-preview)
DROP POLICY IF EXISTS "Allow firmware bucket read" ON storage.objects;
CREATE POLICY "Allow firmware bucket read"
  ON storage.objects FOR SELECT TO anon, authenticated
  USING (bucket_id = 'firmware');

DROP POLICY IF EXISTS "Allow firmware bucket insert" ON storage.objects;
CREATE POLICY "Allow firmware bucket insert"
  ON storage.objects FOR INSERT TO anon, authenticated
  WITH CHECK (bucket_id = 'firmware');

DROP POLICY IF EXISTS "Allow firmware bucket update" ON storage.objects;
CREATE POLICY "Allow firmware bucket update"
  ON storage.objects FOR UPDATE TO anon, authenticated
  USING (bucket_id = 'firmware')
  WITH CHECK (bucket_id = 'firmware');

DROP POLICY IF EXISTS "Allow screenshots bucket read" ON storage.objects;
CREATE POLICY "Allow screenshots bucket read"
  ON storage.objects FOR SELECT TO anon, authenticated
  USING (bucket_id = 'screenshots');

DROP POLICY IF EXISTS "Allow screenshots bucket insert" ON storage.objects;
CREATE POLICY "Allow screenshots bucket insert"
  ON storage.objects FOR INSERT TO anon, authenticated
  WITH CHECK (bucket_id = 'screenshots');

DROP POLICY IF EXISTS "Allow screenshots bucket update" ON storage.objects;
CREATE POLICY "Allow screenshots bucket update"
  ON storage.objects FOR UPDATE TO anon, authenticated
  USING (bucket_id = 'screenshots')
  WITH CHECK (bucket_id = 'screenshots');

DROP POLICY IF EXISTS "Allow desktop preview bucket read" ON storage.objects;
CREATE POLICY "Allow desktop preview bucket read"
  ON storage.objects FOR SELECT TO anon, authenticated
  USING (bucket_id = 'desktop-preview');

DROP POLICY IF EXISTS "Allow desktop preview bucket insert" ON storage.objects;
CREATE POLICY "Allow desktop preview bucket insert"
  ON storage.objects FOR INSERT TO anon, authenticated
  WITH CHECK (bucket_id = 'desktop-preview');

DROP POLICY IF EXISTS "Allow desktop preview bucket update" ON storage.objects;
CREATE POLICY "Allow desktop preview bucket update"
  ON storage.objects FOR UPDATE TO anon, authenticated
  USING (bucket_id = 'desktop-preview')
  WITH CHECK (bucket_id = 'desktop-preview');