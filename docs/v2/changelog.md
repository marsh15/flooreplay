# What changed after talking to practitioners

## Purpose

`docs/v2/PLAN.md` is the approved contract for FloorReplay 2.0. Week-1 discovery (see `docs/v2/discovery.md`) may show that a constraint, a policy default, a data source or a workflow assumption in the plan is wrong. This log is the single record of each such change. It exists so that:

- every change to the plan after approval can be traced to the interview it came from, and
- a change that did not come from an interview cannot be presented as one.

Entries are only added for real events. An interview that confirms a draft value without changing it can be logged as "confirmed, no change". Nothing is written here from guesses.

## Entry format

Newest entry last. Each entry has these fields:

```
### <YYYY-MM-DD> <short title>

- Date: the date of the change (not the interview, if different; give both if so)
- Source interview id: P-<nn> from discovery.md, or "none" (state why)
- What changed: before and after, with units. One change per entry where practical.
- PLAN.md section: the heading or decision number that was edited or is now out of date
- Affected tasks / tests: task ids (T8, T21 ...) and test files or invariants touched
- Decided by: owner (the owner decides all changes to the constraint list)
```

Rules:
- Quote an interviewee only if the notes record consent for quoting. Use the anonymised id only.
- Do not record company, buyer or person names.
- If PLAN.md was edited, say so, and keep the old text visible in the entry (the "before").

## Entries

### 2026-10-20 Draft constraint list created; no interviews yet

- Date: 2026-10-20
- Source interview id: none. No interviews have happened. 0 of 2-3 practitioners reached as of this date.
- What changed: `docs/v2/discovery.md` was created with an interview guide, a notes template, a set of unvalidated hypotheses, and a draft constraint list (FABRIC, SAFETY, TRIMS, CAPACITY, OVERTIME, APPROVAL) with draft default parameter values. The values are the ones proposed in the T2 assignment and match the constraint definitions in PLAN.md. No parameter or constraint differs from PLAN.md. The draft freeze date is 2026-10-27.
- PLAN.md section: "Constraints", "Policy document", "Decisions" #2 (reviewed, not edited).
- Affected tasks / tests: T2 (this deliverable). T8 and `decisions/test_constraints.py` will use this list. If the freeze happens without interviews, T8 starts from the drafted list.
- Decided by: not applicable. This is a record of document creation, not a decision on a value. The owner decides the freeze.

### 2026-10-21 Working-day calendar added to the CAPACITY parameters

- Date: 2026-10-21
- Source interview id: none. No interview has happened; this is an owner decision made while building T7. It is not presented as a practitioner finding. `docs/v2/discovery.md` section 5.2 already flagged that working days (Sundays, festivals) are used by CAPACITY but are not a policy parameter, and that a calendar would be a PLAN.md change to log.
- What changed: two parameters are added to `capacity` in the policy document. Before: `capacity{eligible_lines[], default_efficiency_pct, cut_to_ship_days, finishing_days, ot_cap_hours_per_line_day}` with no definition of a working day. After: `capacity{..., non_working_weekdays[], holidays[]}`. `non_working_weekdays` is a list of weekday codes (MON..SUN), default `["SUN"]`. `holidays` is a list of ISO dates, default `[]`. A working day for CAPACITY and for the gate's required `line_capacity` facts is a date that is neither a non-working weekday nor a holiday. Also recorded: the demo policy uses `eligible_lines = ["L1","L2","L3","L4"]` (discovery 5.2 listed no default).
- PLAN.md section: "Policy document" (the shape line) and "Constraints" CAPACITY and "Required facts" (working day). PLAN.md has not been edited yet; this entry is the pending change until the week-1 freeze (2026-10-27).
- Affected tasks / tests: T7 (`decisions/policy.py`, `decisions/gate.py`, `tests/decisions/test_policy.py`, `test_gate.py`), T8 (CAPACITY and OVERTIME working-day count), T9 and the demo cases (policy digests include the new fields).
- Decided by: owner

### 2026-10-21 CAPACITY efficiency rule made precise (T8)

- Date: 2026-10-21
- Source interview id: none. No interview has happened; this is a T8 implementation decision that makes an ambiguous PLAN.md sentence exact. It is not a practitioner finding and the owner has not yet reviewed it.
- What changed: before, PLAN.md said "efficiency is taken from the line fact or falls back to `default_efficiency_pct`", which does not say what to do when only some line-day facts carry `efficiency_pct`, or how several are combined. After: if EVERY eligible line-day fact in the sewing window gives `efficiency_pct`, efficiency is the weighted average `Σ(free × eff) / Σ free`, where `free = max(0, available_minutes − committed_minutes of other orders)` for that line-day, and `required = total_sam × Σ free / Σ(free × eff)`. If any line-day fact lacks `efficiency_pct` (or the free minutes are all zero) the single `default_efficiency_pct` is used for the whole order. A fact efficiency outside (0, 1] makes CAPACITY NOT_EVALUATED. The weights are free minutes, not raw available minutes, so that PASS holds exactly when `Σ(free × eff) >= total_sam`; that is monotone in every line's minutes, which the plan's monotonicity property needs.
- PLAN.md section: "Constraints", CAPACITY (not edited; this entry is the pending change until the week-1 freeze).
- Affected tasks / tests: T8 (`decisions/constraints.py`, `tests/decisions/test_constraints.py`: `test_efficiency_is_the_free_minute_weighted_average_when_every_line_day_gives_it`, `test_efficiency_weights_are_free_minutes_after_commitments`, the CAPACITY monotonicity property); T9 and the demo cases if a case supplies `efficiency_pct`.
- Decided by: owner to confirm (implemented provisionally in T8).
