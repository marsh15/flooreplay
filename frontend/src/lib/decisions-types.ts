export type GateState = 'READY' | 'STALE' | 'INCOMPLETE' | 'CONFLICTING'
export type ConstraintStatus = 'PASS' | 'FAIL' | 'NOT_EVALUATED'
export type Outcome = 'ACCEPT' | 'ACCEPT_WITH_CONDITIONS' | 'DECLINE' | 'NEEDS_REVIEW'

export interface GateFinding {
  code: string
  state: GateState
  entity_key: string
  fact_ids: string[]
  detail: string
  rule_id: string | null
}

export interface GateResult {
  state: GateState
  findings: GateFinding[]
  coverage_used: { artifact_id: string; as_of: string; qualities: string[] } | null
}

export interface Step {
  label: string
  expression: string
  value: string
}

export interface ConstraintResult {
  constraint: 'FABRIC' | 'SAFETY' | 'TRIMS' | 'CAPACITY' | 'OVERTIME' | 'APPROVAL'
  subject: string
  status: ConstraintStatus
  fact_ids: string[]
  steps: Step[]
  detail: string
  consumed_by: string[]
  pending_review_fact_ids: string[]
}

export type Condition =
  | { type: 'overtime'; lines: number; hours_per_line_per_day: number; days: number }
  | {
      type: 'split_shipment'
      colour: string
      covered_qty: number
      remainder_qty: number
      remainder_ship_date: string
    }

export interface RecommendationView {
  outcome: Outcome
  candidate_outcome: Outcome | null
  conditions: Condition[]
  reasons: string[]
}

export interface FactView {
  id: string
  kind: string
  entity_key: string
  payload: Record<string, unknown>
  valid_from: string
  valid_to: string | null
  known_at: string
  supersedes_id: string | null
  source: string
  artifact_id: string | null
}

export interface DecisionRecord {
  id: string
  recorded_at: string
  reviewer: string
  engine_outcome: Outcome
  final_outcome: Outcome
  reason: string
  override: boolean
}

export interface DecisionView {
  order_id: string
  cutoff: string
  settled: boolean
  policy: { digest: string; label: string; engine_version: string }
  snapshot_digest: string
  decision_digest: string
  gate: GateResult
  constraints: ConstraintResult[]
  recommendation: RecommendationView
  facts: FactView[]
  records: DecisionRecord[]
}

export interface OrderSummary {
  order_id: string
  buyer: string
  style_id: string
  ship_date: string
  total_qty: string
  latest: { outcome: Outcome; gate_state: GateState; cutoff: string } | null
}

export interface OrdersResponse {
  orders: OrderSummary[]
}

export interface TimelineEvent {
  known_at: string
  fact_id: string
  kind: string
  entity_key: string
  source: string
  summary: string
}

export interface DecisionTimeline {
  knowledge_times: string[]
  events: TimelineEvent[]
}

export interface RecordDecisionBody {
  cutoff: string
  policy_digest: string
  final_outcome: Outcome
  reason: string
}

export interface PolicySummary {
  digest: string
  label: string
  engine_version: string
  created_at: string
}

export interface PolicyList {
  adopted: string
  policies: PolicySummary[]
}

export interface PolicyChange {
  path: string
  before: unknown
  after: unknown
}

export interface PolicyDiffResponse {
  changes: PolicyChange[]
}

export type RegressionClassification =
  'UNCHANGED_PASS' | 'UNCHANGED_FAIL' | 'FIXED' | 'REGRESSION' | 'NOT_COMPARABLE'

export interface RegressionCase {
  case_id: string
  title: string
  baseline: 'PASS' | 'FAIL'
  candidate: 'PASS' | 'FAIL' | null
  classification: RegressionClassification
}

export interface RegressionRun {
  id: string
  policy_digest: string
  baseline_digest: string
  suite_digest: string
  engine_version: string
  complete: boolean
  cases: RegressionCase[]
}

export interface StartRegressionRunBody {
  policy_digest: string
}

export interface AdoptPolicyBody {
  run_id: string
  acknowledgements: Record<string, string>
}

export interface ReviewField {
  name: string
  value: unknown
  evidence: string | null
  span: { start: number; end: number; text: string } | null
  status: string
  failed_checks: string[]
}

export interface ReviewItem {
  id: string
  kind: 'extraction' | 'decision'
  note_id?: string
  note_text?: string
  fields?: ReviewField[]
  order_id?: string
  created_at: string
  assignee: string | null
}

export interface ReviewItemsResponse {
  items: ReviewItem[]
}

export type ReviewAction = 'confirm' | 'correct' | 'reject'

export interface ResolveReviewItemBody {
  action: ReviewAction
  corrected?: Record<string, { value: unknown; evidence: string | null }>
  reason: string
}

export type ImportProfile =
  | 'erp-fabric-stock'
  | 'sheet-trims-status'
  | 'shift-capacity'
  | 'supplier-updates'
  | 'order-requests'
  | 'notes'

export type SourceProfile =
  | 'erp_fabric_stock'
  | 'sheet_trims_status'
  | 'shift_capacity'
  | 'supplier_updates'
  | 'notes'
  | 'order_requests'
  | 'review_queue'

export interface ImportProblem {
  row: number
  field: string
  code: string
  message: string
}

export interface NoteRecord {
  note_id: string
  lot_hint: string | null
  text: string
  note_digest: string
}

export interface ImportPreview {
  profile: SourceProfile
  filename: string
  raw_digest: string
  as_of: string
  facts: FactView[]
  notes: NoteRecord[]
  problems: ImportProblem[]
  coverage: { profile: SourceProfile; as_of: string; qualities: string[] } | null
  status: 'READY' | 'BLOCKED'
  preview_digest: string
}

export interface ImportPreviewInput {
  file: File
  profile: ImportProfile
  column_mapping: Record<string, string>
  as_of: string
  units?: Record<string, string>
  coverage_qualities?: string[]
}

export interface PublishImportBody {
  preview_digest: string
  idempotency_key: string
}

export interface ImportPublishResult {
  artifact_id: string
  facts_created: number
}
