import type { components } from '@/lib/generated-api'
import { createContext, useContext, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { API_BASE, ApiError } from '@/lib/api'
import { session } from '@/lib/session'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Popover } from 'radix-ui'
import { LogIn, X } from 'lucide-react'

export interface AuthUser { id: string; username: string; display_name: string; role: 'owner' | 'reviewer' }
interface AuthContextValue { user: AuthUser | null; signIn: (username: string, password: string) => Promise<void>; signOut: () => Promise<void> }
const AuthContext = createContext<AuthContextValue | null>(null)
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const client = useQueryClient()
  async function signIn(username: string, password: string) {
    const response = await fetch(`${API_BASE}/auth/login`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password } satisfies components['schemas']['LoginRequest']) })
    const body = await response.json()
    if (!response.ok) throw new ApiError(body.code ?? 'LOGIN_FAILED', body.message ?? body.detail ?? 'Sign-in failed.', response.status)
    client.clear()
    session.set(body.token)
    setUser(body.user)
    await client.invalidateQueries()
  }
  async function signOut() {
    try { await fetch(`${API_BASE}/auth/logout`, { method: 'POST', headers: session.headers() }) }
    finally { session.set(null); client.clear(); setUser(null); await client.invalidateQueries() }
  }
  return <AuthContext value={{ user, signIn, signOut }}>{children}</AuthContext>
}
export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('AuthProvider is required')
  return context
}
export function SignInControl() {
  const { user, signIn, signOut } = useAuth()
  const [open, setOpen] = useState(false)
  const usernameInput = useRef<HTMLInputElement>(null)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)

  if (user) return (
    <div className="flex flex-wrap items-center justify-end gap-3 text-xs">
      <span className="text-right"><span className="font-medium">{user.display_name}</span><span className="ml-2 text-muted-foreground"> · {user.role}</span></span>
      <Button size="sm" variant="outline" disabled={pending} onClick={async () => {
        setPending(true)
        try { await signOut() }
        finally { setPending(false) }
      }}>{pending ? 'Signing out…' : 'Sign out'}</Button>
    </div>
  )

  return (
    <Popover.Root open={open} onOpenChange={(nextOpen) => { setOpen(nextOpen); if (!nextOpen) setPassword('') }}>
      <Popover.Trigger asChild>
        <Button size="sm" variant="outline"><LogIn aria-hidden="true" />Sign in</Button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content onOpenAutoFocus={(event) => { event.preventDefault(); usernameInput.current?.focus() }} align="end" sideOffset={10} collisionPadding={16} aria-labelledby="sign-in-heading" className="z-50 w-[min(22rem,calc(100vw-2rem))] rounded-xl bg-popover p-5 text-popover-foreground shadow-[0_8px_32px_-8px_rgba(24,35,30,0.22)] outline-none">
          <div className="mb-5 flex items-start justify-between gap-4">
            <div><h2 id="sign-in-heading" className="text-base font-semibold">Reviewer access</h2><p className="mt-1 text-xs leading-relaxed text-muted-foreground">Sign in as an owner or invited reviewer.</p></div>
            <Popover.Close asChild><Button variant="ghost" size="icon-sm" aria-label="Close sign-in"><X aria-hidden="true" /></Button></Popover.Close>
          </div>
          <form className="space-y-4" aria-busy={pending} onSubmit={async (event) => {
            event.preventDefault(); setPending(true); setError('')
            try { await signIn(username.trim(), password); setPassword(''); setOpen(false) }
            catch (failure) { setError(failure instanceof Error ? failure.message : 'Sign-in failed') }
            finally { setPending(false) }
          }}>
            <label className="block space-y-1.5 text-xs font-medium"><span>Username</span><Input ref={usernameInput} autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required disabled={pending} /></label>
            <label className="block space-y-1.5 text-xs font-medium"><span>Password</span><Input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required disabled={pending} /></label>
            {error && <p role="alert" className="rounded-md bg-red-50 p-3 text-xs leading-relaxed text-red-800">{error}</p>}
            <Button className="w-full" size="sm" disabled={pending}>{pending ? 'Signing in…' : 'Continue'}</Button>
            <p className="text-xs leading-relaxed text-muted-foreground">Sign in again after reloading this page.</p>
          </form>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
