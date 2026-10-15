import { useQuery } from '@tanstack/react-query'
import { ArrowLeftRight, FlaskConical, Library, Activity, Shield } from 'lucide-react'
import { Link, useLocation } from 'react-router'
import { api } from '@/lib/api'
import { UsagePanel } from '@/components/Usage'
import { SignInControl, useAuth } from '@/components/Auth'
import { Limits } from '@/components/board'
import { cn } from '@/lib/utils'

const NAV = [{ to: '/', label: 'Incidents', icon: Library }]
const ENGINEERING = [
  { to: '/evaluation', label: 'Evaluation lab', icon: FlaskConical },
  { to: '/coverage', label: 'Coverage archive', icon: ArrowLeftRight },
]

export function AppShell({ children }: { children: React.ReactNode }) {
  const { pathname } = useLocation()
  const { user } = useAuth()
  const navigation = [
    ...NAV,
    ...(user ? [{ to: '/workspaces', label: 'Workspaces', icon: Shield }] : []),
    ...(user?.role === 'owner' ? [{ to: '/operations', label: 'Operations', icon: Activity }] : []),
  ]
  const isDemo = pathname === '/demo'
  const isArchive = pathname === '/coverage' || pathname.startsWith('/coverage/')
  const capabilities = useQuery({
    queryKey: ['capabilities', user?.id ?? 'public'],
    queryFn: api.capabilities,
    staleTime: 60_000,
    enabled: !isDemo,
  })
  const navLink = ({ to, label, icon: Icon }: (typeof NAV)[number]) => {
    const active =
      to === '/'
        ? pathname === '/' || pathname.startsWith('/incidents/')
        : pathname === to || pathname.startsWith(`${to}/`)
    return (
      <Link
        key={to}
        to={to}
        aria-current={active ? 'page' : undefined}
        className={cn(
          'nav-link flex min-h-11 items-center gap-2 border-b-2 px-3 text-sm font-semibold',
          active
            ? 'border-board-foreground text-board-foreground'
            : 'border-transparent text-board-muted hover:text-board-foreground',
        )}
      >
        <Icon aria-hidden="true" className="hidden size-4 md:block" strokeWidth={1.7} />
        {label}
      </Link>
    )
  }
  return (
    <div className="app-shell flex min-h-[100dvh] flex-col">
      <a href="#main-content" className="skip-link">
        Skip to content
      </a>
      <header className="app-header bg-board text-board-foreground">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-8 gap-y-1 px-4 pt-3 sm:px-6 lg:px-8">
          <Link to="/" className="flex shrink-0 items-center gap-3 rounded-sm pb-2">
            <span
              aria-hidden="true"
              className="flex size-9 items-center justify-center rounded-sm bg-primary text-primary-foreground"
            >
              <ArrowLeftRight size={18} strokeWidth={1.8} />
            </span>
            <span>
              <span className="block text-xl leading-tight font-bold font-stretch-semi-condensed">
                FloorReplay
              </span>
              <span className="block text-xs text-board-muted">
                {user ? 'Private and demo investigations' : 'Synthetic manufacturing data'}
              </span>
            </span>
          </Link>
          <div className="ml-auto flex items-center gap-3 pb-2 sm:order-3">
            {isDemo ? (
              <span className="text-sm font-medium text-board-muted">Isolated simulation</span>
            ) : (
              <SignInControl />
            )}
            {!isDemo && capabilities.isError && (
              <span
                className="hidden max-w-28 text-xs text-danger-border lg:block"
                title={capabilities.error.message}
              >
                Capabilities unavailable
              </span>
            )}
          </div>
          <nav
            className="flex w-full flex-wrap items-center gap-x-1 border-t border-rule sm:order-2 sm:w-auto sm:border-0"
            aria-label="Primary"
          >
            {navigation.map(navLink)}
            <div className="flex basis-full flex-wrap items-center border-t border-rule sm:contents">
              <span
                aria-hidden="true"
                className="mx-2 hidden h-5 w-px bg-board-muted/40 sm:block"
              />
              <span className="px-2 text-xs font-medium text-board-muted">Engineering</span>
              {ENGINEERING.map(navLink)}
            </div>
          </nav>
        </div>
      </header>
      <main
        id="main-content"
        tabIndex={-1}
        className="mx-auto w-full max-w-6xl flex-1 px-4 py-7 sm:px-6 sm:py-10 lg:px-8"
      >
        {!isDemo && <UsagePanel />}
        {isArchive && (
          <Limits tone="neutral" className="mb-6 print:hidden">
            <strong>Archive.</strong> The older operator-coverage workbench remains an archived
            engineering demonstration. The current product is the incident investigation workflow.
          </Limits>
        )}
        {children}
      </main>
      <footer className="mx-auto w-full max-w-6xl px-4 pt-8 pb-6 sm:px-6 lg:px-8">
        <p className="max-w-3xl border-t-2 border-foreground pt-4 text-sm leading-6 text-muted-foreground">
          FloorReplay is an unofficial engineering exploration. Public examples use synthetic data.
          It is not affiliated with Genorai and has not been validated in a real factory.
        </p>
      </footer>
    </div>
  )
}
