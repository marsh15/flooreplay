import { useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Link } from 'react-router'
import { incidentApi, type AiRun, type AiTask, type AnalysisReport } from '@/lib/incidents'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useAuth } from '@/components/Auth'

const TASKS: AiTask[] = ['question', 'investigation', 'summary', 'recovery', 'note']
export function OpenAiPanel({ report, enabled, reasons, onEvidence }: { report: AnalysisReport; enabled: boolean; reasons: string[]; onEvidence: (id: string) => void }) {
  const { user } = useAuth()
  const [task, setTask] = useState<AiTask>('question')
  const [question, setQuestion] = useState('What does the available evidence support?')
  const [retrievalMode, setRetrievalMode] = useState<'evidence_only' | 'hybrid'>('evidence_only')
  const [corpusId, setCorpusId] = useState('')
  const corpora = useQuery({ queryKey: ['corpora'], queryFn: incidentApi.corpora, enabled })
  const selectedCorpus = corpusId || corpora.data?.items[0]?.id || ''
  const [requestKey, setRequestKey] = useState('')
  const [run, setRun] = useState<AiRun | null>(null)
  const create = useMutation({ mutationFn: (key: string) => incidentApi.createAiRun(report.id, { idempotency_key: key, task, question: question.trim(), retrieval_mode: retrievalMode, ...(retrievalMode === 'hybrid' ? { corpus_id: selectedCorpus } : {}) }), onSuccess: setRun })
  const recover = useMutation({ mutationFn: () => incidentApi.aiRunByRequest(requestKey), onSuccess: setRun })
  const status = useQuery({ queryKey: ['ai-run', run?.id], queryFn: () => incidentApi.aiRun(run!.id), enabled: run?.status === 'RUNNING', refetchInterval: (query) => query.state.data?.status === 'RUNNING' ? 2000 : false })
  const current = status.data ?? run
  const output = current?.status === 'COMPLETED' ? current.result?.output : undefined
  const claims = output?.claims ?? output?.selected_claims ?? output?.hypotheses?.map((item) => item.explanation) ?? output?.assertions?.map((item) => item.assertion) ?? []
  return <section className="space-y-3 rounded border bg-white p-4"><h2 className="text-base font-semibold">OpenAI draft</h2><p className="text-xs text-zinc-600">Drafts require human review. Calculated metrics and uncertainty remain attached to every draft.</p>
    {!enabled && <p role="status" className="text-sm text-amber-900">{reasons.join(' ')}</p>}
    <div className="flex flex-wrap gap-3"><label className="text-xs">Task<select aria-label="OpenAI task" className="ml-2 rounded border p-2" value={task} onChange={(event) => { const value = TASKS.find((item) => item === event.target.value); if (value) setTask(value) }}>{TASKS.map((item) => <option key={item}>{item}</option>)}</select></label></div>
    <label className="block text-xs">Evidence retrieval<select className="ml-2 rounded border p-2" value={retrievalMode} onChange={(event) => setRetrievalMode(event.target.value === 'hybrid' ? 'hybrid' : 'evidence_only')}><option value="evidence_only">Current evidence only</option><option value="hybrid">Hybrid historical retrieval</option></select></label>{retrievalMode === 'hybrid' && <label className="block text-xs">Corpus release<select className="ml-2 rounded border p-2" value={selectedCorpus} onChange={(event) => setCorpusId(event.target.value)}>{corpora.data?.items.map((item) => <option key={item.id}>{item.id}</option>)}</select></label>}
    {task === 'note' && <p className="text-xs text-zinc-600">Extract observations from the pinned source evidence. Confirm draft assertions before publication.</p>}
    <label className="block text-xs">Question or task instruction<textarea className="mt-1 min-h-20 w-full rounded border p-2 text-sm" value={question} maxLength={500} onChange={(event) => setQuestion(event.target.value)} /></label>
    <Button size="sm" disabled={!enabled || create.isPending || current?.status === 'RUNNING' || question.trim().length < 3 || retrievalMode === 'hybrid' && !selectedCorpus} onClick={() => { const key = crypto.randomUUID(); setRequestKey(key); setRun(null); create.mutate(key) }}>{create.isPending ? 'Request in progress…' : 'Generate draft'}</Button>
    <div className="space-y-2 border-t pt-3"><label className="block text-xs">Request identity<Input aria-label="Request identity" value={requestKey} onChange={(event) => setRequestKey(event.target.value)} /></label><Button size="sm" variant="outline" disabled={!user || !requestKey.trim() || recover.isPending} onClick={() => recover.mutate()}>Recover existing request</Button><p className="text-xs text-zinc-500">A lookup retrieves the original operation without starting another paid request. Keep this identity to recover after a connection interruption.</p></div>
    {(create.error || recover.error || status.error) && <p role="alert" className="text-sm text-red-700">{(create.error ?? recover.error ?? status.error)?.message}</p>}
    {current && <div aria-live="polite" className="space-y-3 border-t pt-3"><p className="text-xs font-semibold">{current.status} · {current.configuration?.generation_model ?? 'OpenAI'}{output ? ' · Awaiting human review' : ''}</p>{current.result?.reason && <p>{current.result.reason}</p>}{current.result?.errors?.map((error, index) => <p role="alert" key={index} className="text-sm text-red-700">{error === 'MODEL_ACCESS_UNAVAILABLE' ? 'The configured model is unavailable to this API project.' : error === 'PROVIDER_TEMPORARILY_UNAVAILABLE' ? 'The provider is temporarily unavailable.' : error}</p>)}
      {claims.map((claim, index) => <article key={index} className="space-y-2 rounded bg-zinc-50 p-3"><p className="text-sm">{claim.text}</p><div className="flex flex-wrap gap-2">{claim.evidence_ids.map((id) => <button key={id} className="text-xs underline" onClick={() => onEvidence(id)}>{id}</button>)}</div>{claim.historical_refs?.map((id) => { const excerpt = current.packet?.historical_evidence?.find((item) => item.id === id); return <blockquote key={id} className="border-l-2 pl-2 text-xs"><strong>Historical excerpt · {id}:</strong> {excerpt?.text ?? excerpt?.excerpt ?? 'Unavailable'}</blockquote> })}{claim.metric_ids.map((id) => { const metric = claim.rendered_metrics?.find((item) => item.id === id) ?? current.packet?.metrics?.find((item) => item.id === id); return <p key={id} className="text-xs"><strong>{id}:</strong> {metric ? `${metric.value ?? 'Unavailable'} ${metric.unit}` : 'Metric reference unavailable'}{metric?.formula && ` · ${metric.formula}`}{metric?.input_refs?.map((ref) => <button key={ref} className="ml-2 text-xs underline" onClick={() => onEvidence(ref)}>{ref}</button>)}</p> })}</article>)}
      {output?.hypotheses?.map((item, index) => <div key={index} className="space-y-1 text-xs"><p><strong>Counterevidence:</strong> {item.counterevidence_ids.join(', ') || 'None cited'}</p><p><strong>Limitations:</strong> {item.limitations.join('; ')}</p><p><strong>Next checks:</strong> {item.next_checks.join('; ')}</p></div>)}
      {output?.assertions?.map((item, index) => <div key={index} className="space-y-1 text-xs"><blockquote className="border-l-2 pl-2">{item.source_span}</blockquote><p>Source: {item.source_id} · Mentioned: {item.mentioned_entities.join(', ')}</p><p>Uncertainty: {item.uncertainty}</p></div>)}
      {output?.proposals?.map((item, index) => <div key={index} className="space-y-1 rounded border p-3 text-sm"><p>{item.catalog_action_id} · {item.owner_role}</p><p className="text-xs">Prerequisites: {item.prerequisites.join('; ')}</p><div className="flex gap-2">{item.evidence_ids.map((id) => <button key={id} className="text-xs underline" onClick={() => onEvidence(id)}>{id}</button>)}</div><p className="text-xs text-amber-900">Draft recommendation · requires a version-bound human review.</p></div>)}
      {[...(output?.limitations ?? []), ...(output?.abstention_reasons ?? []), ...(output?.unresolved_issues ?? []), ...(current.result?.validation?.errors ?? [])].map((item, index) => <p key={index} className="text-xs text-amber-900">{item}</p>)}
      {current.task === 'note' && output && <p className="text-xs text-amber-900">Extracted assertions are drafts. An owner must confirm the source and import it before it becomes incident evidence.</p>}
    </div>}
  </section>
}

export function HybridPanel({ report, enabled }: { report: AnalysisReport; enabled: boolean }) {
  const [query, setQuery] = useState(report.summary)
  const [corpusId, setCorpusId] = useState('')
  const corpora = useQuery({ queryKey: ['corpora'], queryFn: incidentApi.corpora, enabled })
  const selected = corpusId || corpora.data?.items[0]?.id || ''
  const search = useMutation({ mutationFn: () => incidentApi.hybridSearch({ query, corpus_id: selected, cutoff: report.cutoff, exclude_id: report.incident_id, idempotency_key: crypto.randomUUID() }) })
  return <section className="space-y-3 rounded border bg-white p-4"><h2 className="font-semibold">Hybrid precedent search</h2>{enabled ? <><label className="block text-xs">Pinned corpus<select className="ml-2 rounded border p-2" value={selected} onChange={(event) => setCorpusId(event.target.value)}>{corpora.data?.items.map((item) => <option key={item.id}>{item.id}</option>)}</select></label><label className="block text-xs">Search evidence<Input value={query} onChange={(event) => setQuery(event.target.value)} /></label><Button size="sm" disabled={!selected || !query.trim() || search.isPending} onClick={() => search.mutate()}>Search hybrid precedents</Button></> : <p className="text-xs text-zinc-600">Sign in with reviewer access and use an indexed corpus for semantic retrieval. Lexical precedents remain available below.</p>}{search.error && <p role="alert" className="text-xs text-red-700">{search.error.message}</p>}{search.data && <p className="text-xs text-zinc-500">Pinned release: {search.data.manifest.corpus_id} · cutoff: {search.data.manifest.cutoff}</p>}{search.data?.results.map((item) => <article key={`${item.id}-${item.revision}`} className="space-y-2 border-t pt-3"><Link className="text-sm underline" to={`/incidents/${encodeURIComponent(item.id)}?revision=${item.revision}`}>{item.title}</Link><p className="text-xs">{item.match_reason}</p><p className="text-xs"><strong>Differences:</strong> {item.differences.join('; ')}</p>{item.excerpts?.map((excerpt) => <blockquote key={excerpt.id} className="border-l-2 pl-2 text-xs">{excerpt.text ?? excerpt.excerpt} · {excerpt.source_id ?? excerpt.id}</blockquote>)}</article>)}</section>
}
export function ExportReport({ report, enabled }: { report: AnalysisReport; enabled: boolean }) {
  const exportFile = useMutation({ mutationFn: () => incidentApi.exportReport(report.id), onSuccess: (blob) => { const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = `${report.incident_id}-revision-${report.revision}.json`; link.click(); URL.revokeObjectURL(url) } })
  return <div><Button className="mt-3" size="sm" variant="outline" disabled={!enabled || exportFile.isPending} onClick={() => exportFile.mutate()}>Export portable report</Button>{!enabled && <p className="mt-1 text-xs text-zinc-500">Reviewer sign-in required for export.</p>}{exportFile.error && <p role="alert" className="text-xs text-red-700">{exportFile.error.message}</p>}</div>
}
