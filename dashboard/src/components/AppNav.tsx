import { useAuth } from '../contexts/AuthContext'

export type AppPage = 'dashboard' | 'inventory' | 'firmware'

interface AppNavProps {
  activePage: AppPage
  onNavigate: (page: AppPage) => void
}

const navItems: { id: AppPage; label: string }[] = [
  { id: 'dashboard', label: 'Dashboard' },
  { id: 'inventory', label: 'Inventory' },
  { id: 'firmware', label: 'Firmware' },
]

export function AppNav({ activePage, onNavigate }: AppNavProps) {
  const { user, signOut } = useAuth()

  return (
    <nav className="mb-6 flex flex-wrap items-center justify-between gap-3">
      <div className="flex flex-wrap gap-2">
        {navItems.map((item) => {
          const isActive = item.id === activePage
          return (
            <button
              key={item.id}
              type="button"
              onClick={() => onNavigate(item.id)}
              className={`rounded-xl border px-4 py-2 text-sm font-medium transition ${
                isActive
                  ? 'border-indigo-400/40 bg-indigo-500/15 text-indigo-200'
                  : 'border-slate-800 bg-slate-900/60 text-slate-300 hover:border-slate-700 hover:text-white'
              }`}
            >
              {item.label}
            </button>
          )
        })}
      </div>

      <div className="flex items-center gap-3 text-sm text-slate-400">
        <span className="max-w-[220px] truncate">{user?.email ?? user?.id}</span>
        <button
          type="button"
          onClick={() => void signOut()}
          className="rounded-lg border border-slate-700 px-3 py-1.5 text-xs font-medium text-slate-300 transition hover:border-slate-600 hover:text-white"
        >
          Sign out
        </button>
      </div>
    </nav>
  )
}