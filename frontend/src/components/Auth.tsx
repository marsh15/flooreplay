import type { components } from '@/lib/generated-api'
import { createContext, useContext, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { API_BASE, ApiError } from '@/lib/api'
import { session } from '@/lib/session'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

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
    session.set(body.token)
    setUser(body.user)
    await client.invalidateQueries()
  }
  async function signOut() {
    try { await fetch(`${API_BASE}/auth/logout`, { method: 'POST', headers: session.headers() }) }
    finally { session.set(null); setUser(null); await client.invalidateQueries() }
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
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)
  if (user) return <div className="flex items-center gap-2 text-xs"><span>{user.display_name} · {user.role}</span><Button size="sm" variant="outline" onClick={() => void signOut()}>Sign out</Button></div>
  return <div><Button size="sm" variant="outline" onClick={() => setOpen(!open)}>Sign in</Button>{open && <form className="absolute right-4 top-16 z-50 w-72 space-y-3 rounded border bg-white p-4 shadow-lg" onSubmit={async (event) => {
    event.preventDefault(); setPending(true); setError('')
    try { await signIn(username.trim(), password); setPassword(''); setOpen(false) }
    catch (failure) { setError(failure instanceof Error ? failure.message : 'Sign-in failed') }
    finally { setPending(false) }
  }}><p className="text-sm font-medium">Owner or invited reviewer</p><label className="block text-xs">Username<Input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} required /></label><label className="block text-xs">Password<Input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label><p className="text-xs text-zinc-500">Sign in again after reloading this page.</p>{error && <p role="alert" className="text-xs text-red-700">{error}</p>}<Button size="sm" disabled={pending}>{pending ? 'Signing in…' : 'Continue'}</Button></form>}</div>
}
