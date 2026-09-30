# FloorReplay incident walkthrough

Use the seeded local app at `http://localhost:5173`. The story is synthetic; every quantity comes from the shown records.

1. **Open the incident library.** Select “Delayed start on sewing line S4.” The library shows the latest revision and the observed shortfall. The evaluation lab is a separate engineering view.
2. **Set evidence revision 1.** Its 11:00 knowledge cutoff admits eight completed 15-minute buckets. The baseline totals 160 final good units, recorded output totals 87, and shortfall is 73. Expand the calculation inputs and inspect one plan bucket and its matching output record. Then open the material record and the supervisor's line-block assertion. The recorded 30-minute block is a union of explicit blocking intervals; the report does not claim it caused all 73 missing units.
3. **Inspect uncertainty.** The machine event and QC hold appear as recorded observations. Their line-wide impact is not established. The maintenance note is absent because it did not enter the source system until 11:20, despite describing an earlier occurrence.
4. **Open a precedent.** The live lexical search retrieves a prior late fabric transfer. Read the match and differences. Similar wording is a lead for investigation, not a causal finding.
5. **Switch to revision 2.** Its 11:30 cutoff includes the late maintenance note and a correction that supersedes the earlier machine record. The first report remains at its saved analysis URL. Attempting to review a proposal from revision 1 returns a stale-analysis conflict.
6. **Review a current proposal.** Submit a revision 2 proposal, then record a reviewer, rationale, and approval or rejection. This records human review against the pinned proposal digest. It does not execute work or release a held lot.
7. **Open Evaluation lab.** Read the actual numerator and denominator for deterministic arithmetic and lexical retrieval. Recorded OpenAI smoke and pilot checks measure structure. Independent claim support remains pending until reviewers assess the exact generated outputs.
8. **Optional OpenAI draft.** With a configured provider and an authenticated reviewer account, inspect the allowance before requesting a draft from the workbench. Inspect its packet-linked citations and limitations. A timeout or invalid draft leaves the deterministic report intact.

The older operator-coverage demonstration remains in [COVERAGE_ARCHIVE.md](COVERAGE_ARCHIVE.md) and the `coverage-v1` Git tag.
