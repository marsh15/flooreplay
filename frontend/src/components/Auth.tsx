import type { components } from '@/lib/generated-api'
import { Fragment, createContext, useContext, useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { apiRequest, ApiError } from '@/lib/api'
import { session } from '@/lib/session'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Popover } from 'radix-ui'
import { LogIn, X } from 'lucide-react'

export interface AuthUser {
  id: string
  username: string
  display_name: string
  role: 'owner' | 'reviewer'
}
interface AuthContextValue {
  user: AuthUser | null
  /** Increments on every sign-in, sign-out and session expiry, so screens can reset. */
  epoch: number
  notice: string
  signIn: (username: string, password: string) => Promise<void>
  signOut: () => Promise<void>
}
const AuthContext = createContext<AuthContextValue | null>(null)

function readAccount(body: unknown): { token: string; user: AuthUser } {
  if (
    typeof body !== 'object' ||
    body === null ||
    !('token' in body) ||
    typeof body.token !== 'string' ||
    !body.token ||
    !('user' in body) ||
    typeof body.user !== 'object' ||
    body.user === null
  )
    throw new ApiError(
      'INVALID_RESPONSE',
      'The sign-in response was unreadable. Please try again.',
      502,
    )
  const account = body.user
  if (
    !('id' in account) ||
    typeof account.id !== 'string' ||
    !('username' in account) ||
    typeof account.username !== 'string' ||
    !('display_name' in account) ||
    typeof account.display_name !== 'string' ||
    !('role' in account) ||
    (account.role !== 'owner' && account.role !== 'reviewer')
  )
    throw new ApiError(
      'INVALID_RESPONSE',
      'The account response was unreadable. Please try again.',
      502,
    )
  return {
    token: body.token,
    user: {
      id: account.id,
      username: account.username,
      display_name: account.display_name,
      role: account.role,
    },
  }
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null)
  const [epoch, setEpoch] = useState(0)
  const [notice, setNotice] = useState('')
  // A sign-in that resolves after a newer sign-in or sign-out must not win.
  const authGeneration = useRef(0)
  const client = useQueryClient()
  useEffect(
    () =>
      session.onExpire(() => {
        authGeneration.current += 1
        client.clear()
        setUser(null)
        setEpoch((value) => value + 1)
        setNotice('Your session ended. Sign in again to continue.')
      }),
    [client],
  )
  async function signIn(username: string, password: string) {
    const generation = ++authGeneration.current
    const body = await apiRequest<unknown>(
      '/auth/login',
      {
        method: 'POST',
        body: JSON.stringify({
          username,
          password,
        } satisfies components['schemas']['LoginRequest']),
      },
      { anonymous: true },
    )
    if (generation !== authGeneration.current)
      throw new ApiError('SESSION_CHANGED', 'A newer sign-in attempt replaced this request.', 401)
    const account = readAccount(body)
    client.clear()
    session.set(account.token)
    setUser(account.user)
    setEpoch((value) => value + 1)
    setNotice('')
    await client.invalidateQueries()
  }
  async function signOut() {
    authGeneration.current += 1
    const revocation = apiRequest(
      '/auth/logout',
      { method: 'POST' },
      { allowSessionChange: true, timeoutMs: 10_000 },
    )
    // Clear local state immediately; a slow or failed revocation must not keep data on screen.
    session.set(null)
    client.clear()
    setUser(null)
    setEpoch((value) => value + 1)
    setNotice('')
    try {
      await revocation
    } catch (error) {
      if (!session.token())
        setNotice(
          error instanceof ApiError && error.status === 401
            ? 'Your session ended.'
            : 'Signed out on this device. Server revocation could not be confirmed; the session expires within eight hours.',
        )
    }
  }
  return (
    <AuthContext value={{ user, epoch, notice, signIn, signOut }}>
      <Fragment key={user?.id ?? 'public'}>{children}</Fragment>
    </AuthContext>
  )
}
export function useAuth() {
  const context = useContext(AuthContext)
  if (!context) throw new Error('AuthProvider is required')
  return context
}
export function SignInControl() {
  const { user, notice, signIn, signOut } = useAuth()
  const [open, setOpen] = useState(false)
  const usernameInput = useRef<HTMLInputElement>(null)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)

  if (user)
    return (
      <div className="flex flex-wrap items-center justify-end gap-3 text-sm">
        <span className="text-right">
          <span className="font-medium text-board-foreground">{user.display_name}</span>
          <span className="ml-2 text-board-muted"> · {user.role}</span>
        </span>
        <Button
          size="sm"
          variant="board"
          disabled={pending}
          onClick={async () => {
            setPending(true)
            try {
              await signOut()
            } finally {
              setPending(false)
            }
          }}
        >
          {pending ? 'Signing out…' : 'Sign out'}
        </Button>
      </div>
    )

  return (
    <Popover.Root
      open={open}
      onOpenChange={(nextOpen) => {
        setOpen(nextOpen)
        if (!nextOpen) setPassword('')
      }}
    >
      <Popover.Trigger asChild>
        <Button size="sm" variant="board">
          <LogIn aria-hidden="true" />
          Sign in
        </Button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content
          onOpenAutoFocus={(event) => {
            event.preventDefault()
            usernameInput.current?.focus()
          }}
          align="end"
          sideOffset={10}
          collisionPadding={16}
          aria-labelledby="sign-in-heading"
          className="z-50 w-[min(22rem,calc(100vw-2rem))] rounded-md border border-border bg-popover p-5 text-popover-foreground shadow-[0_12px_32px_-12px_rgba(20,24,40,0.35)] outline-none"
        >
          <div className="mb-5 flex items-start justify-between gap-4">
            <div>
              <h2 id="sign-in-heading" className="text-base font-semibold">
                Reviewer access
              </h2>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                Sign in as an owner or invited reviewer.
              </p>
            </div>
            <Popover.Close asChild>
              <Button variant="ghost" size="icon-sm" aria-label="Close sign-in">
                <X aria-hidden="true" />
              </Button>
            </Popover.Close>
          </div>
          <form
            className="space-y-4"
            aria-busy={pending}
            onSubmit={async (event) => {
              event.preventDefault()
              setPending(true)
              setError('')
              try {
                await signIn(username.trim(), password)
                setPassword('')
                setOpen(false)
              } catch (failure) {
                setError(failure instanceof Error ? failure.message : 'Sign-in failed')
              } finally {
                setPending(false)
              }
            }}
          >
            <label className="block space-y-1.5 text-sm font-medium">
              <span>Username</span>
              <Input
                ref={usernameInput}
                autoComplete="username"
                minLength={3}
                maxLength={120}
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                required
                disabled={pending}
              />
            </label>
            <label className="block space-y-1.5 text-sm font-medium">
              <span>Password</span>
              <Input
                type="password"
                autoComplete="current-password"
                maxLength={256}
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
                disabled={pending}
              />
            </label>
            {(error || notice) && (
              <p
                role="alert"
                className="rounded-md bg-danger p-3 text-sm leading-relaxed text-danger-foreground"
              >
                {error || notice}
              </p>
            )}
            <Button className="w-full" size="sm" disabled={pending}>
              {pending ? 'Signing in…' : 'Continue'}
            </Button>
            <p className="text-xs leading-relaxed text-muted-foreground">
              Sign in again after reloading this page.
            </p>
          </form>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  )
}
