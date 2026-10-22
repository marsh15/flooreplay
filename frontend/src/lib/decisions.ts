import { apiNoContent, apiRequest } from '@/lib/http'
import type {
  AdoptPolicyBody,
  DecisionRecord,
  DecisionTimeline,
  DecisionView,
  ImportPreview,
  ImportPreviewInput,
  ImportPublishResult,
  OrdersResponse,
  PolicyDiffResponse,
  PolicyList,
  PublishImportBody,
  RecordDecisionBody,
  RegressionRun,
  ResolveReviewItemBody,
  ReviewItemsResponse,
  StartRegressionRunBody,
} from '@/lib/decisions-types'

const base = '/decisions'
const pathId = (value: string) => encodeURIComponent(value)

export function listOrders(): Promise<OrdersResponse> {
  return apiRequest(`${base}/orders`)
}

export function getOrderDecision(
  orderId: string,
  options: { cutoff?: string; policy?: string } = {},
): Promise<DecisionView> {
  const query = new URLSearchParams()
  if (options.cutoff) query.set('cutoff', options.cutoff)
  if (options.policy) query.set('policy', options.policy)
  const suffix = query.size ? `?${query.toString()}` : ''
  return apiRequest(`${base}/orders/${pathId(orderId)}${suffix}`)
}

export function getOrderTimeline(orderId: string): Promise<DecisionTimeline> {
  return apiRequest(`${base}/orders/${pathId(orderId)}/timeline`)
}

export function recordDecision(orderId: string, body: RecordDecisionBody): Promise<DecisionRecord> {
  return apiRequest(`${base}/orders/${pathId(orderId)}/records`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function listPolicies(): Promise<PolicyList> {
  return apiRequest(`${base}/policies`)
}

export function getPolicyDiff(
  baseDigest: string,
  candidateDigest: string,
): Promise<PolicyDiffResponse> {
  const query = new URLSearchParams({ base: baseDigest, candidate: candidateDigest })
  return apiRequest(`${base}/policies/diff?${query.toString()}`)
}

export function startRegressionRun(body: StartRegressionRunBody): Promise<RegressionRun> {
  return apiRequest(`${base}/regression-runs`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function getRegressionRun(id: string): Promise<RegressionRun> {
  return apiRequest(`${base}/regression-runs/${pathId(id)}`)
}

export function adoptPolicy(digest: string, body: AdoptPolicyBody): Promise<void> {
  return apiNoContent(`${base}/policies/${pathId(digest)}/adopt`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function listReviewItems(): Promise<ReviewItemsResponse> {
  return apiRequest(`${base}/review-items`)
}

export function resolveReviewItem(id: string, body: ResolveReviewItemBody): Promise<void> {
  return apiNoContent(`${base}/review-items/${pathId(id)}/resolve`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function previewImport(input: ImportPreviewInput): Promise<ImportPreview> {
  const form = new FormData()
  form.set('file', input.file)
  form.set('profile', input.profile)
  form.set('column_mapping', JSON.stringify(input.column_mapping))
  form.set('as_of', input.as_of)
  if (input.units) form.set('units', JSON.stringify(input.units))
  if (input.coverage_qualities)
    form.set('coverage_qualities', JSON.stringify(input.coverage_qualities))
  return apiRequest(`${base}/imports/preview`, { method: 'POST', body: form })
}

export function publishImport(body: PublishImportBody): Promise<ImportPublishResult> {
  return apiRequest(`${base}/imports/publish`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}
