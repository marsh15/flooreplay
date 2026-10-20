import { apiRequest } from '@/lib/http'

export interface Workspace {
  id: string
  name: string
  visibility: 'private'
  role: 'owner' | 'member'
}
function request<T>(path: string, body?: object): Promise<T> {
  return apiRequest<T>(path, {
    method: body ? 'POST' : 'GET',
    body: body ? JSON.stringify(body) : undefined,
  })
}
export const workspaceApi = {
  list: () => request<{ items: Workspace[] }>('/workspaces'),
  create: (body: { name: string }) => request<Omit<Workspace, 'role'>>('/workspaces', body),
  invite: (id: string, body: { account_id: string }) =>
    request<{ workspace_id: string; account_id: string; role: 'owner' | 'member' }>(
      `/workspaces/${encodeURIComponent(id)}/members`,
      body,
    ),
}
