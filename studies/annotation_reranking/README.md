# Annotation-Reranking Study

## Purpose

This study evaluates whether LLM rerankers (Anthropic, OpenAI, OpenRouter) improve
ChEBI candidate selection over deterministic baselines on the 172-case ChEBI
disagreement dataset.  The primary question is whether a prompted LLM — given
Kestrel hybrid-search results plus candidate metadata — can outperform the
`source_weight_guard` rule, which selects the RefMet-anchor candidate unless
InChIKey connectivity says it is the same molecule as the resolver's top hit.

Results are written by default to a timestamped `runs/<UTC-timestamp>/` directory
so that every run is self-contained and reproducible without overwriting prior runs.

---

## Run Phase 0 Gate FIRST

Before spending any LLM budget, run the Phase 0 regime measurement to understand
the retrieval ceiling and the independent label partition:

```bash
uv run python -m studies.annotation_reranking.phase0
```

Phase 0 reports:

- How many of the 172 cases have a correct answer present in the top-N candidates
  (retrieval ceiling — reranking cannot fix un-retrieved answers).
- The independent vs. refmet_agreement label split (the LLM can only be fairly
  evaluated on the independent partition).

**Stop and review Phase 0 numbers before proceeding.**  If the independent
partition is too small to detect a meaningful signal (< 50 cases), collecting
more curated labels is a prerequisite, not a post-hoc note.

---

## Run Commands

### Deterministic only (no API calls, no model spend)

```bash
uv run python -m studies.annotation_reranking.run \
    --csv "/path/to/chebi_disagreements_cat.csv" \
    --top-n 20 \
    --seeds 0,1,2
```

Omit `--models` (or leave it empty) to run only the three deterministic rerankers:
`top1`, `rm_anchor`, and `source_weight_guard`.  This is the default.

The default `--csv` path points to the Global-Constraints vault CSV on the local
machine.  Pass an explicit path when running on a different host.

### Full matrix (deterministic + LLM rerankers)

```bash
# Prerequisite: pin the gpt-5.5 model_id in model_call.py (replace PIN_AT_RUNTIME)
# Prerequisite: add openai and anthropic to project dependencies

uv run python -m studies.annotation_reranking.run \
    --csv "/path/to/chebi_disagreements_cat.csv" \
    --top-n 20 \
    --seeds 0,1,2 \
    --models sonnet,qwen3-8b \
    --hardware "A100-40G" \
    --out runs/2026-07-08-full
```

`--models` is a comma-separated list of labels from the ROSTER defined in
`model_call.py` (e.g. `opus`, `sonnet`, `gpt-5.5`, `qwen3-4b`, `qwen3-8b`).
Each label registers both a blind reranker (`llm:<label>/blind`, RM: ids stripped)
and a non-blind reranker (`llm:<label>`).

### Output location

Results land in `studies/annotation_reranking/runs/<UTC-timestamp>/` by default.
The printed path on stdout is the directory that was written.

---

## What `manifest.json` Pins

Every run writes `manifest.json` before `results.jsonl`.  It records:

| Field | Description |
|---|---|
| `dataset_sha256` | SHA-256 of the input CSV for bit-exact dataset identification |
| `top_n` | Candidate window size passed to Kestrel |
| `seeds` | RNG seeds used for candidate position shuffles |
| `temperature` | Always 0 (deterministic LLM calls) |
| `models` | Model IDs for all LLM rerankers in the run |
| `quant_notes` | Per-model quantization notes (e.g. fp8 vs. Q4) |
| `hardware` | Free-form hardware descriptor for the run host |

A partial run (interrupted mid-results) is still inspectable because the manifest
is written first.

---

## Mandatory Caveats (Must Appear in Any Writeup)

1. **Baseline is `source_weight_guard`, not `rm_anchor`.**
   `rm_anchor` is kept in the registry to demonstrate circularity: it is
   right-by-construction on the 11 BioMapper-error cases because it picks the
   RefMet anchor, which is the ground-truth label for those cases.  It is
   retired as a performance baseline.  `source_weight_guard` is the correct
   reference point.

2. **Independent labels — current reality vs. planned scope.**
   Currently `dataset.py` derives independent labels from the ~13 hand-triaged
   cases only (`TRUE_BIOMAPPER_ERRORS` / `REFMET_ERRORS`).  All other 159 cases
   receive `label_source="refmet_agreement"` and are **unscored** (`is_correct=None`).
   InChIKey first-block connectivity (KG → MW → PubChem) is the *intended*
   non-circular label source that would scale past the 13, but the label-derivation
   pass is **NOT YET IMPLEMENTED** — it is a planned follow-up.
   `EvalCase.inchikey_block_correct` and `EvalCase.retrievable` are reserved fields
   for that future pass; they are never populated by the current code.
   Once that pass lands, stereo/protonation cases (same connectivity, different
   structure) would be assigned `expert_needed` and excluded from the scoreable
   subset.  Until then, accuracy figures cover only the 13 hand-triaged cases.

3. **`majority = top-score` proxy.**  This study has no multi-annotator vote
   as in production's resolver.  `source_weight_guard` uses the highest-scoring
   Kestrel candidate as a proxy for the majority vote.  Results may not
   generalise to the full resolver ensemble.

4. **Retrieval ceiling: ~45 / 172 correct nodes absent at top-N ≥ 200.**
   Accuracy is reported conditioned on retrievability.  Reranking cannot reach
   answers that are not in the candidate set.

5. **RM-blinding strips only the `RM:` ids from `equivalent_ids`.**
   Candidate names are retained (legitimate signal from the KG node, not a
   RefMet-specific field).  Residual name-similarity between a candidate name
   and the query is an inherent, un-blindable limitation of any name-based
   reranker.  This is documented here, not stripped.

6. **OpenRouter serves open models at fp8, NOT local Q4.**
   The `qwen3-4b` and `qwen3-8b` numbers collected via OpenRouter reflect
   cloud fp8 inference.  Any hardware-cost claim comparing "small local model
   vs. large cloud model" requires a true-Q4 run on the target box.  The
   `quant_notes` field in `manifest.json` carries this caveat per model.

7. **RUN prerequisites.**
   Before any billed run: (a) pin the exact GPT-5.5-class `model_id` in
   `model_call.py` (replace `PIN_AT_RUNTIME`); (b) add `openai` and `anthropic`
   to project dependencies (`uv add openai anthropic`).

---

## Directory Layout

```
studies/annotation_reranking/
├── README.md          ← this file
├── dataset.py         ← load_eval_cases, dataset_sha256
├── inchikey_resolver.py  ← connectivity_match (InChIKey first-block)
├── model_call.py      ← ROSTER, call_model (lazy API dispatch)
├── models_data.py     ← Candidate, EvalCase, RerankResult dataclasses
├── phase0.py          ← Phase 0 regime measurement (run first)
├── regimes.py         ← classify_regime
├── retrieval.py       ← fetch_candidates (Kestrel hybrid search)
├── run.py             ← run_matrix, score_case, _register_llms, CLI
├── scoring.py         ← Wilson CI, McNemar, min_discordant_for_sig
└── rerankers/
    ├── base.py        ← Reranker protocol, REGISTRY, register
    ├── deterministic.py  ← Top1Reranker, RmAnchorReranker, SourceWeightGuardReranker
    └── llm.py         ← build_prompt, parse_selection, LlmReranker
```
