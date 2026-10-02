import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router'
import { useAuth } from '@/components/Auth'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { workspaceApi, type Workspace } from '@/lib/workspaces'

function MembershipForm({ workspace }: { workspace: Workspace }) {
  const [account, setAccount] = useState('')
  const invitation = useMutation({ mutationFn: () => workspaceApi.invite(workspace.id, { account_id: account.trim() }), retry: false })
  return <form className="mt-4 space-y-3" onSubmit={(event) => { event.preventDefault(); invitation.mutate() }}><label className="block text-xs font-medium">Invited account ID<Input className="mt-1" value={account} onChange={(event) => { setAccount(event.target.value); invitation.reset() }} required maxLength={64} disabled={invitation.isPending} /></label><p className="text-xs leading-5 text-zinc-600">Ask the invited person for their account ID. Adding a member gives them access to this workspace’s records.</p><Button size="sm" disabled={invitation.isPending || !account.trim()}>Add workspace member</Button>{invitation.isSuccess && <p role="status" className="text-sm">Member added to this workspace.</p>}{invitation.isError && <p role="alert" className="text-sm text-red-800">{invitation.error.message}</p>}</form>
}
export function WorkspacesPage() {
  const { user } = useAuth()
  const client = useQueryClient()
  const [name, setName] = useState('')
  const workspaces = useQuery({ queryKey: ['workspaces', user?.id], queryFn: workspaceApi.list, enabled: !!user, retry: false })
  const create = useMutation({ mutationFn: () => workspaceApi.create({ name: name.trim() }), onSuccess: async () => { setName(''); await client.invalidateQueries({ queryKey: ['workspaces', user?.id] }) }, retry: false })
  return <div className="space-y-6"><header><h1 className="text-3xl font-semibold">Private workspaces</h1><p className="mt-2 max-w-2xl text-sm leading-6 text-zinc-600">Keep factory investigations within a workspace shared with invited members. Public synthetic examples remain separate.</p></header>{!user ? <p className="rounded border p-5">Sign in to view your workspaces.</p> : <><p className="break-all rounded border bg-white p-4 text-xs">Your account ID: {user.id}</p>{user.role === 'owner' && <form className="max-w-xl space-y-3 rounded border bg-white p-5" onSubmit={(event) => { event.preventDefault(); create.mutate() }}><label className="block text-sm font-medium">New workspace name<Input className="mt-1" required minLength={3} maxLength={120} value={name} onChange={(event) => setName(event.target.value)} disabled={create.isPending} /></label><Button size="sm" disabled={create.isPending || name.trim().length < 3}>Create private workspace</Button>{create.isError && <p role="alert">{create.error.message}</p>}</form>}{workspaces.isPending ? <p role="status">Loading workspaces…</p> : workspaces.isError ? <div role="alert"><p>{workspaces.error.message}</p><Button onClick={() => workspaces.refetch()}>Retry</Button></div> : workspaces.data.items.length ? <div className="grid gap-4 sm:grid-cols-2">{workspaces.data.items.map((workspace) => <article key={workspace.id} className="min-w-0 rounded border bg-white p-5"><h2 className="font-semibold">{workspace.name}</h2><p className="mt-2 break-all text-xs text-zinc-600">Private · {workspace.role} · {workspace.id}</p>{workspace.role === 'owner' && <MembershipForm workspace={workspace} />}</article>)}</div> : <p>No workspace memberships recorded.</p>}<Link className="inline-flex min-h-11 items-center underline" to="/incidents/imports">Import into a private workspace</Link></>}</div>
}
