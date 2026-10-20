# FloorReplay 2.0 discovery pack

Status: draft prepared 2026-10-20. Nothing in this file has been validated with a practitioner.

This file is the T2 deliverable in `docs/v2/PLAN.md`. The plan is the contract. This file does not change it. Anything that differs from the plan after the interviews goes into `docs/v2/changelog.md`.

## Status

- Interviews not yet conducted.
- 0 of 2-3 practitioners reached as of 2026-10-20.
- The constraint list freezes on 2026-10-27 (end of week 1). The owner decides the freeze, not this document.
- If nobody is reached by the freeze date, this section will be updated to say so, the interview sections below stay as unanswered templates, and the defaults in `PLAN.md` stand. T8 then starts from the drafted constraint list and logs every later change in `changelog.md` (PLAN.md, "Shared rules for every task" and "Risks to watch").
- Until an interview is held and written up, every statement under "Current workflow and pain points" is a hypothesis, and every default value under "Draft constraint list" is a draft, unvalidated.

## 1. Purpose and who to talk to

### Purpose

FloorReplay 2.0 helps Tiruppur and Coimbatore knit garment exporters answer one question: should we accept this urgent order? The week-1 calls have three jobs:

1. Check that the decision, the facts it depends on, and the constraints in PLAN.md match how the work is actually done.
2. Find the parameter values (wastage, buffers, efficiency, thresholds, freshness) that real people use, or learn that they vary too much for one default.
3. Find out which data really exists, in what form, and in which language, so the import profiles (PLAN.md decision 8) and the extraction pilot (decision 3) fit reality.

The owner runs the calls. The owner is a Tamil speaker, so interviews can be held in Tamil, English or a mix. This pack only prepares material. It contains no interview results.

### Who to talk to

Target: 2-3 practitioners, ideally from different roles and different companies. One person per role is enough for a first pass. The roles below are listed in the order in which they touch an urgent order. The "why" is a reason to ask, not a finding.

| Role | Why talk to them |
|---|---|
| Merchandiser | Receives the buyer's request and gives the answer. Closest to the decision PLAN.md models. Knows what is checked before saying yes and what gets promised. |
| Production planner | Knows line loading, SAM, efficiency, overtime and the cut-to-ship timeline. Source for the CAPACITY and OVERTIME constraints. |
| Fabric store manager | Knows the real stock, lots, allocations, inbound fabric and QC holds. Source for FABRIC and SAFETY. Likely to see where ERP and reality disagree. |

Optional if time allows (not required): a trims or accessories store keeper (TRIMS), and a merchandising head or owner-director who approves large orders (APPROVAL).

### Ground rules for the calls

- Ask about the last real order, not about how things "should" work. Past events give better evidence than opinions.
- Do not show PLAN.md numbers first. Ask the open question, listen, then (if useful) probe with a number.
- Do not ask for confidential data. If an artefact is shared (a sheet, a screenshot, a voice note), ask permission first and anonymise it before it enters the repo.
- Never record company names, buyer names or person names in repo files. Use the anonymised id from the notes template.
- Quote someone only with consent recorded in the notes. Real notes are used only with permission and anonymised (PLAN.md decision 10).

## 2. Interview guide

Length: about 45 to 60 minutes. Not every question is needed in every call. Pick the groups that match the role and mark the rest "not asked". Each question has probes to use only if the person has not already covered them. Question ids (Q1 to Q30) are used in the notes template and in the parameter table.

### A. Warm-up

**Q1.** Describe your job in a normal week. Which decisions do you make, and which do you only pass on?
- Probes: Who do you report to? Who reports to you? Which of these decisions involve an order that arrives at short notice?

**Q2.** Think of the last order that arrived with a short deadline. What happened from the moment you heard about it to the moment an answer went back?
- Probes: What did you do first? Who did you speak to? What did you look up? What did you decide at the end, and when?

### B. Urgent-order intake

**Q3.** How does an urgent order reach you, and what information comes with it?
- Probes: In what form (call, email, WhatsApp, a sheet)? Which of style, colours, quantities, ship date, price and buyer are usually present? Which are usually missing?

**Q4.** What do you need to know before you can answer? What do you do when part of it is missing?
- Probes: Do you give a provisional answer? Do you wait? Whom do you ask? How long can the buyer wait for you?

**Q5.** What does "urgent" mean in your work? How much time do you usually have to answer, and how much time between confirmation and the ship date?
- Probes: Does it differ by buyer? By season? Who is waiting for your answer on the other side?

**Q6.** Beyond a plain yes or no, what other answers have you given to an urgent order?
- Probes: Partial shipment, a later date, overtime, a smaller quantity, a different fabric or colour? Who agreed to these? How often does each happen?

### C. Fabric stock and lots

**Q7.** How do you find out how much fabric is available for a given style and colour?
- Probes: Where do you look? Who do you ask? How long does it take? How do you handle several lots of the same quality and colour? Do you plan by style and colour, or does size matter?

**Q8.** How do you work out how much fabric an order needs? What allowance do you add for wastage, and where does that allowance come from?
- Probes: Per piece, per style, per buyer? Does it change with colour, knit structure or season? Is it written down?

**Q9.** Some stock may be promised to other orders. How is that tracked, and how do you find out what is truly free?
- Probes: Who can see the allocations? How often are they out of date? What happens when two orders want the same lot?

**Q10.** How much do you rely on fabric that is not yet in the store? How much earlier than the cutting date does it need to arrive?
- Probes: Where do the arrival dates come from (supplier, dyeing unit, a note)? How often do those dates slip? By how much?

**Q11.** Do you keep some stock untouched? If so, how much, and why?
- Probes: Per order, per quality, per season? Who decides? What was the last time the cushion was used?

**Q12.** How do you handle kilograms versus metres, and what do you need to convert between them?
- Probes: Do you know GSM and width for each lot? Where are they written? What happens when they are missing?

### D. Shade and GSM QC failures

**Q13.** Tell me about the last time a shade or GSM problem affected an order.
- Probes: What was found, when, and by whom? What did it change about the plan? What would have happened if it had been found a day later?

**Q14.** How do you hear that a lot has failed? How quickly does it reach the person who answers the buyer?
- Probes: Through the ERP, a person, a WhatsApp message, a voice note, a paper form? Who writes it down, and where? Is anything written down at all?

**Q15.** When a lot fails, how much of it do you treat as unusable?
- Probes: The whole lot, a part, a part after sorting? Who decides the usable quantity? How long does that take?

**Q16.** When two sources disagree (for example, the ERP shows stock but the dyeing or QC person says part of it failed), what happens?
- Probes: Whom do you trust? Who settles it? How is the settlement recorded? How long does it normally take?

### E. Trims

**Q17.** Which trims (buttons, labels, zips, thread, packing material and others) have caused trouble on an urgent order? How do you check them?
- Probes: Is there a list per style? Who keeps the status? Which trims take longest to get?

**Q18.** What allowance do you add on trim quantities, and does it vary by trim?
- Probes: Per trim type? Per buyer? Who sets it?

**Q19.** By when do trims need to be available, relative to cutting or the start of sewing?
- Probes: Does a trim that is on order but not received count as available? When does it become a problem?

### F. Line capacity, SAM, efficiency and overtime

**Q20.** How do you decide whether a line, or a set of lines, can take an extra order?
- Probes: Which numbers do you look at? Who owns them? Are some lines only able to do certain styles? How do you know what each line is already committed to?

**Q21.** Where does SAM (standard allowed minutes) for a style come from? How much do you trust it?
- Probes: Who sets it? When is it first available for a new style? How often is it wrong, and by how much?

**Q22.** What efficiency do you assume when you plan a line? Does it change?
- Probes: By line, style, buyer, season, or how long the line has run that style? Is the number you plan with different from what is achieved?

**Q23.** Walk me through the time between cutting and shipping for a typical order.
- Probes: How many days between cutting start and ship date? How many days are kept for finishing, packing, inspection and dispatch? Which days are working days (Sundays, festivals, power cuts)?

**Q24.** When and how is overtime used to recover capacity? What limits it?
- Probes: Hours per line per day? Per worker? Who approves? What does it cost, or what does it risk, besides money? Which lines can be used for which orders?

### G. Approvals and thresholds

**Q25.** Which orders need someone else's approval before you say yes? What triggers it?
- Probes: Order value, quantity, buyer, margin, delivery date, use of overtime, a split shipment? Who approves, and how fast? Has an approval ever been waived for urgency?

### H. Data sources actually used

**Q26.** For fabric stock, trims, line capacity, orders and supplier updates: where does each one actually live today, and who keeps it current?
- Probes: ERP export, Google Sheet, Excel, paper, WhatsApp? How often is it updated? What happens when two places disagree? Which fields are most often wrong or blank?

**Q27.** How old can each of these numbers be before you stop trusting it? Give examples from different sources.
- Probes: Stock count, trims status, shift capacity, supplier updates, notes, order requests. What is your own rule of thumb? What was the last time you used a stale number and what happened?

**Q28.** What information travels by WhatsApp, voice notes or phone calls rather than in a system? In which language?
- Probes: Tamil, English, Tanglish (Tamil written in English letters)? Can you describe, without sharing private details, how a shade problem or a delay is usually phrased? Are quantities and lot numbers included? Would you be willing to share anonymised examples?

### I. How decisions are recorded and reviewed

**Q29.** When you decide on an urgent order, what do you write down, where, and who can see it later?
- Probes: The decision, the reason, the numbers you used, the person who approved? Is it written before or after you tell the buyer? Is it ever written at all?

**Q30.** When an accepted order later goes wrong (or a declined one would have worked), what happens? How do you find out why?
- Probes: Is there a review? Who takes part? What would you want to be able to look back at? How much of the information at the time can you actually reconstruct?

## 3. Per-interview notes template

Copy this template into a new section, or a separate private file, for each interview. Use only the anonymised id. Do not put names, company names or buyer names in this repo.

```
### Interview P-<nn>

- Date (IST):
- Interviewer:
- Anonymised id: P-<nn>
- Role: merchandiser | production planner | fabric store manager | trims store | approver | other (state)
- Company size band (state only the band): <50 workers | 50-199 | 200-499 | 500-999 | 1000+
- Language(s) used in the call:
- Duration:
- Consent recorded for:
  - [ ] taking notes
  - [ ] quoting anonymised excerpts in repo docs
  - [ ] using shared artefacts (anonymised) as test or sample data
- Quotes allowed: yes | no | only with re-check

#### Answers mapped to the constraints
Use the person's own words where consent allows. Write "not asked" or "no answer" where that is true. Do not fill gaps with assumptions.

| Constraint | Question ids | What they said | Matches draft default? (yes / no / unclear) | Value they gave, with unit and how sure they were |
|---|---|---|---|---|
| FABRIC (wastage, inbound buffer) | Q7-Q10, Q12 | | | |
| SAFETY (safety floor) | Q11 | | | |
| TRIMS (wastage, buffer) | Q17-Q19 | | | |
| CAPACITY (efficiency, cut-to-ship, finishing, eligible lines) | Q20-Q23 | | | |
| OVERTIME (cap) | Q24 | | | |
| APPROVAL (value, quantity) | Q25 | | | |
| Freshness per source | Q26-Q27 | | | |
| Conflicts and QC failures | Q13-Q16 | | | |
| Intake and outcomes beyond yes/no | Q3-Q6 | | | |
| Recording and review | Q29-Q30 | | | |

#### Hypothesis check
For each hypothesis in section 4 raised in this call: H<n> confirmed | rejected | no evidence | refined (say how).

#### Surprises
Things said that were not in the guide or in PLAN.md.

#### Artefacts shared
List each item by type and anonymised description only (for example: "stock sheet export, 1 file, anonymised by the owner"). State whether it may be stored in the repo.

#### Follow-ups
Questions to ask again, people to ask next, things to check.

#### Proposed changes to the constraint list
List each as: parameter or section, current draft, proposed change, supporting interview id. The owner decides what goes to `changelog.md`.
```

## 4. Current workflow and pain points

**These are unvalidated assumptions. They are hypotheses to confirm or reject in the interviews. They are not findings, and nothing here has been checked with a practitioner.** They come from the shape of the PLAN.md domain and general knowledge of knit garment planning. Each one names the interview questions that would test it.

### Hypothesised workflow (unvalidated)

1. An urgent order arrives through a messaging app, a call or email, with style, colours, quantities and a ship date. (Test: Q3, Q5.)
2. The merchandiser checks fabric, trims and line capacity, usually by asking different people. (Test: Q2, Q4, Q7, Q17, Q20.)
3. The merchandiser answers the buyer with accept, decline or accept with conditions such as overtime or a split shipment. (Test: Q6.)
4. Larger orders need a senior approval. (Test: Q25.)
5. The reason for the decision is rarely written down in a form that can be replayed later. (Test: Q29, Q30.)

### Hypothesised pain points (unvalidated)

| Id | Hypothesis | Tested by | Result |
|---|---|---|---|
| H1 | Fabric stock in the ERP export is often out of date or disagrees with what the store manager knows. | Q7, Q9, Q26, Q27 | Not yet tested |
| H2 | Part of a lot can be unusable because of a shade or GSM problem, and the news reaches the merchandiser late or informally. | Q13, Q14, Q15 | Not yet tested |
| H3 | Two sources disagree (ERP stock against a dyeing or QC note), and there is no clear rule or record of who settles it. | Q16 | Not yet tested |
| H4 | Stock is already allocated to other orders, and the free quantity is hard to see. | Q9 | Not yet tested |
| H5 | Inbound fabric and trim arrival dates slip, and a buffer before cutting is used informally. | Q10, Q19 | Not yet tested |
| H6 | Trims status lives in a spreadsheet kept by hand, and gaps are found late. | Q17, Q19, Q26 | Not yet tested |
| H7 | Line capacity is judged from experience with a rough efficiency figure, not from a calculation using SAM. | Q20, Q21, Q22 | Not yet tested |
| H8 | Overtime is a common way to make an urgent order work, with limits that are informal. | Q24 | Not yet tested |
| H9 | Important information arrives as WhatsApp text or voice notes in Tamil, English or Tanglish, and is not recorded anywhere else. | Q14, Q28 | Not yet tested |
| H10 | The reasons behind accept/decline decisions are not stored in a way that allows a later review, so mistakes cannot be traced to the information available at the time. | Q29, Q30 | Not yet tested |
| H11 | Planning at style and colour level (ignoring sizes, PLAN.md decision 11) is close enough for an accept/decline answer. | Q7, Q8 | Not yet tested |

Update the "Result" column only from interview notes, and add the interview id. Do not change a hypothesis into a finding without at least one recorded interview supporting it. Do not present a single interview as a general fact.

## 5. Draft constraint list

Freeze date: **2026-10-27** (end of week 1). The owner decides the freeze. Until then, every value below is **draft, unvalidated**. The definitions of the constraints are copied from PLAN.md, "Constraints", and are the same ones T8 will implement.

### 5.1 Constraints

Each returns PASS, FAIL or NOT_EVALUATED, together with the fact ids used and the arithmetic as an ordered list of `{label, expression, value}` steps.

- **FABRIC** (per colour).
  - `req = qty × consumption × (1 + fabric.wastage_pct)`.
  - `usable_onhand = Σ lot.qty − Σ fabric_qc.qty` for QC facts with `review_state` in {checks_passed, confirmed}. A resolution's `usable_qty` replaces this for its lot.
  - `inbound = Σ fabric_inbound.qty` where `eta <= cut_date − inbound_buffer_days`.
  - `committed = Σ fabric_allocation.qty` for other orders.
  - `free = usable_onhand + inbound − committed`. PASS if `free >= req`.
- **SAFETY** (per colour). PASS if `free − req >= safety_floor_pct × (usable_onhand + inbound)`. A FAIL names the allocations that consumed the stock.
- **TRIMS** (per trim). `need = Σqty × qty_per_pc × (1 + trims.wastage_pct)`. PASS if `on_hand >= need`, or if `on_hand + inbound_qty (eta <= cut_date − trims.buffer_days) >= need`.
- **CAPACITY**. `required = Σ qty × sam / efficiency`, where efficiency comes from the line fact or falls back to `default_efficiency_pct`. `available = Σ over eligible lines × working days in [cut_date+1, ship_date − finishing_days] of (available_minutes − committed_minutes)`. PASS if `available >= required`. `cut_date = ship_date − cut_to_ship_days`.
- **OVERTIME**. Evaluated only when CAPACITY fails. `ot_available = lines × days × ot_cap_hours_per_line_day × 60`. PASS (the shortfall is curable) if `shortfall <= ot_available`. The condition is `ceil(shortfall / (lines × days × 60))` hours per line per day.
- **APPROVAL**. PASS if `order_value_inr <= max_value_inr` and `Σqty <= max_qty_pcs`.

Related rules in PLAN.md that the interviews could also touch: explicit units with kg to metres conversion only when GSM and width are known (decision 17); style by colour granularity, sizes ignored (decision 11); freshness is inclusive and measured against the decision cutoff (decision 18).

### 5.2 Policy parameters

All values are **draft, unvalidated**. They are the proposed defaults for the first policy document. The "Questions" column shows which interview questions could confirm or change each one. A value stays as drafted unless an interview, recorded in `changelog.md`, changes it.

| Parameter | Used by | Draft default (unvalidated) | Unit | Questions that would confirm or change it |
|---|---|---|---|---|
| `fabric.wastage_pct` | FABRIC | 0.05 | fraction of required quantity | Q8 |
| `fabric.inbound_buffer_days` | FABRIC | 2 | days before cut date | Q10 |
| `fabric.safety_floor_pct` | SAFETY | 0.05 | fraction of (usable on hand + inbound) | Q11 |
| `trims.wastage_pct` | TRIMS | 0.03 | fraction of required quantity | Q18 |
| `trims.buffer_days` | TRIMS | 2 | days before cut date | Q19, Q17 |
| `capacity.default_efficiency_pct` | CAPACITY | 0.55 | fraction, used when the line fact has none | Q22 |
| `capacity.cut_to_ship_days` | CAPACITY | 21 | days (`cut_date = ship_date − this`) | Q23, Q5 |
| `capacity.finishing_days` | CAPACITY | 4 | days before ship date | Q23 |
| `capacity.ot_cap_hours_per_line_day` | OVERTIME | 2 | hours per line per day | Q24 |
| `capacity.eligible_lines[]` | CAPACITY, OVERTIME | no default; set per factory | list of line ids | Q20, Q24 |
| `approval.max_value_inr` | APPROVAL | 5000000 | INR | Q25 |
| `approval.max_qty_pcs` | APPROVAL | 20000 | pieces | Q25 |
| `freshness_hours.erp_fabric_stock` | gate | 24 | hours | Q26, Q27 |
| `freshness_hours.sheet_trims_status` | gate | 48 | hours | Q26, Q27 |
| `freshness_hours.shift_capacity` | gate | 24 | hours | Q26, Q27 |
| `freshness_hours.supplier_updates` | gate | 72 | hours | Q26, Q27 |
| `freshness_hours.notes` | gate | 24 | hours | Q27, Q28 |
| `freshness_hours.order_requests` | gate | 168 | hours | Q27, Q3, Q5 |
| `conflict_rules[]` | gate | per PLAN.md examples (`qc_claims_against_lot`, `inbound_eta_disagrees`); full set not yet drafted | list | Q14, Q16, Q10 |
| `enabled_constraints[]` | engine | FABRIC, SAFETY, TRIMS, CAPACITY, OVERTIME, APPROVAL | list | Q1-Q25 (whether any constraint is missing or unnecessary) |

Notes:
- The defaults above are the starting values given for T2. This document has no evidence for them. They are not industry norms.
- `eligible_lines[]` has no default because it depends on the factory. The seeded synthetic data will need to define it.
- `conflict_rules[]` names only the two predicates mentioned in PLAN.md. Whether those are the right conflicts to model is an open question for Q16.
- Working days (Sundays, festivals) are used by CAPACITY but are not a policy parameter in PLAN.md. Q23 may show that a calendar is needed. That would be a change to PLAN.md and must be logged.

### 5.3 Freeze procedure

1. By 2026-10-27, the owner reviews the interview notes (if any) and decides which parameters and constraint definitions change.
2. Each accepted change is added to `docs/v2/changelog.md`, with the interview id, the PLAN.md section it affects, and the affected tasks and tests.
3. If PLAN.md needs editing, the owner edits it after the changelog entry exists.
4. If no interview happened, the owner may still freeze the draft list as is. The changelog entry then says that the list is unvalidated.
5. After the freeze, T8 builds on the frozen list. Later changes are logged the same way.
