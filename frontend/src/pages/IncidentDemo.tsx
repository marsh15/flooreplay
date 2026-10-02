import { useState } from 'react'
import { Link } from 'react-router'

type DemoProgress =
  | { kind: 'inspect' }
  | { kind: 'assign' }
  | { kind: 'check'; assignee: string }
  | { kind: 'complete'; assignee: string; outcome: 'confirmed' | 'inconclusive'; rationale: string }

const button = 'min-h-11 rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-40'
const field = 'mt-2 block min-h-11 w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm'

export function IncidentDemoPage() {
  const [progress, setProgress] = useState<DemoProgress>({ kind: 'inspect' })
  const [assignee, setAssignee] = useState('')
  const [outcome, setOutcome] = useState<'confirmed' | 'inconclusive'>('inconclusive')
  const [rationale, setRationale] = useState('')
  const step = progress.kind === 'inspect' ? 1 : progress.kind === 'assign' ? 2 : progress.kind === 'check' ? 3 : 4
  function reset() {
    setProgress({ kind: 'inspect' })
    setAssignee('')
    setOutcome('inconclusive')
    setRationale('')
  }
  return (
    <article className="mx-auto max-w-3xl space-y-6">
      <header className="space-y-3">
        <p className="text-xs font-semibold uppercase tracking-wider text-zinc-600">Guided simulation · synthetic example</p>
        <h1 className="text-3xl font-semibold tracking-tight">Start the example investigation</h1>
        <p className="leading-7 text-zinc-700">Find what the records support, choose a next check, and record its result. FloorReplay helps you investigate a production disruption without treating a calculation as a confirmed cause.</p>
        <p className="rounded-md border border-blue-200 bg-blue-50 p-3 text-sm leading-6 text-blue-950">Your entries stay in this page only. No sign-in, AI request, shared record change, or owner access is needed. Reloading or leaving this page clears the simulation.</p>
      </header>
      <ol aria-label="Investigation steps" className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4">
        {['Inspect evidence', 'Assign a check', 'Record result', 'Review finding'].map((label, index) => <li key={label} aria-current={step === index + 1 ? 'step' : undefined} className={`rounded-md border p-3 ${step === index + 1 ? 'border-zinc-900 bg-zinc-900 text-white' : 'border-zinc-200 text-zinc-600'}`}>{index + 1}. {label}</li>)}
      </ol>
      <section aria-labelledby="demo-case-heading" className="space-y-3 rounded-lg border border-zinc-200 p-4 sm:p-6">
        <h2 id="demo-case-heading" className="text-lg font-semibold">Line A: output fell during the morning shift</h2>
        <dl className="grid gap-3 text-sm sm:grid-cols-2">
          <div><dt className="font-medium">Calculation coverage</dt><dd className="text-zinc-600">Complete for the recorded output interval</dd></div>
          <div><dt className="font-medium">Evidence completeness</dt><dd className="text-zinc-600">Partial — maintenance confirmation is missing</dd></div>
          <div><dt className="font-medium">Investigation state</dt><dd className="text-zinc-600">Open — cause unconfirmed</dd></div>
          <div><dt className="font-medium">Action state</dt><dd className="text-zinc-600">{progress.kind === 'inspect' || progress.kind === 'assign' ? 'Unassigned check' : progress.kind === 'check' ? 'Assigned check awaiting result' : 'Check recorded; incident remains open'}</dd></div>
        </dl>
        <p className="border-t border-zinc-200 pt-3 text-sm leading-6 text-zinc-600"><strong className="text-zinc-900">Records available through 10:00.</strong> This is the knowledge cutoff: the investigation can only use records available by that time. A later repair note cannot explain what someone knew earlier.</p>
      </section>
      {progress.kind === 'inspect' && <section className="space-y-4" aria-labelledby="inspect-heading">
        <h2 id="inspect-heading" className="text-xl font-semibold">1. Inspect the evidence</h2>
        <div className="space-y-3 rounded-lg border border-zinc-200 p-4 text-sm leading-6">
          <p><strong>Output record · 09:00–10:00:</strong> 72 completed units against a target of 100. The recorded shortfall is 28 units.</p>
          <p><strong>Operator note · 09:20:</strong> “Machine stopped briefly; waiting for maintenance.” No stop duration was recorded.</p>
          <p><strong>Supervisor note · 09:35:</strong> “Material arrived late.” The arrival time and effect on production are unknown.</p>
          <p className="border-t border-zinc-200 pt-3"><strong>Useful finding:</strong> Output was below target. A machine stop and a material delay were reported, but these records do not establish which caused the shortfall or how much either contributed.</p>
        </div>
        <p className="text-sm text-zinc-600">The next useful check is to obtain the maintenance log and compare the stop interval with the output interval.</p>
        <button className={button} onClick={() => setProgress({ kind: 'assign' })}>Choose this next check</button>
      </section>}
      {progress.kind === 'assign' && <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); if (assignee.trim()) setProgress({ kind: 'check', assignee: assignee.trim() }) }}>
        <h2 className="text-xl font-semibold">2. Give the check an owner</h2>
        <p className="text-sm leading-6 text-zinc-600">Check: obtain the maintenance log for the reported machine stop. An owner makes the follow-up actionable.</p>
        <label className="block text-sm font-medium">Check owner<input className={field} value={assignee} onChange={(event) => setAssignee(event.target.value)} required maxLength={100} placeholder="Example: Maintenance lead" /></label>
        <button className={button} disabled={!assignee.trim()}>Assign simulated check</button>
      </form>}
      {progress.kind === 'check' && <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); if (rationale.trim()) setProgress({ kind: 'complete', assignee: progress.assignee, outcome, rationale: rationale.trim() }) }}>
        <h2 className="text-xl font-semibold">3. Record the check result</h2>
        <p className="text-sm text-zinc-600">Assigned to {progress.assignee}. For this simulation, choose what your follow-up found.</p>
        <fieldset className="space-y-3 rounded-md border border-zinc-200 p-4"><legend className="px-1 text-sm font-medium">Simulated result</legend>
          <label className="flex min-h-11 items-start gap-3 text-sm"><input className="mt-1" type="radio" name="outcome" checked={outcome === 'confirmed'} onChange={() => setOutcome('confirmed')} />A maintenance log corroborates the stop; its effect on output remains unmeasured.</label>
          <label className="flex min-h-11 items-start gap-3 text-sm"><input className="mt-1" type="radio" name="outcome" checked={outcome === 'inconclusive'} onChange={() => setOutcome('inconclusive')} />The maintenance log is unavailable; the check is inconclusive.</label>
        </fieldset>
        <label className="block text-sm font-medium">Result rationale<textarea className={field} rows={3} value={rationale} onChange={(event) => setRationale(event.target.value)} required maxLength={1000} placeholder="What did you find, and what is still uncertain?" /></label>
        <button className={button} disabled={!rationale.trim()}>Record simulated result</button>
      </form>}
      {progress.kind === 'complete' && <section aria-labelledby="complete-heading" className="space-y-4 rounded-lg border border-emerald-200 bg-emerald-50 p-4 sm:p-6">
        <h2 id="complete-heading" className="text-xl font-semibold">Example investigation completed</h2>
        <p className="text-sm leading-6">You found a recorded output shortfall, inspected competing explanations, assigned a check to {progress.assignee}, and preserved its result.</p>
        <p className="text-sm leading-6"><strong>Check result:</strong> {progress.outcome === 'confirmed' ? 'The simulated log corroborated the machine stop. Its contribution to lost output is still unknown.' : 'The simulated check could not establish the stop interval.'}</p>
        <p className="break-words text-sm leading-6"><strong>Your rationale:</strong> {progress.rationale}</p>
        <p className="text-sm leading-6"><strong>Cause remains unconfirmed; incident remains open.</strong> Recording a check result does not resolve the incident. Compare material timing and measured output before deciding what caused the loss.</p>
        <Link to="/incidents/INC-001" className="inline-flex min-h-11 items-center rounded-md border border-zinc-400 bg-white px-4 py-2 text-sm font-medium">Open the full example investigation</Link>
      </section>}
      <div className="flex flex-wrap gap-4 border-t border-zinc-200 pt-4"><button onClick={reset} className="min-h-11 rounded-md border border-zinc-300 px-4 text-sm font-medium">Reset simulation</button><Link to="/" className="inline-flex min-h-11 items-center text-sm font-medium underline underline-offset-4">Browse curated examples</Link></div>
    </article>
  )
}
