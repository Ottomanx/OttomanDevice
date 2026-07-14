# OttomanDevice Dashboard v0.1.0

React dashboard for monitoring OttomanDevice fleet telemetry and sending remote commands.

## Stack

- React 19 + TypeScript
- Vite
- Tailwind CSS v4
- Supabase

## Setup

```powershell
cd dashboard
copy .env.example .env
# Edit .env with your Supabase URL and anon key (VITE_ prefix required)
npm install
npm run dev
```

Open http://localhost:5173

## Environment

| Variable | Description |
|----------|-------------|
| `VITE_SUPABASE_URL` | Supabase project URL |
| `VITE_SUPABASE_ANON_KEY` | Supabase anon/public key |

Use the same Supabase project as the device agent. Tables: `devices_enhanced`, `device_commands`.

## Features

- Lists all devices from `devices_enhanced`
- Auto-refreshes every 5 seconds
- Device cards: online status, computer name, CPU/RAM/disk, camera, last heartbeat
- Command buttons (PING, HEARTBEAT, CAMERA TEST) insert rows into `device_commands`
- Remote desktop preview: live JPEG stream refreshed every 1 second

## Scripts

| Command | Description |
|---------|-------------|
| `npm run dev` | Start dev server |
| `npm run build` | Production build to `dist/` |
| `npm run preview` | Preview production build |

## Architecture

```
src/
  components/   UI components
  hooks/        Data fetching and command state
  lib/          Supabase client
  services/     API layer (devices, commands)
  types/        Shared TypeScript types
  utils/        Formatting and status helpers
```
