import { API_BASE } from '@/lib/api'
import { session } from '@/lib/session'

export interface OperationsReport {
  events: { request_id: string; route: string; method: string; status_code: number; failure_category: string | null; elapsed_seconds: number; created_at: string }[]
  operations: { id: string; request_id: string | null; status: string; task: string; incident_id: string | null; analysis_id: string; elapsed_seconds: number | null; provider_receipts: { response_id?: string; request_id?: string; status?: string }[]; inspect_url: string }[]
  allowance_entries: { id: string; purpose: string; operation: string; status: string; reserved_inr: number; charged_inr: number }[]
  alerts: { code: string; severity: string; operation_id?: string; request_id?: string; remediation: string }[]
  execution_model: string
  recovery_policy: string
  limitations: string[]
}

export async function getOperations(query: string): Promise<OperationsReport> {
  const response = await fetch(`${API_BASE}/operations?q=${encodeURIComponent(query)}`, { headers: session.headers() })
  if (!response.ok) throw new Error(response.status === 403 ? 'Owner access is required.' : response.status === 401 ? 'Sign in as an owner to inspect your operations.' : 'Operational evidence is unavailable. Check host logs and readiness.')
  return response.json()
}
