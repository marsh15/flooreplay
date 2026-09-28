# The FloorReplay demonstration script

A narrated walkthrough for presenting FloorReplay live. Everything runs on
synthetic data with no API key. The full version takes ~15 minutes; a 5-minute
version is marked at the end. Every step names the principle it demonstrates —
that is the product being demonstrated.

Setup: `make backend-dev`, `make frontend-dev`, open http://localhost:5173.

---

## Act 1 — A recommendation you can't trust yet (Workbench)

**SCEN-HERO@1, Improved policy → Run replay.**

> "7:58 AM in a sewing unit. Operator O117 can't run sleeve attach today. The
> system is asked: can someone qualified cover that slot on that machine?
> Before answering, it checks whether the *evidence itself* is good enough to
> act on. Here the skill snapshot was assessed 45 days ago — outside the
> freshness budget. So the answer is **Needs context**, and no policy ever
> runs. The system would rather refuse than guess."

**Point at:** the outcome badge, the issue list, and that no proposal appears.

**Principle: missing evidence is never read as absence, and stale evidence
never quietly becomes truth.**

## Act 2 — Correction, not rewriting (Library + Workbench)

Select **SCEN-HERO@2** (the corrected revision) → **Run replay** (Improved).

> "The skills were re-assessed four days before the decision. The correction
> is pinned as a *new revision* — revision 1 is still exactly what it was,
> and replaying it still gives the historical result. With fresh evidence the
> gate opens: **Ready for review**, proposing **O219** — idle, skilled to the
> required level, on the same line. Every one of the twelve independent
> checks passes, each linked to the row of evidence that proves it."

**Point at:** the C01–C12 table; click one evidence chip to open the drawer
with the highlighted source row.

**Principle: corrections create history; the validator never trusts the
policy — it re-derives everything from pinned evidence.**

## Act 3 — The documented blind spot (Workbench)

**SCEN-HERO@2, Baseline policy → Run replay.**

> "This is the *baseline* policy: it ranks qualified candidates but
> deliberately does not check who is already busy. It proposes O204 — who is
> occupied on Line 3 — and independent validation rejects it with **C07**,
> showing the overlapping assignment row. The baseline's limitation is
> printed on its label everywhere it appears."

**Principle: systems ship with known limitations; honesty means carrying the
limitation on the artifact itself, not in a README nobody reads.**

## Act 4 — The regression the suite catches (Comparison)

Open **Comparison** → Baseline vs Improved → **Run comparison**.

> "32 named cases pin exactly how this system should behave, each with the
> defect it would catch. Under baseline vs improved: 32 unchanged pass — the
> baseline meets its own documented demands. Now watch a real regression:"

Re-run with **candidate = the demonstration defect** (CFG-DEFECT-SKILLFRESH,
a deliberately wrong 400-day freshness budget).

> "Three cases flip to REGRESSION — exactly the three stale-evidence cases.
> Note the defect configuration still *runs* and produces outcomes; what
> fails is its **expectation**. Actual results are never relabeled to hide a
> surprise."

**Principle: expectations are demands, not observations — an interrupted or
surprising run keeps its actual outcome and fails the demand visibly.**

## Act 5 — The model drafts, a human confirms (Floor notes)

Open **Floor notes** → paste:

> "O117 called in sick at 07:52, he cannot run sleeve attach today."

→ **Extract draft.**

> "The parser produced a *draft* — category, subject, uncertainty. It
> resolved the mention to O117 by exact id. If the note had said just
> 'Balamurugan', resolution would refuse to guess. And with no API key
> configured, the UI says so — the offline rule baseline ran, and the UI
> won't pretend otherwise. Nothing is stored until I confirm — and
> confirming forks a new revision. The parser never writes history; a human
> does."

**Point at:** the parser-kind label, the resolution chip, then **Confirm
event and fork revision** → the new SCEN-HERO@NN.

**Principle: AI output is a draft with an audit trail; ambiguity stays
ambiguous; the human is the authority.**

## Act 6 — The money moment: does yesterday's answer still hold? (Workbench)

**SCEN-REVIEW-LATER@1** → **Run replay** (Improved) → in *Later-context
review* choose **SCEN-REVIEW-LATER@2** → **Run review check**.

> "8:10 AM. The recommendation from 7:58 is already executed on paper. New
> exports arrived. Does the recommendation still hold? **Stale
> recommendation** — the decision time changed, the event changed, the
> evidence changed — here are the 51 exact paths that differ. The original
> replay was never touched."

Also show **SCEN-REVIEW-LATER@3** (blocked context: every snapshot stale) and
**SCEN-HERO@2** (identical digest → *still supported*).

**Principle: review is explicit, evidence-based, and never rewrites the
past — exactly what a recommendation system owes the people who act on it.**

## Act 7 — Prove it to yourself

- Every replay has a **portable JSON report** (export link) with both
  digests.
- `uv run python -m flooreplay.eval_notes` scores the parser on held-out
  notes; the offline baseline honestly scores ~50% — which is why the note
  workflow never trusts it without confirmation.
- All 100+ unit tests, the 32-case suite, and 10 end-to-end browser tests
  are in the repo (`make verify`, `make e2e`).

**Closing line:**

> "FloorReplay doesn't promise better recommendations. It promises that when
> a recommendation is shown, you can see exactly which evidence, which
> rules, and which software produced it — and whether it still holds when
> any of those change."

---

## The 5-minute version

Act 1 (stale blocks) → Act 2 (correction replays ready) → Act 6 (review:
stale / still supported) → closing line. If there is time for one more:
Act 4 (the caught regression).
