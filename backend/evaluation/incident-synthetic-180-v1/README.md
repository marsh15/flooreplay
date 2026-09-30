# Synthetic incident release v1

This release contains 180 generated synthetic episodes: 120 historical, 30 development, and 30 locked investigations. The 24 authored category/structure templates cover material, machine, staffing, quality, changeover, and planning/reporting evidence. Development assertions and locked contradictory observations use separate template identities. Healthy cases, missing counts, mid-window cutoffs, late notes, valid corrections, and competing corrections change the observable evidence structures.

`observations.json` is the runtime corpus. `labels.json` contains frozen investigation expectations and category-level historical relevance labels. `hidden-world-state.json` contains synthetic world state and later-resolution placeholders. Neither labels nor world state is seeded into operational incident payloads. `manifest.json` pins record, label, template, lineage, and split identities.

`validation.json` records offline accounting and structure checks for all 60 investigation cases and checks template/lineage separation, source cutoff eligibility, and absence of hidden fields in runtime observations. These checks do not measure OpenAI quality or establish that historical actions can transfer to another incident.

The scenarios received generator-author arithmetic and structure review. They are not manufacturing-expert annotations. Independent semantic support review and semantic paraphrase leakage review remain pending. The frozen labels exist before current-provider evaluation; no OpenAI calls were used to generate or grade this release.
