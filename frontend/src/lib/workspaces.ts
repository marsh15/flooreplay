import { API_BASE, ApiError } from '@/lib/api'
import { session } from '@/lib/session'

export interface Workspace { id: string; name: string; visibility: 'private'; role: 'owner' | 'member' }
async function request<T>(path: string, body?: object): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, { method: body ? 'POST' : 'GET', headers: { 'Content-Type': 'application/json', ...session.headers() }, body: body ? JSON.stringify(body) : undefined })
  if (!response.ok) throw new ApiError('WORKSPACE_REQUEST_FAILED', response.status === 404 ? 'Workspace or account is unavailable.' : 'Workspace request could not be completed.', response.status, response.headers.get('X-Request-ID') ?? undefined)
  return response.json()
}
export const workspaceApi = {
  list: () => request<{ items: Workspace[] }>('/workspaces'),
  create: (body: { name: string }) => request<Omit<Workspace, 'role'>>('/workspaces', body),
  invite: (id: string, body: { account_id: string }) => request<{ workspace_id: string; account_id: string; role: 'owner' | 'member' }>(`/workspaces/${encodeURIComponent(id)}/members`, body),
}
