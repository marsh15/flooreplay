import { useQuery } from '@tanstack/react-query'

import { useAuth } from '@/components/Auth'
import { DEMO_WORKSPACE, decisionWorkspace, useDecisionWorkspace } from '@/lib/decision-workspace'
import { workspaceApi } from '@/lib/workspaces'

/** Chooses which workspace the decision screens read. Signed-out visitors only have the demo. */
export function WorkspacePicker() {
  const { user, epoch } = useAuth()
  const selected = useDecisionWorkspace()
  const workspaces = useQuery({
    queryKey: ['workspaces', user?.id ?? 'public', epoch],
    queryFn: workspaceApi.list,
    enabled: Boolean(user),
  })
  const own = workspaces.data?.items ?? []
  if (!user) {
    return (
      <p className="text-sm text-muted-foreground">
        Showing the public synthetic demo. Sign in to use a private workspace.
      </p>
    )
  }
  const known = selected === DEMO_WORKSPACE || own.some((item) => item.id === selected)
  return (
    <label className="block max-w-sm space-y-1 text-sm font-medium" htmlFor="decision-workspace">
      Workspace
      <select
        id="decision-workspace"
        aria-label="Workspace"
        className="h-10 w-full rounded-sm border border-input bg-card px-3 focus-visible:outline-2"
        value={known ? selected : DEMO_WORKSPACE}
        onChange={(event) => decisionWorkspace.set(event.currentTarget.value)}
      >
        <option value={DEMO_WORKSPACE}>Public demo (synthetic, read only)</option>
        {own.map((item) => (
          <option key={item.id} value={item.id}>
            {item.name}
          </option>
        ))}
      </select>
    </label>
  )
}
