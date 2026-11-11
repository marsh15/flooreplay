# Product

FloorReplay answers one question for a knit-garment exporter in Tiruppur or Coimbatore: **should we accept this urgent order?**

A merchandiser gets an order request with a short ship date. Before saying yes they check fabric stock, trims, sewing capacity and whether the order is large enough to need a director's sign-off. The answers sit in an ERP export, a trims sheet, a shift sheet, supplier updates and messages from the dyeing house and the fabric store. They disagree, they are out of date, and some are in Tamil.

FloorReplay brings those sources together, says whether the evidence can be trusted, does the arithmetic in the open, and recommends accept, accept with conditions, decline or needs review. The merchandiser always records the final decision and a reason.

## What it does

1. **Keeps every piece of evidence as an immutable fact with two clocks.** `valid_from` is when it was true (the export's as-of time). `known_at` is when the system learned it. A correction is a new fact that supersedes the old one; nothing is overwritten.
2. **Replays any decision as it was known at a chosen time.** The same facts, policy and engine version always give the same decision digest. Scrubbing the knowledge-time slider shows exactly what changed when the dyeing note arrived and when QA resolved it.
3. **Checks the evidence before the numbers.** The gate returns READY, STALE, INCOMPLETE or CONFLICTING (in that order of severity, worst first) and lists every finding with its rule and fact ids. A stock figure the ERP shows against a quality failure reported by the dyeing house is a conflict, not a guess.
4. **Shows six constraints with their arithmetic.** Fabric per colour, safety stock, trims per item, sewing capacity, capped overtime and the approval threshold each return PASS, FAIL or NOT_EVALUATED with the ordered steps that produced the answer.
5. **Recommends, never decides.** Auto-accept needs a READY gate, every constraint passing and an order under the approval threshold. Anything uncertain becomes NEEDS_REVIEW. A language model, when used, only extracts structured signals from notes, and deterministic checks then verify each one.
6. **Tests policy changes before they are adopted.** The replay lab runs a candidate policy over a frozen set of past order cases and classifies each as fixed, regressed, unchanged or not comparable. Adopting a policy needs a complete stored run and a written acknowledgement for every regression, and only a workspace owner can do it.

## Who it is for

The primary user is a merchandiser or order planner who has to answer a buyer within hours. Fabric-store, QC and planning staff supply evidence. Engineers and hiring reviewers read the replay, the arithmetic and the tests as evidence of how the system is built.

## Scope and honesty

- **All data is synthetic.** The public demo is a fictional factory, "Tiruppur Knits (synthetic)". There has been no factory pilot and no practitioner interview, so the constraint list and default parameters are drafts from [the discovery notes](docs/v2/discovery.md), not validated values. No operational benefit is claimed.
- **Evidence arrives as file imports only:** CSV exports, a trims sheet saved as CSV, shift capacity, supplier updates, orders with bills of materials, and notes. There are no live ERP connectors and no spreadsheet (XLSX) import.
- **Split shipments are not proposed.** When fabric or trims fall short the engine says NEEDS_REVIEW instead of inventing a partial delivery. The shortfall arithmetic is shown.
- **Note extraction is built and tested but not offered in the web app.** The extraction pipeline, its deterministic checks and a 100-note English, Tamil and Tanglish draft corpus exist in the repository. The corpus labels are drafts that a Tamil speaker has not reviewed, and no model accuracy is claimed.
- **Orders are modelled by style and colour.** Sizes are ignored. Consumption is bill-of-materials metres per piece times quantity times one plus wastage.

## Design requirements

1. Show the decision and its evidence together; every figure leads to its facts.
2. Keep evidence quality, constraint arithmetic and the recommendation distinct.
3. Say when each fact entered the system and why the cutoff matters.
4. Use written status labels and visible focus. Colour never carries meaning alone. Never show a confidence percentage.
5. Preserve the earlier decision when new evidence arrives.
6. Work on a narrow screen and by keyboard.
7. Provide loading, empty, interrupted, unavailable and error states.

The earlier product, shortfall investigations on a sewing line, remains available under "Earlier versions" in the navigation and is described in [docs/v1/PRODUCT.md](docs/v1/PRODUCT.md). It receives no new features.
