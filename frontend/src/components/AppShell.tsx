/**
 * App shell: quiet top bar, two primary destinations. Light theme is
 * locked for this workbench; state colors supplement labels everywhere.
 */

import { useQuery } from '@tanstack/react-query'
import { Link, useLocation } from 'react-router'
import { api } from '@/lib/api'
import { UsagePanel } from '@/components/Usage'
import { SignInControl } from '@/components/Auth'
import { cn } from '@/lib/utils'

const NAV = [
  { to: '/', label: 'Incidents' },
  { to: '/evaluation', label: 'Evaluation lab' },
  { to: '/coverage', label: 'Coverage archive' },
]

export function AppShell({ children }: { children: React.ReactNode }) {
  const { pathname } = useLocation()
  const capabilities = useQuery({
    queryKey: ['capabilities'],
    queryFn: api.capabilities,
    staleTime: 60_000,
  })
  return (
    <div className="min-h-[100dvh] bg-zinc-50">
      <header className="border-b border-zinc-200 bg-white">
        <div className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-4">
          <Link to="/" className="flex items-baseline gap-2 focus-visible:outline-2 focus-visible:outline-offset-4">
            <span className="text-sm font-semibold tracking-tight">FloorReplay</span>
            <span className="hidden text-xs text-zinc-500 sm:inline">
              Synthetic manufacturing data
            </span>
          </Link>
          <nav className="ml-auto flex flex-wrap gap-1" aria-label="Primary">
            {NAV.map((item) => {
              const active = item.to === '/' ? pathname === '/' || pathname.startsWith('/incidents/') : pathname === item.to || pathname.startsWith(`${item.to}/`)
              return (
                <Link
                  key={item.to}
                  to={item.to}
                  aria-current={active ? 'page' : undefined}
                  className={cn(
                    'rounded-md px-3 py-1.5 text-sm transition-colors',
                    active
                      ? 'bg-zinc-900 text-white'
                      : 'text-zinc-600 hover:bg-zinc-100 hover:text-zinc-900',
                  )}
                >
                  {item.label}
                </Link>
              )
            })}
          </nav>
          <SignInControl />
          {capabilities.isError ? (
            <span className="text-[10px] text-red-700" title={capabilities.error.message}>
              Capabilities unavailable
            </span>
          ) : null}
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-6"><UsagePanel /><div className="mt-4">{children}</div></main>
      <footer className="mx-auto max-w-6xl px-4 pb-8 pt-2">
        <p className="text-xs text-zinc-400">
          FloorReplay is an unofficial engineering exploration using synthetic data. It is not
          affiliated with Genorai and has not been validated in a real factory.
        </p>
      </footer>
    </div>
  )
}
