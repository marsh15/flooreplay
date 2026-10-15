# FloorReplay design

FloorReplay is an evidence workbench for a production supervisor. Its visual identity is the hourly production board: the ruled output sheet and tally board a sewing line already reads. Ink-strong type, large tabular figures, hard horizontal rules, and one cobalt accent for interaction. Product truth, wording and behavior are defined in [PRODUCT.md](PRODUCT.md); this file records how they are drawn.

## Ground rules

- Light theme only. The supervisor works at a desk or tablet in daylight; there is no dark mode and no `.dark` token set.
- Desktop first. Tablet and phone get a real reading layout and 44px touch targets (`pointer: coarse`), not a scaled-down desktop.
- Every status is a written label. Color supplements text and never carries meaning alone.
- No decorative gauges, confidence percentages or ornamental charts. A chart is allowed only when it is drawn from the incident's own records and links to them.
- Wording is product copy, not decoration. Design changes alter presentation, not headings, labels, buttons or caveats.

## Color

Tokens live in `frontend/src/index.css` as OKLCH values. Neutrals are tinted toward the ink hue (255-262) so every grey belongs to the palette. The Tailwind `zinc` scale is re-mapped to the same neutrals, so legacy `zinc-*` classes render in palette.

| Role | Token | Use |
|---|---|---|
| Paper | `--background` `oklch(0.972 0.004 250)` | Page ground |
| Document | `--card` white | Panels, tables, forms |
| Ink | `--foreground` `oklch(0.2 0.02 262)` | Text and heavy rules |
| Board | `--board` `oklch(0.19 0.02 262)` | Top bar, active step |
| Accent | `--primary` `oklch(0.47 0.19 262)` (cobalt) | Primary actions, links, recorded output bars, focus ring |
| Limit | `--limit` / `-foreground` / `-border` (amber) | Evidence limits, next checks, observed shortfall |
| Danger | `--danger*` (red) | Errors, rejected, contradictions |
| Success | `--success*` (green) | Supported findings |
| Info | `--info*` (cobalt tint) | Neutral notices, abstain |

Each meaning color has a text-safe foreground (at least 4.5:1 on its own surface). Amber means an evidence limit and nothing else. Use the semantic classes (`bg-limit text-limit-foreground border-limit-border`), not palette classes.

## Typography

- **Archivo Variable** (self-hosted, `@fontsource-variable/archivo/wdth.css`) for the interface. Board figures and headings use the width axis (`font-stretch-semi-condensed`, bold); body text stays normal width.
- **JetBrains Mono** for source identifiers, formulas and structured records only.
- Scale: `text-xs` 13px for captions and secondary table columns, `text-sm` 15px for body in dense panels, `text-base` 16px for introductions. Nothing below 13px. Headings use `letter-spacing: -0.015em`.
- Numeric tables and figures use tabular numerals.

## Layout and shell

- One 72rem content column. Pages read in order: title, explanation, task controls, report content.
- The top bar is the board: ink background, logo, primary links (Incidents, Workspaces, Operations), then an **Engineering** group (Evaluation lab, Coverage archive) after a divider. All links stay visible inside one `nav[aria-label="Primary"]`; on phones the Engineering group takes its own row.
- Pages and sections open with a heavy ink rule (`PageHeader`: 2px under the title; `Section`: 2px above the heading). Panels are white documents with a 1px border and a small (about 4px) radius.
- The incident page has a sticky section rail (`SectionRail`) that highlights the section in view. It is horizontal and scrolls on narrow screens.
- `/coverage/*` shows an archive notice and otherwise inherits the same tokens. It is not redesigned.

## Components

Shared primitives are in `frontend/src/components/board.tsx` and `components/ui/`.

- `PageHeader`, `Section`: ruled headings with a short explanation.
- `BoardStat`: one cell of a ruled ledger row, with label, large figure and unit or status text. The shortfall cell uses the limit tone.
- `StatusTag`: bordered tag with text, tones `neutral | limit | danger | success | info`.
- `Limits`: inline callout for evidence limits and cautions. Caveats are always shown inline, never collapsed.
- `EvidenceLink` / `EvidenceList`: mono ID chips that open the source drawer (`.evidence-link`).
- `NativeSelect`, `FieldLabel`, shadcn `Input`, `Button` (variants include `board` for the dark bar), `Alert` (variants `limit`, `info`, `success`, `destructive`).
- `BucketStrip`: plan against recorded good output for each 15-minute interval. Bars are recorded output, a black line is the baseline plan, amber is the shortfall in the interval. Intervals the report did not count are dashed, labeled "Not counted" and explained in text; missing output is never drawn as zero, and records that arrived after the cutoff are not shown. Each column opens its source record.
- `ErrorBoundary`, `NotFoundPage`: error and 404 states.

## Interaction and states

- Visible 2px focus ring in cobalt, a skip link, and `aria-current` on navigation. Popovers dismiss with Escape and restore focus.
- Short feedback on controls; frequent inspection actions are immediate. No staged entrances. Reduced motion is honored globally.
- Tables scroll inside their container and are keyboard-scrollable. Incident library records have a narrow-screen card layout.
- Every data view has loading, empty, error and unavailable states with written explanations.
- Print: the supervisor report prints from `.supervisor-export` / `.supervisor-report`; the print stylesheet in `index.css` depends on those class names and on `.app-header`.

## Provenance

Saved deterministic bundles, live analyses, historical model outputs and unavailable capabilities keep explicit labels. Synthetic-data and archive notices stay visible. Design changes must preserve evidence provenance and the notices defined in PRODUCT.md.

## Checks

`pnpm visual` (in `frontend/`) renders every route at 1440 and 390 pixels against the saved demo data and writes screenshots plus an axe summary. Before and after captures from the redesign are in `docs/ui-baseline/`. The expected axe result is no violations.
