import { useQuery } from '@tanstack/react-query'
import { ArrowLeftRight, FlaskConical, Library, Activity, Shield } from 'lucide-react'
import { Link, useLocation } from 'react-router'
import { api } from '@/lib/api'
import { UsagePanel } from '@/components/Usage'
import { SignInControl, useAuth } from '@/components/Auth'
import { cn } from '@/lib/utils'

const NAV = [
  { to: '/', label: 'Incidents', icon: Library },
  { to: '/evaluation', label: 'Evaluation lab', icon: FlaskConical },
  { to: '/coverage', label: 'Coverage archive', icon: ArrowLeftRight },
]

export function AppShell({ children }: { children: React.ReactNode }) {
  const { pathname } = useLocation()
  const { user } = useAuth()
  const navigation = [...NAV, ...(user ? [{ to: '/workspaces', label: 'Workspaces', icon: Shield }] : []), ...(user?.role === 'owner' ? [{ to: '/operations', label: 'Operations', icon: Activity }] : [])]
  const isDemo = pathname === '/demo'
  const capabilities = useQuery({ queryKey: ['capabilities', user?.id ?? 'public'], queryFn: api.capabilities, staleTime: 60_000, enabled: !isDemo })
  return (
    <div className="app-shell flex min-h-[100dvh] flex-col">
      <a href="#main-content" className="skip-link">Skip to content</a>
      <header className="app-header border-b border-zinc-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-3 px-4 py-4 sm:px-6 lg:px-8">
          <Link to="/" className="flex shrink-0 items-center gap-3 rounded-sm">
            <span aria-hidden="true" className="flex size-9 items-center justify-center rounded-lg bg-zinc-900 text-white"><ArrowLeftRight size={18} strokeWidth={1.6} /></span>
            <span><span className="block text-base font-semibold tracking-tight">FloorReplay</span><span className="block text-[11px] text-zinc-600">{user ? 'Private and demo investigations' : 'Synthetic manufacturing data'}</span></span>
          </Link>
          <div className="ml-auto flex items-center gap-3 sm:order-3">
            {isDemo ? <span className="text-xs font-medium text-zinc-600">Isolated simulation</span> : <SignInControl />}
            {!isDemo && capabilities.isError && <span className="hidden max-w-28 text-xs text-red-700 lg:block" title={capabilities.error.message}>Capabilities unavailable</span>}
          </div>
          <nav className="flex w-full flex-wrap gap-1 border-t border-zinc-100 pt-3 sm:order-2 sm:ml-auto sm:w-auto sm:border-0 sm:pt-0" aria-label="Primary">
            {navigation.map(({ to, label, icon: Icon }) => {
              const active = to === '/' ? pathname === '/' || pathname.startsWith('/incidents/') : pathname === to || pathname.startsWith(`${to}/`)
              return <Link key={to} to={to} aria-current={active ? 'page' : undefined} className={cn('nav-link flex min-h-10 flex-1 items-center justify-center gap-2 rounded-md px-2.5 text-xs font-medium sm:flex-none sm:text-sm', active ? 'bg-zinc-900 text-white' : 'text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900')}><Icon aria-hidden="true" className="hidden size-4 md:block" strokeWidth={1.7} />{label}</Link>
            })}
          </nav>
        </div>
      </header>
      <main id="main-content" tabIndex={-1} className="mx-auto w-full max-w-6xl flex-1 px-4 py-7 sm:px-6 sm:py-10 lg:px-8">{!isDemo && <UsagePanel />}{children}</main>
      <footer className="mx-auto w-full max-w-6xl px-4 pb-6 pt-8 sm:px-6 lg:px-8">
        <p className="max-w-3xl border-t border-zinc-200 pt-4 text-xs leading-5 text-zinc-600">FloorReplay is an unofficial engineering exploration. Public examples use synthetic data. It is not affiliated with Genorai and has not been validated in a real factory.</p>
      </footer>
    </div>
  )
}
