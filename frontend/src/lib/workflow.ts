import type { components } from '@/lib/generated-api'
import { apiRequest } from '@/lib/http'

export interface WorkflowAssignee {
  id: string
  display_name: string
  username: string
  role: 'owner' | 'reviewer'
}
export interface WorkflowActivity {
  id: string
  actor: string
  kind: string
  text: string
  created_at: string
}
export interface WorkflowTask {
  id: string
  incident_id: string
  analysis_id: string
  revision: number
  proposal_id: string
  question: string
  requested_fields: string[]
  assignee_id: string
  assignee_name: string
  due_at: string
  status: 'OPEN' | 'IN_PROGRESS' | 'ANSWERED' | 'COMPLETED' | 'CANCELLED'
  created_by: string
  created_at: string
  updated_at: string
  overdue: boolean
  activities: WorkflowActivity[]
  response: {
    evidence_id: string
    revision: number
    summary: string
    occurred_at: string
    source_ref: string
    details: Record<string, string>
  } | null
  outcome: {
    action_taken: string
    actual_completed_at: string
    observed_good_units: number | null
    observed_at: string | null
    assessment: string
    remaining_uncertainty: string
  } | null
}
export interface IncidentWorkflowData {
  incident_id: string
  current_revision: number
  resolution: 'OPEN' | 'RESOLVED'
  resolution_rationale: string | null
  resolution_activities: WorkflowActivity[]
  tasks: WorkflowTask[]
  handover: {
    summary: string
    cutoff: string
    uncertainties: string[]
    outstanding_checks: WorkflowTask[]
    completed_checks?: WorkflowTask[]
  }
}
export type CreateCheckRequest = components['schemas']['CheckCreateRequest']
export type UpdateCheckRequest = components['schemas']['CheckUpdateRequest']
export type RespondCheckRequest = components['schemas']['CheckResponseRequest']
export type CompleteCheckRequest = components['schemas']['CheckCompleteRequest']
export type ResolveIncidentRequest = components['schemas']['IncidentResolutionRequest']

function request<T>(path: string, body?: object): Promise<T> {
  return apiRequest<T>(path, {
    method: body ? 'POST' : 'GET',
    body: body ? JSON.stringify(body) : undefined,
  })
}
const encoded = encodeURIComponent
export const workflowApi = {
  assignees: () => request<{ items: WorkflowAssignee[] }>('/workflow/assignees'),
  get: (id: string) => request<IncidentWorkflowData>(`/incidents/${encoded(id)}/workflow`),
  create: (analysisId: string, body: CreateCheckRequest) =>
    request<WorkflowTask>(`/analyses/${encoded(analysisId)}/checks`, body),
  update: (taskId: string, body: UpdateCheckRequest) =>
    request<WorkflowTask>(`/checks/${encoded(taskId)}/update`, body),
  respond: (taskId: string, body: RespondCheckRequest) =>
    request<WorkflowTask>(`/checks/${encoded(taskId)}/respond`, body),
  complete: (taskId: string, body: CompleteCheckRequest) =>
    request<WorkflowTask>(`/checks/${encoded(taskId)}/complete`, body),
  resolution: (id: string, body: ResolveIncidentRequest) =>
    request<IncidentWorkflowData>(`/incidents/${encoded(id)}/resolution`, body),
}
