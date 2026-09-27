/**
 * Status vocabulary: every status has a text label; color only supplements.
 * Factory-local time formatting for Asia/Kolkata per the pinned timezone.
 */

import type { DomainOutcome, Issue, Verdict } from '@/lib/api'

const FACTORY_TZ = 'Asia/Kolkata'

export function formatInstant(iso: string): string {
  const date = new Date(iso)
  return new Intl.DateTimeFormat('en-IN', {
    timeZone: FACTORY_TZ,
    weekday: 'short',
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
    timeZoneName: 'short',
  }).format(date)
}

export function formatInterval(startIso: string, endIso: string): string {
  const start = new Date(startIso)
  const end = new Date(endIso)
  const fmt = new Intl.DateTimeFormat('en-IN', {
    timeZone: FACTORY_TZ,
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
  return `${fmt.format(start)} to ${fmt.format(end)} IST`
}

export function shortDigest(digest: string | null | undefined): string {
  if (!digest) return ''
  return digest.length > 19 ? `${digest.slice(0, 19)}…` : digest
}

type OutcomeTone = 'ready' | 'rejected' | 'blocked' | 'abstain'

export const OUTCOME_META: Record<DomainOutcome, { label: string; tone: OutcomeTone; hint: string }> = {
  READY_FOR_REVIEW: {
    label: 'Ready for review',
    tone: 'ready',
    hint: 'A supported proposal passed every independent constraint check.',
  },
  REJECTED_BY_CONSTRAINT: {
    label: 'Rejected by constraint',
    tone: 'rejected',
    hint: 'The policy proposed, but independent validation rejected the proposal.',
  },
  NEEDS_CONTEXT: {
    label: 'Needs context',
    tone: 'blocked',
    hint: 'Missing or stale evidence could conceal a feasible candidate; the policy did not run.',
  },
  CONFLICTING_CONTEXT: {
    label: 'Conflicting context',
    tone: 'blocked',
    hint: 'The pinned sources assert incompatible facts; nothing can be concluded.',
  },
  NO_FEASIBLE_CANDIDATE: {
    label: 'No feasible candidate',
    tone: 'abstain',
    hint: 'The bounded candidate pool is conclusively excluded; this is an abstention, not an error.',
  },
}

export const VERDICT_META: Record<Verdict, { label: string }> = {
  PASS: { label: 'Pass' },
  FAIL: { label: 'Fail' },
  NOT_EVALUATED: { label: 'Not evaluated' },
}

export function issueSubject(issue: Issue): string {
  return issue.subject ? ` · ${issue.subject}` : ''
}

export function isRejectedOutcome(outcome: DomainOutcome | null): boolean {
  return outcome === 'REJECTED_BY_CONSTRAINT'
}
