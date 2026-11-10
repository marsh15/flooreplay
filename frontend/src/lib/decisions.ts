import { decisionWorkspace } from '@/lib/decision-workspace'
import type { components } from '@/lib/generated-api'
import { ApiError, apiRequest } from '@/lib/http'
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
  ReviewItem,
  ReviewItemsResponse,
  StartRegressionRunBody,
} from '@/lib/decisions-types'

/**
 * Every call the order decision screens make goes through this module. It speaks the backend's
 * own contract (see `generated-api.ts`) and hands the pages the shapes they render, so a
 * contract change is fixed here and nowhere else.
 */
type Schemas = components['schemas']

const base = '/decisions'
const pathId = (value: string) => encodeURIComponent(value)

/** `/decisions<path>?workspace_id=…&<extra>`: every route is scoped to one workspace. */
function scoped(path: string, extra: Record<string, string | undefined> = {}): string {
  const query = new URLSearchParams({ workspace_id: decisionWorkspace.get() })
  for (const [key, value] of Object.entries(extra)) if (value) query.set(key, value)
  return `${base}${path}?${query.toString()}`
}

function post<T>(path: string, body: unknown, extra?: Record<string, string>): Promise<T> {
  return apiRequest<T>(scoped(path, extra), { method: 'POST', body: JSON.stringify(body) })
}

const NOT_RECORDED = 'Not recorded'

export async function listOrders(): Promise<OrdersResponse> {
  const raw = await apiRequest<Schemas['OrderList']>(scoped('/orders'))
  return {
    orders: raw.items.map((item) => ({
      order_id: item.order_id,
      buyer: item.buyer ?? NOT_RECORDED,
      style_id: item.style_id ?? NOT_RECORDED,
      ship_date: item.ship_date ?? NOT_RECORDED,
      total_qty: item.total_qty ?? NOT_RECORDED,
      latest: item.latest
        ? {
            outcome: item.latest.outcome,
            gate_state: item.latest.gate_state,
            cutoff: item.latest.cutoff,
          }
        : null,
    })),
  }
}

export function getOrderDecision(
  orderId: string,
  options: { cutoff?: string; policy?: string } = {},
): Promise<DecisionView> {
  return apiRequest(
    scoped(`/orders/${pathId(orderId)}`, { cutoff: options.cutoff, policy: options.policy }),
  )
}

export function getOrderTimeline(orderId: string): Promise<DecisionTimeline> {
  return apiRequest(scoped(`/orders/${pathId(orderId)}/timeline`))
}

export function recordDecision(orderId: string, body: RecordDecisionBody): Promise<DecisionRecord> {
  return post(`/orders/${pathId(orderId)}/records`, body)
}

function rawPolicies(): Promise<Schemas['PolicyList']> {
  return apiRequest(scoped('/policies'))
}

export async function listPolicies(): Promise<PolicyList> {
  const raw = await rawPolicies()
  return {
    adopted: raw.adopted,
    policies: raw.items.map((item) => ({
      digest: item.policy_digest,
      label: item.label,
      engine_version: item.engine_version,
      created_at: item.created_at,
    })),
  }
}

function policyDocument(
  list: Schemas['PolicyList'],
  digest: string,
): Schemas['StoredPolicyView']['policy'] {
  const found = list.items.find((item) => item.policy_digest === digest)
  if (!found) throw new ApiError('POLICY_UNKNOWN', 'That policy is not in this workspace.', 404)
  return found.policy
}

export async function getPolicyDiff(
  baseDigest: string,
  candidateDigest: string,
): Promise<PolicyDiffResponse> {
  const list = await rawPolicies()
  return post<Schemas['PolicyDiffView']>('/policies/diff', {
    baseline: policyDocument(list, baseDigest),
    candidate: policyDocument(list, candidateDigest),
  } satisfies Schemas['PolicyDiffRequest'])
}

function readRun(raw: Schemas['RegressionRunView']): RegressionRun {
  return {
    id: raw.id,
    policy_digest: raw.candidate_policy_digest,
    baseline_digest: raw.baseline_policy_digest,
    suite_digest: raw.suite_digest,
    engine_version: raw.engine_version,
    complete: raw.complete,
    cases: raw.cases.map((item) => ({
      case_id: item.case_id,
      title: item.title,
      baseline: item.baseline.verdict ?? null,
      candidate: item.candidate.verdict ?? null,
      classification: item.classification,
    })),
  }
}

/** Runs the whole stored case suite under the adopted policy and the candidate. */
export async function startRegressionRun(body: StartRegressionRunBody): Promise<RegressionRun> {
  const list = await rawPolicies()
  const raw = await post<Schemas['RegressionRunView']>('/regression-runs', {
    baseline: policyDocument(list, list.adopted),
    candidate: policyDocument(list, body.policy_digest),
  } satisfies Schemas['RegressionRequest'])
  return readRun(raw)
}

export async function getRegressionRun(id: string): Promise<RegressionRun> {
  return readRun(await apiRequest(scoped(`/regression-runs/${pathId(id)}`)))
}

/** The newest stored run for a candidate, or null when nobody has run it yet. */
export async function latestRegressionRun(candidateDigest: string): Promise<RegressionRun | null> {
  const raw = await apiRequest<Schemas['RegressionRunList']>(
    scoped('/regression-runs', { candidate: candidateDigest }),
  )
  return raw.items.length ? readRun(raw.items[0]) : null
}

export async function adoptPolicy(_digest: string, body: AdoptPolicyBody): Promise<void> {
  await post(`/regression-runs/${pathId(body.run_id)}/adopt`, {
    acknowledgements: body.acknowledgements,
  } satisfies Schemas['AdoptRequest'])
}

const PENDING_STATES = new Set(['OPEN', 'ASSIGNED'])

/** The backend queues one item per flagged field; the screen shows them together per source. */
export async function listReviewItems(): Promise<ReviewItemsResponse> {
  const raw = await apiRequest<Schemas['ReviewItemList']>(scoped('/review-items'))
  const groups = new Map<string, ReviewItem>()
  for (const row of raw.items) {
    if (!PENDING_STATES.has(row.state)) continue
    const key = row.extraction_id ?? row.evaluation_id ?? row.id
    let item = groups.get(key)
    if (!item) {
      item = {
        id: key,
        kind: row.source_kind === 'EVALUATION' ? 'decision' : 'extraction',
        fields: [],
        field_items: {},
        created_at: row.created_at,
        assignee: row.assignee_id,
        ...(row.entity_key?.startsWith('order:')
          ? { order_id: row.entity_key.slice('order:'.length) }
          : {}),
      }
      groups.set(key, item)
    }
    item.fields = [
      ...(item.fields ?? []),
      {
        name: row.field,
        value: row.claimed_value,
        evidence: row.evidence_span?.text ?? null,
        span: row.evidence_span,
        status: row.field_status,
        failed_checks: row.check_codes,
      },
    ]
    item.field_items[row.field] = row.id
  }
  return { items: [...groups.values()] }
}

function asText(value: unknown): string | null {
  if (value == null) return null
  return typeof value === 'string' ? value : JSON.stringify(value)
}

/** Applies one decision to every flagged field of a review item, one request per field. */
export async function resolveReviewItem(
  item: ReviewItem,
  body: ResolveReviewItemBody,
): Promise<void> {
  const note = body.reason
  for (const field of item.fields ?? []) {
    const id = item.field_items[field.name]
    if (!id) continue
    const route = `/review-items/${pathId(id)}`
    if (body.action === 'reject') {
      await post(`${route}/reject`, { note } satisfies Schemas['NoteRequest'])
    } else if (body.action === 'confirm') {
      await post(`${route}/confirm`, {
        note,
        value: asText(field.value),
      } satisfies Schemas['ConfirmRequest'])
    } else if (body.corrected && field.name in body.corrected) {
      await post(`${route}/correct`, {
        note,
        value: asText(body.corrected[field.name].value),
      } satisfies Schemas['CorrectRequest'])
    }
  }
}

/** What the last preview was built from: publishing sends the same bytes and settings again. */
const previews = new Map<string, Schemas['ImportBody']>()

async function toBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer())
  let binary = ''
  for (let offset = 0; offset < bytes.length; offset += 0x8000)
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000))
  return btoa(binary)
}

export async function previewImport(input: ImportPreviewInput): Promise<ImportPreview> {
  const request: Schemas['ImportBody'] = {
    filename: input.file.name,
    profile: input.profile,
    column_mapping: input.column_mapping,
    as_of: input.as_of,
    timezone: 'Asia/Kolkata',
    units: input.units ?? {},
    coverage_qualities: input.coverage_qualities ?? null,
    content_base64: await toBase64(input.file),
  }
  const raw = await post<Schemas['PreviewView']>('/imports/preview', request)
  previews.set(raw.preview_digest, request)
  const coverage = raw.coverage as { profile: string; as_of: string; qualities: string[] } | null
  return {
    profile: raw.profile as ImportPreview['profile'],
    filename: raw.filename,
    raw_digest: raw.raw_digest,
    as_of: raw.as_of,
    facts: raw.facts as ImportPreview['facts'],
    notes: raw.pending_extraction.map((note) => ({
      note_id: note.note_id,
      lot_hint: note.lot_hint ?? null,
      text: note.text,
      note_digest: note.note_digest,
    })),
    problems: raw.problems,
    coverage: coverage
      ? {
          profile: coverage.profile as ImportPreview['profile'],
          as_of: coverage.as_of,
          qualities: [...coverage.qualities],
        }
      : null,
    status: raw.status,
    preview_digest: raw.preview_digest,
  }
}

export async function publishImport(body: PublishImportBody): Promise<ImportPublishResult> {
  const request = previews.get(body.preview_digest)
  if (!request)
    throw new ApiError(
      'PREVIEW_EXPIRED',
      'This preview is no longer available. Preview the file again before publishing.',
      409,
    )
  const raw = await post<Schemas['PublishView']>('/imports/publish', {
    ...request,
    preview_digest: body.preview_digest,
    idempotency_key: body.idempotency_key,
  } satisfies Schemas['PublishBody'])
  return { artifact_id: raw.artifact_id, facts_created: raw.fact_ids.length }
}
