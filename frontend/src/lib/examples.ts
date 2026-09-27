/**
 * Curated import examples for the demo. They exercise the documented
 * normalization (P/A/blank attendance codes, naive factory-local times)
 * and the rejection path (unsupported values, invalid timestamps,
 * duplicates, unknown operators) without any arbitrary visitor upload.
 */

export interface CuratedExample {
  id: string
  label: string
  description: string
  profile_id: string
  declared_evidence_at: string
  coverage_complete: boolean
  expectsRejection: boolean
  csv: string
}

const ROSTER_P = [
  'O101', 'O108', 'O117', 'O121', 'O126', 'O130', 'O133', 'O141', 'O145',
  'O152', 'O158', 'O163', 'O171', 'O177', 'O182', 'O190', 'O196', 'O204',
  'O210', 'O215', 'O219',
]

export const CURATED_EXAMPLES: CuratedExample[] = [
  {
    id: 'attendance-good',
    label: 'Attendance export (successful)',
    description:
      'Complete roster with real-world codes: P, A, and a blank no-scan cell. Naive timestamps are interpreted as Asia/Kolkata.',
    profile_id: 'attendance-v1',
    declared_evidence_at: '2026-09-22T07:55:00+05:30',
    coverage_complete: true,
    expectsRejection: false,
    csv: [
      'operator_id,status,observed_at,shift_note',
      ...ROSTER_P.map(
        (op) =>
          `${op},${op === 'O145' || op === 'O196' ? 'A' : op === 'O112' ? '' : 'P'},2026-09-22 07:55,${op === 'O112' ? 'no-scan' : 'ok'}`,
      ),
    ].join('\n'),
  },
  {
    id: 'attendance-rejected',
    label: 'Attendance export (rejected)',
    description:
      'Six rows, five different defect kinds: an unsupported status code, an invalid timestamp, a duplicated operator, an unknown operator, and a declared-complete roster with gaps. Publication is refused until every blocking issue is fixed.',
    profile_id: 'attendance-v1',
    declared_evidence_at: '2026-09-22T07:55:00+05:30',
    coverage_complete: true,
    expectsRejection: true,
    csv: [
      'operator_id,status,observed_at,shift_note',
      'O101,P,2026-09-22 07:55,ok',
      'O108,X,2026-09-22 07:55,unknown code',
      'O112,P,tomorrow morning,bad timestamp',
      'O117,P,2026-09-22 07:55,duplicate row',
      'O117,P,2026-09-22 07:55,duplicate row',
      'O999,P,2026-09-22 07:55,not on roster',
    ].join('\n'),
  },
  {
    id: 'skills-good',
    label: 'Skill matrix (successful, forkable)',
    description:
      'Fresh sleeve-attach assessments. Publish this and fork the stale hero scenario onto it: the replay unblocks and proposes O219.',
    profile_id: 'skills-v1',
    declared_evidence_at: '2026-09-21T15:30:00+05:30',
    coverage_complete: true,
    expectsRejection: false,
    csv: [
      'operator_id,operation_id,level,assessed_at',
      'O219,OP-SLM,3,2026-09-21 15:00',
      'O112,OP-SLM,3,2026-09-21 15:00',
      'O152,OP-SLM,2,2026-09-21 15:00',
      'O204,OP-SLM,4,2026-09-21 15:00',
      'O130,OP-SLM,2,2026-09-21 15:00',
      'O215,OP-SLM,2,2026-09-21 15:00',
    ].join('\n'),
  },
]
