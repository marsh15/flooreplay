# Note benchmark v1 — synthetic, unfrozen draft

All 100 messages are synthetic Codex drafts, written as short store, dyeing-house and QC updates for the fictional **Tiruppur Knits (synthetic)**. No message is a real worker's statement or a claim about a real company. These examples have not been validated by garment practitioners or a Tamil speaker.

- `notes.jsonl`: 40 English, 30 Tamil-script and 30 Tanglish notes. Every row declares `synthetic: true` and `drafted_by: "codex"`.
- `gold.jsonl`: proposed `note-signal-v2` fields, plus `note_id`, language, source text and `gold_status: "draft_unreviewed"`. Text is duplicated so the pure scorer can validate evidence without a filesystem lookup. Every evidence string is copied exactly from the NFC source.
- `pilot.jsonl`: IDs only, stratified 12 English / 9 Tamil / 9 Tanglish. Cases are spread through each language block to include ordinary, negated, ambiguous and multiplier examples.
- `manifest.json`: SHA-256 over the exact bytes of the three JSONL files, record/language counts, and `frozen: false`. The manifest does not hash itself.
- `verify.py`: local byte/structure/provenance verifier; it never edits data, marks labels reviewed, calls a provider or freezes the corpus.

Run from `backend/`:

```sh
uv run --python 3.12 python evaluation/note-benchmark-v1/verify.py
uv run --python 3.12 pytest tests/decisions/test_note_corpus.py tests/decisions/test_benchmark.py
```

The **owner must review all gold fields and Tamil/Tanglish phrasing before evaluation or freezing**. Model quality has not been measured. Scoring tests use `MockProvider` only; there are no provider credentials, paid calls, or stored real-model predictions in this corpus.

Proposed annotation conventions, all awaiting owner review:

1. These are QC signals. A routine arrival, question, negated-only issue or explicit release has all six fields null; routine stock quantities must not become defective quantities.
2. For a positive issue, use `shade_fail`, `gsm_fail`, or `defect`. Lot, affected quantity, unit, colour and quality are present only where the note supports them. Missing units remain null.
3. Mixed negation/positive notes label the live positive issue. When one of two lots is explicitly affected, label that lot; when attribution is uncertain, leave the lot null. More than one lot or quantity can still force deterministic checks to review the prediction.
4. Quantity values use plain decimal text, while evidence retains commas, `k`, `lakh`, or `லட்சம்`. Multipliers are deliberately included even where the present checks reject them: do not loosen the checks to make this draft benchmark score better.
5. Units are canonical `kg` or `m`; evidence may include the full quantity-and-unit phrase. Case is retained in other values, and all text is NFC.

`score_benchmark` is the offline scorer in `src/flooreplay/decisions/extraction/benchmark.py`. It reports numerator, denominator and a fixed-context Decimal ratio for each metric, overall, by field and by language. Missing predictions are errors rather than successful null predictions. An empty denominator yields no ratio. Gold review and a frozen manifest, actual provider runs, model comparisons and integration into the release CLI belong to the lead's later T34 work.
