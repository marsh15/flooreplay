# Product

## Register

product

## Users

Applied AI engineers and forward-deployed engineers investigating whether an operational recommendation stays trustworthy when source data, decision rules, or software versions change. Secondary audience: the hiring team evaluating the build. They open the workbench mid-investigation: they want to trace why a policy proposed (or refused) a coverage action, down to the exact source row, and compare two configurations across a pinned suite. They are expert readers who distrust unexplained numbers.

## Product Purpose

FloorReplay reconstructs a bounded manufacturing situation from immutable evidence, decides whether the evidence supports a decision, runs a recommendation policy, validates its proposal, and compares the result against explicit expectations. One narrow workflow: an operator cannot cover a planned sewing operation; can an available, qualified operator cover that vacant slot on its designated machine? Success = a reviewer can follow the hero episode end to end (stale evidence gate, corrected revision, baseline rejection, improved proposal, regression catch) and trust every link.

## Brand Personality

Precise, restrained, honest. An engineering instrument, not a dashboard product. Three words: exact, quiet, inspectable.

## Anti-references

- Artificial confidence percentages or single "accuracy" scores
- Decorative charts, gauges, score dials
- Animation that delays inspection; orchestrated page-load sequences
- Marketing voice ("seamless", "AI-powered", "next-gen")
- Dark cockpit dashboards with neon accents; the plan calls for light neutral surfaces
- A red badge with no explanation; color must never be the only signal

## Design Principles

1. Evidence before conclusion. Every issue and failed constraint links to the source row or canonical fact that caused it.
2. Result first, then the chain. Main outcome at top; event, issues, proposal, constraints, manifest in reading order.
3. Distinguish live execution, previously computed result, and saved release report. A saved report must never look freshly executed.
4. Color supplements labels and icons; never replaces them.
5. Monospaced identifiers, compact tables, strong typographic hierarchy. Density is a feature; decoration is a defect.
6. Immutability is visible. Historical results never change; corrections create new revisions.

## Accessibility & Inclusion

- Full keyboard navigation, visible focus
- Accessible table headings and screen-reader labels for statuses
- Readable narrow-screen layouts (tables collapse gracefully)
- Loading, empty, interrupted, unavailable, and error states for every data surface
- WCAG AA contrast on light neutral surfaces
