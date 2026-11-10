import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'

import { PageHeader, Section, StatusTag } from '@/components/board'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { PolicyDiff } from '@/components/decisions/PolicyDiff'
import { RegressionTable } from '@/components/decisions/RegressionTable'
import { WorkspacePicker } from '@/components/decisions/WorkspacePicker'
import { useDecisionWorkspace } from '@/lib/decision-workspace'
import {
  adoptPolicy,
  getPolicyDiff,
  getRegressionRun,
  latestRegressionRun,
  listPolicies,
  startRegressionRun,
} from '@/lib/decisions'
import type { PolicyDiffResponse, RegressionRun } from '@/lib/decisions-types'
import { ApiError } from '@/lib/http'

export function ReplayLab() {
  const workspace = useDecisionWorkspace()
  const policies = useQuery({
    queryKey: ['decisions', 'policies', workspace],
    queryFn: listPolicies,
  })
  const [selectedCandidate, setSelectedCandidate] = useState('')
  const candidateRef = useRef('')
  const [run, setRun] = useState<RegressionRun | null>(null)
  const [storedRunId, setStoredRunId] = useState('')
  const [acknowledgements, setAcknowledgements] = useState<Record<string, string>>({})
  const [notice, setNotice] = useState('')
  const candidate =
    selectedCandidate ||
    policies.data?.policies.find((policy) => policy.digest !== policies.data?.adopted)?.digest ||
    ''
  useEffect(() => {
    candidateRef.current = candidate
  }, [candidate])
  const diffQuery = useQuery<PolicyDiffResponse>({
    queryKey: ['decisions', 'policy-diff', workspace, policies.data?.adopted, candidate],
    queryFn: () => getPolicyDiff(policies.data!.adopted, candidate),
    enabled: Boolean(policies.data?.adopted && candidate && candidate !== policies.data.adopted),
  })
  const storedRun = useQuery({
    queryKey: ['decisions', 'latest-run', workspace, candidate],
    queryFn: () => latestRegressionRun(candidate),
    enabled: Boolean(candidate && candidate !== policies.data?.adopted),
    retry: false,
  })
  useEffect(() => {
    const stored = storedRun.data
    if (!stored || stored.policy_digest !== candidateRef.current) return
    setRun((current) => current ?? stored)
    setStoredRunId((current) => current || stored.id)
    setNotice((current) => current || 'Latest stored regression run loaded.')
  }, [storedRun.data])
  const runMutation = useMutation({
    mutationFn: async (digest: string) => {
      const started = await startRegressionRun({ policy_digest: digest })
      return { runId: started.id, stored: await getRegressionRun(started.id) }
    },
    onSuccess: ({ runId, stored }, requestedDigest) => {
      if (candidateRef.current !== requestedDigest) return
      setStoredRunId(runId)
      setRun(stored.policy_digest === requestedDigest ? stored : null)
      setAcknowledgements({})
      setNotice(
        stored.complete
          ? 'Stored regression run loaded.'
          : 'Run is incomplete; adoption stays disabled.',
      )
    },
    onError: (error, requestedDigest) => {
      if (candidateRef.current !== requestedDigest) return
      setNotice(
        error instanceof ApiError && (error.status === 401 || error.status === 404)
          ? 'Running a regression needs a signed-in member of a private workspace. The public demo shows stored runs only.'
          : 'The regression run could not be stored. Try again.',
      )
    },
  })
  const refreshMutation = useMutation({
    mutationFn: (runId: string) => getRegressionRun(runId),
    onSuccess: (stored, requestedRunId) => {
      if (candidateRef.current !== stored.policy_digest || storedRunId !== requestedRunId) return
      setRun(stored)
      setNotice(
        stored.complete
          ? 'Stored regression run refreshed.'
          : 'Run is incomplete; adoption stays disabled.',
      )
    },
    onError: (_error, requestedRunId) => {
      if (storedRunId === requestedRunId) setNotice('The stored run could not be refreshed.')
    },
  })
  const adoptMutation = useMutation({
    mutationFn: (input: {
      digest: string
      runId: string
      acknowledgements: Record<string, string>
    }) =>
      adoptPolicy(input.digest, {
        run_id: input.runId,
        acknowledgements: input.acknowledgements,
      }),
    onSuccess: (_result, input) => {
      if (candidateRef.current === input.digest) setNotice('Policy adopted')
    },
    onError: (error, input) => {
      if (candidateRef.current !== input.digest) return
      setNotice(
        error instanceof ApiError && error.status === 403
          ? 'Only an owner can adopt a policy.'
          : 'Policy adoption failed. Review the acknowledgements and retry.',
      )
    },
  })

  const selectedPolicy = policies.data?.policies.find((policy) => policy.digest === candidate)
  const regressions = run?.cases.filter((item) => item.classification === 'REGRESSION') ?? []
  const adoptable = Boolean(
    run?.complete &&
    run.id === storedRunId &&
    run.policy_digest === candidate &&
    run.baseline_digest === policies.data?.adopted &&
    run.engine_version === selectedPolicy?.engine_version &&
    candidate &&
    regressions.every((item) => acknowledgements[item.case_id]?.trim()),
  )
  const onCandidateChange = (digest: string) => {
    candidateRef.current = digest
    setSelectedCandidate(digest)
    setRun(null)
    setStoredRunId('')
    setAcknowledgements({})
    setNotice('')
  }

  return (
    <div className="space-y-8">
      <PageHeader title="Replay lab">
        <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">
          Compare a candidate policy with the adopted policy across the frozen order case suite.
          Adoption needs a stored complete run and a written acknowledgement for each regression.
        </p>
      </PageHeader>
      <WorkspacePicker />
      {policies.isPending ? <p role="status">Loading policy list…</p> : null}
      {policies.isError ? <p role="alert">Policies are unavailable. Try again later.</p> : null}
      {policies.data ? (
        <>
          <Section
            title="Candidate policy"
            detail="The selected digest identifies an immutable policy version."
          >
            <label
              className="block max-w-xl space-y-1 text-sm font-medium"
              htmlFor="candidate-policy"
            >
              Candidate policy
              <select
                aria-label="Candidate policy"
                id="candidate-policy"
                className="h-10 w-full rounded-sm border border-input bg-card px-3 focus-visible:outline-2"
                value={candidate}
                onChange={(event) => onCandidateChange(event.currentTarget.value)}
              >
                {policies.data.policies.map((policy) => (
                  <option
                    key={policy.digest}
                    value={policy.digest}
                    disabled={policy.digest === policies.data?.adopted}
                  >
                    {policy.label} · {policy.digest}
                  </option>
                ))}
              </select>
            </label>
            <p className="text-sm text-muted-foreground">
              Adopted: <span className="font-mono">{policies.data.adopted}</span>
              {selectedPolicy ? <> · Engine {selectedPolicy.engine_version}</> : null}
            </p>
          </Section>
          <Section
            title="Policy changes"
            detail="Parameter changes between the adopted and candidate digests."
          >
            {!candidate ? <p role="status">No candidate policy is available.</p> : null}
            {candidate && diffQuery.isPending ? <p role="status">Loading policy changes…</p> : null}
            {diffQuery.isError ? <p role="alert">Policy changes are unavailable.</p> : null}
            {diffQuery.data ? <PolicyDiff changes={diffQuery.data.changes} /> : null}
          </Section>
          <Section
            title="Regression run"
            detail="Every case is compared against its stored expected outcome."
          >
            <Button
              onClick={() => {
                if (candidate) {
                  setRun(null)
                  setStoredRunId('')
                  setNotice('')
                  runMutation.mutate(candidate)
                }
              }}
              disabled={!candidate || candidate === policies.data.adopted || runMutation.isPending}
            >
              {runMutation.isPending ? 'Running regression…' : 'Run regression'}
            </Button>
            {runMutation.isError ? (
              <p role="alert" className="mt-3">
                The regression run failed.
              </p>
            ) : null}
            {storedRunId ? (
              <Button
                variant="outline"
                onClick={() => refreshMutation.mutate(storedRunId)}
                disabled={refreshMutation.isPending}
              >
                {refreshMutation.isPending ? 'Refreshing stored run…' : 'Refresh stored run'}
              </Button>
            ) : null}
            {run ? (
              <div className="mt-5">
                <RegressionTable run={run} />
              </div>
            ) : null}
          </Section>
          {run ? (
            <Section
              title="Regression acknowledgements"
              detail="Write one acknowledgement for every REGRESSION classification."
            >
              {regressions.length ? (
                regressions.map((item) => (
                  <label
                    key={item.case_id}
                    className="block max-w-3xl space-y-1 text-sm font-medium"
                    htmlFor={`ack-${item.case_id}`}
                  >
                    Acknowledgement for {item.title}
                    <Input
                      id={`ack-${item.case_id}`}
                      value={acknowledgements[item.case_id] ?? ''}
                      onChange={(event) => {
                        const value = event.currentTarget.value
                        setAcknowledgements((current) => ({ ...current, [item.case_id]: value }))
                      }}
                      placeholder="Record why this regression is accepted."
                    />
                  </label>
                ))
              ) : (
                <StatusTag tone="success">No regressions to acknowledge</StatusTag>
              )}
              <Button
                onClick={() =>
                  adoptMutation.mutate({ digest: candidate, runId: run.id, acknowledgements })
                }
                disabled={!adoptable || adoptMutation.isPending}
              >
                {adoptMutation.isPending ? 'Adopting…' : 'Adopt policy'}
              </Button>
              {notice ? <p role="status">{notice}</p> : null}
            </Section>
          ) : (
            <div>
              <Button disabled>Adopt policy</Button>
              {notice ? (
                <p role="status" className="mt-2">
                  {notice}
                </p>
              ) : null}
            </div>
          )}
        </>
      ) : null}
    </div>
  )
}
