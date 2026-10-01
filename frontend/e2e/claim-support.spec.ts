import { expect, test } from '@playwright/test'
import fs from 'node:fs'

const report = JSON.parse(fs.readFileSync('src/data/hero-report.json', 'utf8'))
const revision = JSON.parse(fs.readFileSync('src/data/hero-revision.json', 'utf8'))
const library = JSON.parse(fs.readFileSync('src/data/incident-library.json', 'utf8'))
const claim = { text: 'The output record establishes a shortfall.', evidence_ids: ['EV-MAT-1'], metric_ids: [], historical_refs: [], source_fields: [] }

for (const variant of [
  { task: 'question', output: { claims: [claim] }, path: 'claims.0' },
  { task: 'summary', output: { selected_claims: [claim] }, path: 'selected_claims.0' },
  { task: 'investigation', output: { hypotheses: [{ explanation: claim, counterevidence_ids: [], limitations: [], next_checks: [] }] }, path: 'hypotheses.0.explanation' },
  { task: 'note', output: { assertions: [{ assertion: claim, source_id: 'EV-MAT-1', source_span: 'Supervisor observation', mentioned_entities: [], uncertainty: 'Verification required' }] }, path: 'assertions.0.assertion' },
]) {
  test(`${variant.task} claim review retries the same authenticated annotation and survives recovery`, async ({ page }) => {
    const requests: Record<string, unknown>[] = []
    let paidRequests = 0
    let savedReview: Record<string, unknown> | null = null
    const fingerprint = 'sha256:' + 'a'.repeat(64)
    const run = () => ({ id: 'claim-run', status: 'COMPLETED', output_digest: fingerprint, analysis_id: report.id, task: variant.task, result: { output: variant.output }, claim_reviews: savedReview ? [savedReview] : [] })
    await page.route('**/api/v1/**', async (route) => {
      const path = new URL(route.request().url()).pathname
      const reply = (body: unknown, status = 200) => route.fulfill({ json: body, status })
      if (path.endsWith('/auth/login')) return reply({ token: 'claim-token', user: { id: 'reviewer-1', username: 'reviewer', display_name: 'Reviewer', role: 'reviewer' } })
      if (path.endsWith('/capabilities')) return reply({ reviews_enabled: true, ai: { generation_available: !!route.request().headers().authorization, index_ready: false }, execution_limits: {}, configurations: [] })
      if (path.endsWith('/claim-review')) {
        expect(route.request().headers().authorization).toBe('Bearer claim-token')
        const body = route.request().postDataJSON()
        requests.push(body)
        savedReview = { id: 'review-1', run_id: 'claim-run', claim_path: body.claim_path, supported: body.judgment === 'supported', actor: 'reviewer-1', rationale: body.rationale, output_digest: fingerprint, judgment: body.judgment, flags: body.flags, reviewer_kind: body.reviewer_kind, qualifications: body.qualifications, independent: body.independent }
        if (requests.length === 1) return route.abort()
        return reply(savedReview)
      }
      if (path.endsWith('/ai-runs')) { paidRequests++; return reply(run()) }
      if (path.includes('/ai-runs/by-request/')) return reply(run())
      if (path.endsWith('/review-packet')) return reply({ id: 'claim-run', output_digest: fingerprint, analysis_id: report.id, task: variant.task, provider: 'openai', model: 'mock', output: variant.output, packet: { evidence: [{ id: 'EV-MAT-1', summary: 'Recorded source observation.' }], metrics: [], historical_evidence: [] }, claim_reviews: savedReview ? [savedReview] : [], assessments: [] })
      if (path.endsWith('/review-report')) return reply({ run_id: 'claim-run', output_digest: fingerprint, status: 'AWAITING_INDEPENDENT_HUMAN_REVIEW', total_claims: 1, reviewed_claims: savedReview ? 1 : 0, unreviewed_claims: savedReview ? 0 : 1, supported_claims: 0, unsupported_claims: savedReview ? 1 : 0, insufficient_evidence_claims: 0, independent_human_reviewed_claims: 0, declared_independent_human_reviewers: 0, disagreements: [], reviewers: [], claim_reviews: savedReview ? [savedReview] : [], assessments: [], limitations: [] })
      if (path.endsWith('/incidents')) return reply(library)
      if (path.includes('/revisions/')) return reply(revision)
      if (path.includes('/analyses')) return reply({ ...report, execution_kind: 'live' })
      if (path.endsWith('/corpora')) return reply({ items: [] })
      return reply({}, 404)
    })
    const signIn = async () => {
      await page.getByRole('button', { name: 'Sign in', exact: true }).click()
      await page.getByLabel('Username').fill('reviewer')
      await page.getByLabel('Password').fill('test-password')
      await page.getByRole('button', { name: 'Continue', exact: true }).click()
    }
    await page.goto('/incidents/INC-001?revision=2')
    await signIn()
    await page.getByLabel('OpenAI task').selectOption(variant.task)
    await page.getByRole('button', { name: 'Generate draft' }).click()
    const form = page.getByRole('form', { name: `Claim support review ${variant.path}` })
    await expect(form.getByRole('button', { name: 'Record support review', exact: true })).toBeDisabled()
    await form.getByRole('combobox', { name: 'Claim support', exact: true }).selectOption('unsupported')
    await form.getByLabel('Support rationale').fill('The source reports an observation, without measuring this effect.')
    await form.getByRole('button', { name: 'Record support review', exact: true }).click()
    await expect(form.getByRole('alert')).toContainText('Retry sends the same output identity')
    await expect(form.getByLabel('Support rationale')).toBeDisabled()
    await form.getByRole('button', { name: 'Retry same annotation' }).click()
    await expect(form.getByRole('status')).toContainText('Annotation saved against this exact output')
    expect(requests[0]).toEqual(requests[1])
    expect(requests[0]).toMatchObject({ claim_path: variant.path, judgment: 'unsupported', output_digest: fingerprint })
    await expect(page.getByRole('region', { name: 'Semantic review claim-run' })).toContainText('does not approve a recovery action')
    await page.getByText('Recover an interrupted request', { exact: true }).click()
    const identity = await page.getByLabel('Request identity').inputValue()
    await page.reload()
    await signIn()
    await page.getByText('Recover an interrupted request', { exact: true }).click()
    await page.getByLabel('Request identity').fill(identity)
    await page.getByRole('button', { name: 'Recover existing request' }).click()
    const restored = page.getByRole('region', { name: 'Semantic review claim-run' })
    await restored.getByText('Append-only claim annotations (1)', { exact: true }).click()
    await expect(restored).toContainText('The source reports an observation, without measuring this effect.')
    await expect(restored).toContainText('unsupported · actor reviewer-1')
    expect(paidRequests).toBe(1)
  })
}
