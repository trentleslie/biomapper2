# Annotation-Reranking Ablation Harness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-contained harness that retrieves top-N metabolite candidate nodes from Kestrel, runs deterministic + LLM rerankers over them, and scores each reranker on independent-label and RM-uninformative subsets — producing the data that gates biomapper2 Phase 3 (LLM reranker tier) and feeds the BioMapper preprint.

**Architecture:** A new `studies/annotation_reranking/` package inside the biomapper2 repo (importable under the same uv venv). It reuses biomapper2's Kestrel client directly (`_kestrel_hybrid_search` + node enrichment), implements rerankers as small pure functions behind one `Reranker` protocol, calls models through one unified `call_model()` (OpenAI SDK → OpenRouter for open models; native Anthropic/OpenAI SDKs for frontier), and always saves full per-item results to a timestamped path. A mandatory **Phase 0** measures RM-uninformative regime sizes before any model spend.

**Tech Stack:** Python ≥3.10, uv, pandas, requests (via biomapper2's `kestrel_request`), pytest, `openai` SDK (for OpenRouter + GPT), `anthropic` SDK (Opus/Sonnet), `statsmodels` or hand-rolled exact stats (McNemar, Wilson CI).

## Global Constraints

- **Python ≥ 3.10** (biomapper2 `pyproject.toml`). Run everything via `uv run …` from the repo root.
- **Never mutate ground truth.** `chebi_disagreements_cat.csv` and `analyze.py` in the vault dir are read-only inputs. Copy/hash them; do not edit.
- **Kestrel access:** `KESTREL_API_KEY` (header `X-API-Key`) and `KESTREL_API_URL` (default `https://kestrel.nathanpricelab.com/api`) are read by `biomapper2.config`. `HYBRID_SEARCH_LIMIT = 20` is the default `top_n`.
- **Model keys:** `OPENROUTER_API_KEY` lives in `~/.config/model-ablation/env` (chmod 600; `source` it). Native Anthropic/OpenAI keys via their standard env vars. **Read keys inline; never echo or commit them.**
- **Reproducibility SOP (mandatory, not a flag):** every run saves full per-item results to `studies/annotation_reranking/runs/<UTC-stamp>/` **by default** and prints the path on completion. `--out` only *overrides* the path. Each run's `manifest.json` pins: CSV content hash (SHA-256 of the file bytes), exact model ids/versions, seeds, `top_n`, temperature, quantization note ("OpenRouter fp8, NOT local Q4" for open models), and hardware string.
- **Determinism:** `temperature=0` and a fixed seed for every model call. Counterbalance candidate ordering across seeds (position-bias control).
- **RM-anchor definition:** pick the candidate whose enriched `equivalent_ids` contains a RefMet id (prefix `RM:`); if none, fall back to top score; break ties deterministically (lowest CURIE string). This is the free baseline to beat.
- **Scope boundary:** this harness is a *study*. It deliberately calls `_kestrel_hybrid_search` directly rather than the production `get_annotations` path, so it does **not** depend on Phase 1 production wiring. Reranker functions live in the study package; migrating them to `src/biomapper2/core/rerankers/` is Phase 1/3 work, out of scope here.

---

## Revision 2026-07-08 — baseline swap, InChIKey labels, retrieval ceiling (AUTHORITATIVE)

The companion reranker design was revised 2026-07-08 (`docs/plans/2026-07-06-001-feat-topn-pluggable-reranker-design.md`, "Revision 2026-07-08"). Three changes flow into this plan. **This section is authoritative wherever it conflicts with the task text below.** The infra (retrieval, model-call, orchestrator, reproducibility) is unchanged.

**Change A — primary deterministic baseline is `source_weight_guard`, not `rm_anchor`.** `rm_anchor` is retired as the metabolite default (circular: `RM:` *is* RefMet). It stays in the matrix **only to demonstrate the circularity**. The rule to beat is guarded source-weighting with a layered InChIKey resolver.

**Change B — headline labels come from InChIKey first-block connectivity** (non-circular), not the ~13 hand-triaged cases (which become a cross-check). Stereo/protonation cases (same connectivity) are not InChIKey-adjudicable → excluded from the skill set as `expert_needed`.

**Change C — tag retrievability and report accuracy conditioned on it.** Measured ceiling: 45/172 correct nodes absent at `limit=200`. The LLM skill set = present-but-misranked + flagged-divergent cases only.

### New module: `studies/annotation_reranking/inchikey_resolver.py` (do before Task 4)

**Interfaces produced:**
- `inchikey_block(node_id: str, name: str) -> str | None` — layered, cached by `name`, each layer timeout-guarded and returning `None` on error (never raises): (1) KG `equivalent_ids` with `INCHIKEY` prefix; (2) Metabolomics Workbench `GET /rest/refmet/name/{name}/inchi_key`; (3) PubChem `GET /rest/pug/compound/name/{name}/property/InChIKey/JSON`. Returns the **first block** (substring before the first `-`).
- `connectivity_match(id_a, name_a, id_b, name_b) -> bool | None` — `True` if both blocks resolve and match, `False` if both resolve and differ, `None` if either is unresolvable.

Mirror the resolver spec's logic; a `# CONSOLIDATE: replace with core.resolver._connectivity_match once Phase 1b merges` comment marks the intended dedup. Tests mock all three network layers and assert the layer order (KG hit skips MW/PubChem; KG miss falls through to MW then PubChem; all-miss → `None`).

### Change to the `Reranker` protocol (Task 4) — carries case context + review flag

`select(candidates: list[Candidate], case: EvalCase | None = None) -> tuple[str | None, str | None]` → `(selected_id, review_flag)`. Deterministic `top1`/`rm_anchor` ignore `case` and return `flag=None`. `RerankResult` gains `review_flag: str | None`. `score_case` (Task 8) unpacks the tuple and stores the flag.

### New reranker: `SourceWeightGuardReranker` (primary baseline, in `deterministic.py`)

```python
class SourceWeightGuardReranker:
    name = "source_weight_guard"
    def __init__(self, connectivity_fn):        # inject connectivity_match for testability
        self._match = connectivity_fn
    def select(self, candidates, case=None):
        if not candidates:
            return None, "empty_candidates"
        majority = max(candidates, key=lambda c: c.score)          # study proxy for the vote
        if case is None or not case.refmet_id:
            return majority.id, None
        refmet_curie = f"CHEBI:{case.refmet_id}"
        refmet = next((c for c in candidates if c.id == refmet_curie), None)
        if refmet is None or refmet.id == majority.id:
            return majority.id, None
        same = self._match(refmet.id, refmet.name, majority.id, majority.name)
        if same is True:  return refmet.id, None                    # same molecule, silent
        if same is False: return refmet.id, "divergent_refmet"      # error-prone bucket → flag
        return majority.id, "conflict_no_structure"                 # unresolved → keep majority + flag
```
Tests (mock `connectivity_fn`): refmet-absent → majority/None; same-connectivity → refmet/None; different → refmet/`divergent_refmet`; unresolved → majority/`conflict_no_structure`. **Note the `majority = top-score` proxy** (the study has no multi-annotator vote); record this limitation in the README.

### Amendments to existing tasks

- **Task 1 (dataset):** add `inchikey_block_correct: str | None` and `retrievable: bool | None` fields to `EvalCase` (populated later, default `None`). Add `label_source` values `"inchikey_connectivity"` and `"expert_needed"`. Keep the n=2 `rm_anchor`-circularity test — it now documents *why* `rm_anchor` was demoted, not the headline path.
- **Task 3 (Phase 0):** replace RM-regime counting with **(i) retrievability** — is the correct node (InChIKey-labelled, or `refmet_id`) in the top-`top_n` window? Reproduce the 45/172-absent@200 finding; **(ii) divergence** — of retrievable cases, how many does `source_weight_guard` flag (`divergent_refmet` / `conflict_no_structure`). Report both. Gate unchanged: STOP and report before model spend.
- **Task 4:** implement `top1`, `rm_anchor` (reference), **and `source_weight_guard` (primary)** under the new tuple-returning protocol.
- **Task 5 (LLM) / Task 7 (scoring):** the LLM skill set is `retrievable AND (label_source=="inchikey_connectivity") AND source_weight_guard flagged-or-wrong`. Report accuracy **conditioned on retrievability**; same-connectivity cases are excluded (handled deterministically). RM-blinding is retained but secondary (baseline is no longer RM-based).
- **Task 6 / Task 8 / Task 9:** unchanged except `RerankResult.review_flag` threads through `results.jsonl`, and the README states Change A/B/C + the `majority=top-score` proxy + the InChIKey non-adjudicable (stereo/protonation) caveat.

---

## File Structure

```
studies/annotation_reranking/
  __init__.py
  models_data.py        # Candidate, EvalCase, RerankResult dataclasses (no I/O)
  dataset.py            # load CSV → EvalCase[]; derive independent labels; content hash
  retrieval.py          # top-N fetch via _kestrel_hybrid_search + equivalent_ids enrichment
  inchikey_resolver.py  # [Rev 2026-07-08] layered InChIKey block resolver (KG→MW→PubChem)
  regimes.py            # [Rev 2026-07-08] retrievability + source_weight_guard divergence tagging
  phase0.py             # measure + report regime sizes (the gate before model spend)
  rerankers/
    __init__.py
    base.py             # Reranker protocol + registry
    deterministic.py    # top1, rm_anchor
    llm.py              # prompt build (+ RM-blinding), response parse, LLM reranker
  model_call.py         # roster + unified call_model() → (text, cost_usd, latency_s)
  scoring.py            # per-regime accuracy, Wilson CI, McNemar exact, discordant counts
  run.py                # orchestrate full matrix; timestamped output by default; manifest
  README.md             # how to run + reproducibility SOP
  runs/                 # gitignored output (created at runtime)
tests/studies/annotation_reranking/
  test_dataset.py
  test_retrieval.py
  test_regimes.py
  test_deterministic.py
  test_llm.py
  test_model_call.py
  test_scoring.py
  test_run.py
```

**Task dependency order:** 1 → 2 → 3 (Phase 0 gate) → 4 → 5 → 6 → 7 → 8 → 9. Tasks 4–7 are independent of each other once 1–2 exist and may be built in any order; 8 depends on all.

---

### Task 1: Study package scaffold + data models + dataset loader

**Files:**
- Create: `studies/annotation_reranking/__init__.py`
- Create: `studies/annotation_reranking/models_data.py`
- Create: `studies/annotation_reranking/dataset.py`
- Create: `studies/__init__.py` (empty, makes `studies` importable)
- Test: `tests/studies/annotation_reranking/test_dataset.py`
- Reference (read-only input): `/home/trentleslie/Documents/Trent's Vault/Active 🎯/Work/Projects/biomapper2 - refmet ChEBI analysis/chebi_disagreements_cat.csv`

**Interfaces:**
- Produces:
  - `Candidate(id: str, score: float, name: str, synonyms: list[str], prefixes: list[str], equivalent_ids: list[str])` — a dataclass in `models_data.py`.
  - `EvalCase(name: str, level: str, refmet_id: str, refmet_name: str, biomapper_ids: list[str], biomapper_name: str, category: str, correct_id: str | None, label_source: str)` — `correct_id` is the CURIE (`CHEBI:<n>`) of the independently-adjudicated right answer, or `None` when only RefMet-agreement is available; `label_source ∈ {"independent_refmet_error", "independent_biomapper_error", "refmet_agreement"}`.
  - `load_eval_cases(csv_path: str) -> list[EvalCase]`
  - `independent_cases(cases: list[EvalCase]) -> list[EvalCase]` (those with `label_source` starting `"independent_"`)
  - `dataset_sha256(csv_path: str) -> str`
  - Module constants `TRUE_BIOMAPPER_ERRORS: set[str]` and `REFMET_ERRORS: set[str]` — the 11 + 2 case names copied verbatim from `analyze.py`.

**Key derivation rule (the n=2 insight, encode it explicitly):**
- CSV `refmet_id` / `biomapper_id` are bare ChEBI integers (biomapper_id may be pipe-delimited, e.g. `27596|50599`). Normalize to `CHEBI:<n>` CURIEs.
- For a name in `TRUE_BIOMAPPER_ERRORS`: BioMapper was wrong → `correct_id = CHEBI:<refmet_id>`, `label_source = "independent_biomapper_error"`.
- For a name in `REFMET_ERRORS`: RefMet was wrong → `correct_id = CHEBI:<first biomapper_id>`, `label_source = "independent_refmet_error"`.
- Otherwise: `correct_id = None`, `label_source = "refmet_agreement"` (RefMet's node; use only for agreement reporting, never as skill).

- [ ] **Step 1: Confirm the pinned error-case names in `analyze.py`**

Run: `grep -nA14 "TRUE_BIOMAPPER_ERRORS\|REFMET_ERRORS" "/home/trentleslie/Documents/Trent's Vault/Active 🎯/Work/Projects/biomapper2 - refmet ChEBI analysis/analyze.py"`
Expected: the two dicts. Copy the exact key strings (11 + 2) into `TRUE_BIOMAPPER_ERRORS` / `REFMET_ERRORS` in `dataset.py`. (These are the ground-truth case names — the plan depends on them matching the CSV `name` column exactly.)

- [ ] **Step 2: Write the failing test**

```python
# tests/studies/annotation_reranking/test_dataset.py
from studies.annotation_reranking.dataset import (
    load_eval_cases, independent_cases, dataset_sha256,
    TRUE_BIOMAPPER_ERRORS, REFMET_ERRORS,
)

CSV = "/home/trentleslie/Documents/Trent's Vault/Active 🎯/Work/Projects/biomapper2 - refmet ChEBI analysis/chebi_disagreements_cat.csv"

def test_loads_all_172_rows():
    cases = load_eval_cases(CSV)
    assert len(cases) == 172

def test_error_case_counts():
    assert len(TRUE_BIOMAPPER_ERRORS) == 11
    assert len(REFMET_ERRORS) == 2

def test_independent_label_partition():
    cases = load_eval_cases(CSV)
    indep = independent_cases(cases)
    # 11 biomapper-error + 2 refmet-error == 13 independently-labeled cases
    assert len(indep) == 13
    bm = [c for c in indep if c.label_source == "independent_biomapper_error"]
    rm = [c for c in indep if c.label_source == "independent_refmet_error"]
    assert len(bm) == 11 and len(rm) == 2
    # every independent case has a concrete correct CURIE
    assert all(c.correct_id and c.correct_id.startswith("CHEBI:") for c in indep)

def test_biomapper_error_correct_id_is_refmet_node():
    # the n=2 insight: on the 11 BM-errors, correct == RefMet's node,
    # so rm_anchor (picks RM-bearing == RefMet node) is right by construction.
    cases = {c.name: c for c in load_eval_cases(CSV)}
    for name in TRUE_BIOMAPPER_ERRORS:
        c = cases[name]
        assert c.correct_id == f"CHEBI:{c.refmet_id}"

def test_dataset_hash_is_stable_hex():
    h = dataset_sha256(CSV)
    assert len(h) == 64 and all(ch in "0123456789abcdef" for ch in h)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/studies/annotation_reranking/test_dataset.py -v`
Expected: FAIL with `ModuleNotFoundError: studies.annotation_reranking.dataset`

- [ ] **Step 4: Implement `models_data.py`**

```python
# studies/annotation_reranking/models_data.py
from dataclasses import dataclass, field

@dataclass
class Candidate:
    id: str                       # CURIE, e.g. "CHEBI:28683"
    score: float                  # Kestrel hybrid score (0–5)
    name: str
    synonyms: list[str] = field(default_factory=list)
    prefixes: list[str] = field(default_factory=list)
    equivalent_ids: list[str] = field(default_factory=list)  # enriched via get-nodes

    def has_refmet(self) -> bool:
        return any(e.startswith("RM:") for e in self.equivalent_ids)

@dataclass
class EvalCase:
    name: str
    level: str
    refmet_id: str
    refmet_name: str
    biomapper_ids: list[str]
    biomapper_name: str
    category: str
    correct_id: str | None
    label_source: str

@dataclass
class RerankResult:
    case_name: str
    reranker: str
    model: str | None
    selected_id: str | None
    correct_id: str | None
    label_source: str
    regime: str
    is_correct: bool | None       # None when label_source == "refmet_agreement"
    cost_usd: float
    latency_s: float
    error: str | None = None      # off-list / parse / api failure marker
```

- [ ] **Step 5: Implement `dataset.py`**

```python
# studies/annotation_reranking/dataset.py
import csv
import hashlib
from studies.annotation_reranking.models_data import EvalCase

# Copy the exact 11 + 2 names from analyze.py (Step 1). Placeholder names below
# MUST be replaced with the verified strings before this task is complete.
TRUE_BIOMAPPER_ERRORS: set[str] = {
    "(15:3)-anacardic acid", "2-hydroxypalmitate", "4-acetamidophenol",
    "4-hydroxyhippurate", "4-methylbenzenesulfonate", "9-hydroxystearate",
    "5_HpEPE__4_55", "2-Methylmaleate", "laurylcarnitine (C12)",
    "myristoylcarnitine (C14)", "glycerophosphoinositol*",
}
REFMET_ERRORS: set[str] = {
    "6-shogaol", "Diethyl 2-methyl-3-oxosuccinate",
}

def _curie(raw: str) -> str:
    raw = raw.strip()
    return raw if raw.startswith("CHEBI:") else f"CHEBI:{raw}"

def load_eval_cases(csv_path: str) -> list[EvalCase]:
    cases: list[EvalCase] = []
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            name = row["name"]
            bm_ids = [_curie(x) for x in row["biomapper_id"].split("|") if x.strip()]
            if name in TRUE_BIOMAPPER_ERRORS:
                correct, src = _curie(row["refmet_id"]), "independent_biomapper_error"
            elif name in REFMET_ERRORS:
                correct, src = (bm_ids[0] if bm_ids else None), "independent_refmet_error"
            else:
                correct, src = None, "refmet_agreement"
            cases.append(EvalCase(
                name=name, level=row["level"], refmet_id=row["refmet_id"],
                refmet_name=row["refmet_name"], biomapper_ids=bm_ids,
                biomapper_name=row["biomapper_name"], category=row["category"],
                correct_id=correct, label_source=src,
            ))
    return cases

def independent_cases(cases: list[EvalCase]) -> list[EvalCase]:
    return [c for c in cases if c.label_source.startswith("independent_")]

def dataset_sha256(csv_path: str) -> str:
    with open(csv_path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/studies/annotation_reranking/test_dataset.py -v`
Expected: PASS (5 tests). If `test_biomapper_error_correct_id_is_refmet_node` fails, a name in `TRUE_BIOMAPPER_ERRORS` doesn't match the CSV — fix the copied string, don't relax the test.

- [ ] **Step 7: Commit**

```bash
git add studies/ tests/studies/
git commit -m "feat(study): eval-case dataset loader + independent-label partition"
```

---

### Task 2: Top-N candidate retrieval + equivalent_ids enrichment

**Files:**
- Create: `studies/annotation_reranking/retrieval.py`
- Test: `tests/studies/annotation_reranking/test_retrieval.py`
- Reference: `src/biomapper2/core/annotators/kestrel_hybrid.py`, `src/biomapper2/core/linker.py`, `src/biomapper2/config.py`

**Interfaces:**
- Consumes: `Candidate` from Task 1.
- Produces: `fetch_candidates(name: str, category: str, top_n: int = 20) -> list[Candidate]` — returns up to `top_n` scored candidates, each enriched with `equivalent_ids`.

- [ ] **Step 1: Confirm the exact biomapper2 symbols**

Run: `grep -n "class \|def _kestrel_hybrid_search\|def get_equivalent" "src/biomapper2/core/annotators/kestrel_hybrid.py" "src/biomapper2/core/linker.py"`
Expected: the annotator class name (e.g. `KestrelHybridAnnotator`), the static `_kestrel_hybrid_search(search_text, category, prefixes, limit=10)`, and the equivalent-ids fetch in `linker.py`. Record the confirmed names; use them below in place of `<AnnotatorClass>` / `<get_equivalent_ids>`.

- [ ] **Step 2: Write the failing test (mock the network)**

```python
# tests/studies/annotation_reranking/test_retrieval.py
from unittest.mock import patch
from studies.annotation_reranking import retrieval
from studies.annotation_reranking.models_data import Candidate

FAKE_SEARCH = {"1-methylhistidine": [
    {"id": "CHEBI:70958", "score": 4.9, "name": "1-methylhistidine", "synonyms": []},
    {"id": "CHEBI:27596", "score": 4.1, "name": "N(pros)-methyl-L-histidine", "synonyms": []},
]}
FAKE_EQUIV = {"CHEBI:70958": ["RM:0001", "HMDB:0000001"], "CHEBI:27596": ["HMDB:0000479"]}

def test_fetch_returns_enriched_candidates():
    with patch.object(retrieval, "_raw_hybrid_search", return_value=FAKE_SEARCH), \
         patch.object(retrieval, "_fetch_equivalent_ids", return_value=FAKE_EQUIV):
        cands = retrieval.fetch_candidates("1-methylhistidine", "metabolite", top_n=20)
    assert [c.id for c in cands] == ["CHEBI:70958", "CHEBI:27596"]
    assert isinstance(cands[0], Candidate)
    assert cands[0].equivalent_ids == ["RM:0001", "HMDB:0000001"]
    assert cands[0].has_refmet() and not cands[1].has_refmet()

def test_top_n_is_passed_through():
    captured = {}
    def spy(text, category, prefixes, limit):
        captured["limit"] = limit
        return {text: []}
    with patch.object(retrieval, "_raw_hybrid_search", side_effect=spy), \
         patch.object(retrieval, "_fetch_equivalent_ids", return_value={}):
        retrieval.fetch_candidates("x", "metabolite", top_n=15)
    assert captured["limit"] == 15
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/studies/annotation_reranking/test_retrieval.py -v`
Expected: FAIL (`AttributeError`/`ModuleNotFoundError` on `retrieval`).

- [ ] **Step 4: Implement `retrieval.py`**

```python
# studies/annotation_reranking/retrieval.py
from biomapper2.core.annotators.kestrel_hybrid import <AnnotatorClass>  # from Step 1
from biomapper2.core.linker import <get_equivalent_ids>                 # from Step 1
from studies.annotation_reranking.models_data import Candidate

def _raw_hybrid_search(text: str, category: str, prefixes, limit: int) -> dict:
    # Bypasses production get_annotations (which hardcodes limit=1) on purpose.
    return <AnnotatorClass>._kestrel_hybrid_search(text, category, prefixes, limit=limit)

def _fetch_equivalent_ids(ids: list[str]) -> dict[str, list[str]]:
    # Wrap linker's get-nodes call; return {curie: [equivalent CURIEs]}.
    return <get_equivalent_ids>(ids)

def fetch_candidates(name: str, category: str, top_n: int = 20) -> list[Candidate]:
    raw = _raw_hybrid_search(name, category, None, limit=top_n).get(name, [])
    ids = [r["id"] for r in raw]
    equiv = _fetch_equivalent_ids(ids) if ids else {}
    return [
        Candidate(
            id=r["id"], score=float(r["score"]), name=r["name"],
            synonyms=r.get("synonyms", []), prefixes=r.get("prefixes", []),
            equivalent_ids=equiv.get(r["id"], []),
        )
        for r in raw
    ]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/studies/annotation_reranking/test_retrieval.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Add a live smoke check (marked external, skipped by default)**

```python
# append to test_retrieval.py
import os, pytest

@pytest.mark.external
@pytest.mark.skipif(not os.getenv("KESTREL_API_KEY"), reason="needs KESTREL_API_KEY")
def test_live_fetch_one_case():
    cands = retrieval.fetch_candidates("1-methylhistidine", "metabolite", top_n=20)
    assert 1 <= len(cands) <= 20
    assert all(c.id.startswith("CHEBI:") for c in cands)
```

Run: `uv run pytest tests/studies/annotation_reranking/test_retrieval.py -v -m external` (only when the API key + network are available). Expected: PASS or skip.

- [ ] **Step 7: Commit**

```bash
git add studies/annotation_reranking/retrieval.py tests/studies/annotation_reranking/test_retrieval.py
git commit -m "feat(study): top-N Kestrel retrieval with equivalent_ids enrichment"
```

---

### Task 3: Regime classification + Phase 0 gate

**Files:**
- Create: `studies/annotation_reranking/regimes.py`
- Create: `studies/annotation_reranking/phase0.py`
- Test: `tests/studies/annotation_reranking/test_regimes.py`

**Interfaces:**
- Consumes: `Candidate`, `EvalCase`, `fetch_candidates`.
- Produces:
  - `classify_regime(candidates: list[Candidate]) -> str` → `"a_no_rm"` (no RM-bearing candidate), `"b_multi_rm"` (≥2 RM-bearing candidates → tie/ambiguous), or `"informative"` (exactly one RM-bearing candidate).
  - `run_phase0(csv_path: str, top_n: int, out_dir: str) -> dict` → writes `phase0_regimes.json` and returns `{"a_no_rm": int, "b_multi_rm": int, "informative": int, "n_independent_rm_wrong": int, ...}`.

**Why this is a gate:** `run_phase0` counts how many of the 172 cases land in RM-uninformative regimes (a/b) — the only place beyond the 2 RefMet-error cases where an LLM can out-skill `rm_anchor`. It also reports `n_independent_rm_wrong` (cases where `rm_anchor`'s pick ≠ `correct_id`). If regimes a+b and `n_independent_rm_wrong` are both tiny, the headline needs the ≥100-pair curated set before models are worth running.

- [ ] **Step 1: Write the failing test**

```python
# tests/studies/annotation_reranking/test_regimes.py
from studies.annotation_reranking.regimes import classify_regime
from studies.annotation_reranking.models_data import Candidate

def _c(cid, rm): return Candidate(id=cid, score=1.0, name=cid, equivalent_ids=(["RM:1"] if rm else []))

def test_no_rm_candidate():
    assert classify_regime([_c("CHEBI:1", False), _c("CHEBI:2", False)]) == "a_no_rm"

def test_single_rm_candidate_is_informative():
    assert classify_regime([_c("CHEBI:1", True), _c("CHEBI:2", False)]) == "informative"

def test_multiple_rm_candidates():
    assert classify_regime([_c("CHEBI:1", True), _c("CHEBI:2", True)]) == "b_multi_rm"

def test_empty_list_is_no_rm():
    assert classify_regime([]) == "a_no_rm"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/studies/annotation_reranking/test_regimes.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `regimes.py`**

```python
# studies/annotation_reranking/regimes.py
from studies.annotation_reranking.models_data import Candidate

def classify_regime(candidates: list[Candidate]) -> str:
    rm = [c for c in candidates if c.has_refmet()]
    if len(rm) == 0:
        return "a_no_rm"
    if len(rm) >= 2:
        return "b_multi_rm"
    return "informative"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/studies/annotation_reranking/test_regimes.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Implement `phase0.py` (uses live retrieval; run manually)**

```python
# studies/annotation_reranking/phase0.py
import json, os
from collections import Counter
from studies.annotation_reranking.dataset import load_eval_cases, dataset_sha256
from studies.annotation_reranking.retrieval import fetch_candidates
from studies.annotation_reranking.regimes import classify_regime

def run_phase0(csv_path: str, top_n: int, out_dir: str) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    cases = load_eval_cases(csv_path)
    regime_counts, rm_wrong, per_case = Counter(), 0, []
    for c in cases:
        cands = fetch_candidates(c.name, "metabolite", top_n=top_n)
        regime = classify_regime(cands)
        regime_counts[regime] += 1
        rm_pick = next((x.id for x in cands if x.has_refmet()),
                       (max(cands, key=lambda x: x.score).id if cands else None))
        if c.correct_id and rm_pick != c.correct_id:
            rm_wrong += 1
        per_case.append({"name": c.name, "regime": regime, "rm_pick": rm_pick,
                         "correct_id": c.correct_id, "label_source": c.label_source})
    summary = {"top_n": top_n, "dataset_sha256": dataset_sha256(csv_path),
               "n_cases": len(cases), **regime_counts,
               "n_independent_rm_wrong": rm_wrong}
    with open(os.path.join(out_dir, "phase0_regimes.json"), "w") as fh:
        json.dump({"summary": summary, "per_case": per_case}, fh, indent=2)
    print(f"[phase0] {summary}")
    print(f"[phase0] wrote {out_dir}/phase0_regimes.json")
    return summary
```

- [ ] **Step 6: Commit**

```bash
git add studies/annotation_reranking/regimes.py studies/annotation_reranking/phase0.py tests/studies/annotation_reranking/test_regimes.py
git commit -m "feat(study): regime classifier + Phase 0 gate measurement"
```

- [ ] **Step 7: DECISION GATE — run Phase 0 and report before building models**

Run (needs `KESTREL_API_KEY`): `uv run python -c "from studies.annotation_reranking.phase0 import run_phase0; run_phase0('/home/trentleslie/Documents/Trent\\'s Vault/Active 🎯/Work/Projects/biomapper2 - refmet ChEBI analysis/chebi_disagreements_cat.csv', 20, 'studies/annotation_reranking/runs/phase0')"`
Expected: prints regime counts + `n_independent_rm_wrong`. **Stop and report these numbers to Trent.** If `a_no_rm + b_multi_rm + n_independent_rm_wrong` is small (single digits), flag that the skill-revealing set is tiny and the ≥100-pair curated label set is a prerequisite before the full model matrix is worth its cost. Do not silently proceed.

---

### Task 4: Deterministic rerankers (top-1, rm_anchor)

**Files:**
- Create: `studies/annotation_reranking/rerankers/__init__.py`
- Create: `studies/annotation_reranking/rerankers/base.py`
- Create: `studies/annotation_reranking/rerankers/deterministic.py`
- Test: `tests/studies/annotation_reranking/test_deterministic.py`

**Interfaces:**
- Consumes: `Candidate`.
- Produces:
  - `Reranker` = `Protocol` with `name: str` and `select(candidates: list[Candidate]) -> str | None`.
  - `Top1Reranker()` and `RmAnchorReranker()` implementing it.
  - `REGISTRY: dict[str, Reranker]` in `base.py` (deterministic entries registered here; LLM entries added in Task 5).

- [ ] **Step 1: Write the failing test**

```python
# tests/studies/annotation_reranking/test_deterministic.py
from studies.annotation_reranking.rerankers.deterministic import Top1Reranker, RmAnchorReranker
from studies.annotation_reranking.models_data import Candidate

def _c(cid, score, rm): return Candidate(id=cid, score=score, name=cid, equivalent_ids=(["RM:1"] if rm else []))

def test_top1_picks_highest_score():
    cands = [_c("CHEBI:2", 4.9, False), _c("CHEBI:9", 3.1, True)]
    assert Top1Reranker().select(cands) == "CHEBI:2"

def test_rm_anchor_prefers_rm_bearing_even_if_lower_score():
    cands = [_c("CHEBI:2", 4.9, False), _c("CHEBI:9", 3.1, True)]
    assert RmAnchorReranker().select(cands) == "CHEBI:9"

def test_rm_anchor_falls_back_to_top_score_when_no_rm():
    cands = [_c("CHEBI:2", 4.9, False), _c("CHEBI:3", 3.1, False)]
    assert RmAnchorReranker().select(cands) == "CHEBI:2"

def test_rm_anchor_breaks_ties_deterministically():
    # two RM-bearing candidates → lowest CURIE string wins (stable, reproducible)
    cands = [_c("CHEBI:50", 2.0, True), _c("CHEBI:27", 2.0, True)]
    assert RmAnchorReranker().select(cands) == "CHEBI:27"

def test_empty_returns_none():
    assert Top1Reranker().select([]) is None
    assert RmAnchorReranker().select([]) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/studies/annotation_reranking/test_deterministic.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `base.py` then `deterministic.py`**

```python
# studies/annotation_reranking/rerankers/base.py
from typing import Protocol, runtime_checkable
from studies.annotation_reranking.models_data import Candidate

@runtime_checkable
class Reranker(Protocol):
    name: str
    def select(self, candidates: list[Candidate]) -> str | None: ...

REGISTRY: dict[str, "Reranker"] = {}

def register(r: "Reranker") -> "Reranker":
    REGISTRY[r.name] = r
    return r
```

```python
# studies/annotation_reranking/rerankers/deterministic.py
from studies.annotation_reranking.models_data import Candidate
from studies.annotation_reranking.rerankers.base import register

class Top1Reranker:
    name = "top1"
    def select(self, candidates: list[Candidate]) -> str | None:
        return max(candidates, key=lambda c: c.score).id if candidates else None

class RmAnchorReranker:
    name = "rm_anchor"
    def select(self, candidates: list[Candidate]) -> str | None:
        if not candidates:
            return None
        rm = [c for c in candidates if c.has_refmet()]
        if rm:
            return min(rm, key=lambda c: c.id).id      # deterministic tie-break
        return max(candidates, key=lambda c: c.score).id

register(Top1Reranker())
register(RmAnchorReranker())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/studies/annotation_reranking/test_deterministic.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add studies/annotation_reranking/rerankers/ tests/studies/annotation_reranking/test_deterministic.py
git commit -m "feat(study): Reranker protocol + top1/rm_anchor deterministic rerankers"
```

---

### Task 5: LLM reranker — prompt (with RM-blinding), parse, off-list handling

**Files:**
- Create: `studies/annotation_reranking/rerankers/llm.py`
- Test: `tests/studies/annotation_reranking/test_llm.py`

**Interfaces:**
- Consumes: `Candidate`; `call_model` (Task 6) is injected, so this task tests prompt/parse in isolation with a stub callable.
- Produces:
  - `build_prompt(candidates: list[Candidate], blind_rm: bool) -> str`
  - `parse_selection(text: str, candidates: list[Candidate]) -> str | None` (returns a candidate id present in the list, else `None` for off-list/malformed)
  - `LlmReranker(model_name: str, call_fn, blind_rm: bool)` with `.name` = `f"llm:{model_name}{'/blind' if blind_rm else ''}"` and `.select(candidates) -> str | None`.

**RM-blinding rule:** when `blind_rm=True`, strip any `equivalent_ids`/`prefixes` entry beginning `RM:` and drop the RefMet canonical name from the serialized candidate, so the model cannot key on the anchor feature.

- [ ] **Step 1: Write the failing test**

```python
# tests/studies/annotation_reranking/test_llm.py
from studies.annotation_reranking.rerankers.llm import build_prompt, parse_selection, LlmReranker
from studies.annotation_reranking.models_data import Candidate

def _c(cid, rm): return Candidate(id=cid, score=1.0, name=cid, equivalent_ids=(["RM:9", "HMDB:1"] if rm else ["HMDB:1"]))

def test_blind_strips_rm_ids_from_prompt():
    cands = [_c("CHEBI:1", True), _c("CHEBI:2", False)]
    assert "RM:9" in build_prompt(cands, blind_rm=False)
    assert "RM:9" not in build_prompt(cands, blind_rm=True)

def test_parse_accepts_in_list_curie():
    cands = [_c("CHEBI:1", True), _c("CHEBI:2", False)]
    assert parse_selection("I choose CHEBI:2 because ...", cands) == "CHEBI:2"

def test_parse_rejects_off_list_or_garbage():
    cands = [_c("CHEBI:1", True)]
    assert parse_selection("CHEBI:99999", cands) is None      # hallucinated / off-list
    assert parse_selection("none of these", cands) is None

def test_llm_reranker_uses_injected_call_fn():
    cands = [_c("CHEBI:1", True), _c("CHEBI:2", False)]
    stub = lambda model, prompt: ("CHEBI:2", 0.0, 0.0)  # (text, cost, latency)
    r = LlmReranker("sonnet", call_fn=lambda m, p: stub(m, p)[0], blind_rm=True)
    assert r.name == "llm:sonnet/blind"
    assert r.select(cands) == "CHEBI:2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/studies/annotation_reranking/test_llm.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `llm.py`**

```python
# studies/annotation_reranking/rerankers/llm.py
import re
from studies.annotation_reranking.models_data import Candidate

_INSTRUCTION = (
    "You are matching a metabolite query to the single best knowledge-graph node.\n"
    "Choose exactly one candidate. Respond with ONLY its CHEBI CURIE (e.g. CHEBI:12345)."
)

def _serialize(c: Candidate, blind_rm: bool) -> str:
    equiv = [e for e in c.equivalent_ids if not (blind_rm and e.startswith("RM:"))]
    return f"- {c.id} | name={c.name} | score={c.score} | equivalent_ids={equiv}"

def build_prompt(candidates: list[Candidate], blind_rm: bool) -> str:
    lines = "\n".join(_serialize(c, blind_rm) for c in candidates)
    return f"{_INSTRUCTION}\n\nCandidates:\n{lines}\n\nAnswer with one CURIE:"

def parse_selection(text: str, candidates: list[Candidate]) -> str | None:
    ids = {c.id for c in candidates}
    for m in re.findall(r"CHEBI:\d+", text):
        if m in ids:
            return m
    return None

class LlmReranker:
    def __init__(self, model_name: str, call_fn, blind_rm: bool):
        self.model_name = model_name
        self.call_fn = call_fn            # (model_name, prompt) -> str
        self.blind_rm = blind_rm
        self.name = f"llm:{model_name}{'/blind' if blind_rm else ''}"

    def select(self, candidates: list[Candidate]) -> str | None:
        if not candidates:
            return None
        text = self.call_fn(self.model_name, build_prompt(candidates, self.blind_rm))
        return parse_selection(text, candidates)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/studies/annotation_reranking/test_llm.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add studies/annotation_reranking/rerankers/llm.py tests/studies/annotation_reranking/test_llm.py
git commit -m "feat(study): LLM reranker with RM-blinding + off-list-safe parsing"
```

---

### Task 6: Unified model call layer + roster

**Files:**
- Create: `studies/annotation_reranking/model_call.py`
- Test: `tests/studies/annotation_reranking/test_model_call.py`

**Interfaces:**
- Produces:
  - `ModelCfg(label: str, provider: str, model_id: str, quant_note: str)` dataclass. `provider ∈ {"anthropic", "openai", "openrouter"}`.
  - `ROSTER: list[ModelCfg]` — the full matrix: Opus, Sonnet (anthropic), a GPT-5.5-class id (openai; pin at run time), Qwen3-4B, Qwen3-8B + comparables (openrouter, `quant_note="OpenRouter fp8, NOT local Q4"`).
  - `call_model(cfg: ModelCfg, prompt: str, seed: int = 0) -> tuple[str, float, float]` → `(text, cost_usd, latency_s)`, `temperature=0`.

**Note on the billing-leak caveat:** this harness makes **direct single-shot API calls** — it does not spawn `ce:` subagents, so the model-ablation subagent-billing-leak does not apply. Cost is read from each SDK response's usage where available; for OpenRouter, prefer the response's reported cost, else compute from token usage × the pinned per-model price recorded in the manifest.

- [ ] **Step 1: Write the failing test (mock SDK clients)**

```python
# tests/studies/annotation_reranking/test_model_call.py
from unittest.mock import patch
from studies.annotation_reranking import model_call
from studies.annotation_reranking.model_call import ModelCfg

def test_roster_has_full_matrix_providers():
    labels = {c.label for c in model_call.ROSTER}
    assert {"opus", "sonnet"} <= labels
    assert any(c.provider == "openai" for c in model_call.ROSTER)     # GPT-5.5-class
    assert any(c.provider == "openrouter" for c in model_call.ROSTER) # small open
    assert all(c.quant_note for c in model_call.ROSTER if c.provider == "openrouter")

def test_call_model_openrouter_returns_text_cost_latency():
    cfg = ModelCfg("qwen3-8b", "openrouter", "qwen/qwen3-8b", "OpenRouter fp8, NOT local Q4")
    fake = {"text": "CHEBI:2", "cost": 0.0004}
    with patch.object(model_call, "_call_openrouter", return_value=fake):
        text, cost, latency = model_call.call_model(cfg, "prompt", seed=0)
    assert text == "CHEBI:2" and cost == 0.0004 and latency >= 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/studies/annotation_reranking/test_model_call.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `model_call.py`**

```python
# studies/annotation_reranking/model_call.py
import os, time
from dataclasses import dataclass

@dataclass
class ModelCfg:
    label: str
    provider: str          # "anthropic" | "openai" | "openrouter"
    model_id: str
    quant_note: str = ""

# Frontier ids are pinned at run time (see manifest). Values below are the
# intended slots; confirm exact ids before a billed run.
ROSTER: list[ModelCfg] = [
    ModelCfg("opus",    "anthropic",  "claude-opus-4-8"),
    ModelCfg("sonnet",  "anthropic",  "claude-sonnet-4-6"),
    ModelCfg("gpt-5.5", "openai",     "PIN_AT_RUNTIME"),
    ModelCfg("qwen3-4b","openrouter", "qwen/qwen3-4b", "OpenRouter fp8, NOT local Q4"),
    ModelCfg("qwen3-8b","openrouter", "qwen/qwen3-8b", "OpenRouter fp8, NOT local Q4"),
]

def _load_openrouter_key() -> str:
    # ~/.config/model-ablation/env holds: export OPENROUTER_API_KEY=sk-or-...
    path = os.path.expanduser("~/.config/model-ablation/env")
    if os.getenv("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"]
    with open(path) as fh:
        for line in fh:
            if "OPENROUTER_API_KEY" in line:
                return line.strip().split("=", 1)[1].strip().strip('"')
    raise RuntimeError("OPENROUTER_API_KEY not found")

def _call_openrouter(model_id: str, prompt: str, seed: int) -> dict:
    from openai import OpenAI
    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=_load_openrouter_key())
    resp = client.chat.completions.create(
        model=model_id, temperature=0, seed=seed,
        messages=[{"role": "user", "content": prompt}],
    )
    text = resp.choices[0].message.content or ""
    cost = getattr(getattr(resp, "usage", None), "cost", 0.0) or 0.0
    return {"text": text, "cost": float(cost)}

def _call_anthropic(model_id: str, prompt: str, seed: int) -> dict:
    from anthropic import Anthropic
    client = Anthropic()
    resp = client.messages.create(
        model=model_id, max_tokens=64, temperature=0,
        messages=[{"role": "user", "content": prompt}],
    )
    return {"text": resp.content[0].text, "cost": 0.0}  # cost computed from usage in manifest

def _call_openai(model_id: str, prompt: str, seed: int) -> dict:
    from openai import OpenAI
    client = OpenAI()
    resp = client.chat.completions.create(
        model=model_id, temperature=0, seed=seed,
        messages=[{"role": "user", "content": prompt}],
    )
    return {"text": resp.choices[0].message.content or "", "cost": 0.0}

_DISPATCH = {"openrouter": _call_openrouter, "anthropic": _call_anthropic, "openai": _call_openai}

def call_model(cfg: ModelCfg, prompt: str, seed: int = 0) -> tuple[str, float, float]:
    t0 = time.monotonic()
    out = _DISPATCH[cfg.provider](cfg.model_id, prompt, seed)
    return out["text"], float(out.get("cost", 0.0)), time.monotonic() - t0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/studies/annotation_reranking/test_model_call.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add studies/annotation_reranking/model_call.py tests/studies/annotation_reranking/test_model_call.py
git commit -m "feat(study): unified model-call layer + full-matrix roster"
```

---

### Task 7: Scoring + statistics (per-regime accuracy, Wilson CI, McNemar)

**Files:**
- Create: `studies/annotation_reranking/scoring.py`
- Test: `tests/studies/annotation_reranking/test_scoring.py`

**Interfaces:**
- Consumes: `RerankResult` from Task 1.
- Produces:
  - `wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]`
  - `accuracy(results: list[RerankResult]) -> tuple[float, tuple[float, float]]` (point + Wilson CI, over results with `is_correct is not None`)
  - `mcnemar_exact(a_correct: list[bool], b_correct: list[bool]) -> tuple[int, int, float]` → `(b01, b10, p_value)` two-sided exact binomial on discordant pairs.
  - `min_discordant_for_sig(n_discordant: int, alpha: float = 0.05) -> int` (helper that reports the ≥6-on-n≈13 fact).

- [ ] **Step 1: Write the failing test**

```python
# tests/studies/annotation_reranking/test_scoring.py
import math
from studies.annotation_reranking.scoring import wilson_ci, mcnemar_exact, min_discordant_for_sig

def test_wilson_ci_bounds_are_ordered_and_in_unit_interval():
    lo, hi = wilson_ci(1, 13)
    assert 0.0 <= lo < hi <= 1.0

def test_mcnemar_all_discordant_one_direction_is_significant():
    a = [True]*6 + [False]*7   # model A correct on 6 where B wrong
    b = [False]*6 + [False]*7
    b01, b10, p = mcnemar_exact(a, b)
    assert b10 == 6 and b01 == 0
    assert p < 0.05

def test_mcnemar_small_delta_not_significant():
    a = [True, True, False, False]
    b = [False, True, True, False]   # 1 vs 1 discordant
    _, _, p = mcnemar_exact(a, b)
    assert p > 0.05

def test_min_discordant_threshold_matches_doc_claim():
    # the "≥6 discordant pairs to clear p<0.05" fact the design doc cites
    assert min_discordant_for_sig(6) <= 6
    assert min_discordant_for_sig(4) > 4   # 4 discordant can't reach significance
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/studies/annotation_reranking/test_scoring.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `scoring.py`**

```python
# studies/annotation_reranking/scoring.py
import math
from studies.annotation_reranking.models_data import RerankResult

def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z*z/n
    center = (p + z*z/(2*n)) / denom
    half = (z * math.sqrt(p*(1-p)/n + z*z/(4*n*n))) / denom
    return (max(0.0, center - half), min(1.0, center + half))

def accuracy(results: list[RerankResult]) -> tuple[float, tuple[float, float]]:
    scored = [r for r in results if r.is_correct is not None]
    n = len(scored)
    k = sum(1 for r in scored if r.is_correct)
    return (k / n if n else 0.0, wilson_ci(k, n))

def _binom_pmf(k: int, n: int, p: float = 0.5) -> float:
    return math.comb(n, k) * p**k * (1-p)**(n-k)

def mcnemar_exact(a_correct: list[bool], b_correct: list[bool]) -> tuple[int, int, float]:
    b01 = sum(1 for a, b in zip(a_correct, b_correct) if (not a) and b)
    b10 = sum(1 for a, b in zip(a_correct, b_correct) if a and (not b))
    n = b01 + b10
    if n == 0:
        return (b01, b10, 1.0)
    x = min(b01, b10)
    tail = sum(_binom_pmf(i, n) for i in range(0, x + 1))
    return (b01, b10, min(1.0, 2 * tail))

def min_discordant_for_sig(n_discordant: int, alpha: float = 0.05) -> int:
    # smallest all-one-direction discordant count whose two-sided exact p < alpha
    for m in range(1, n_discordant + 1):
        if 2 * _binom_pmf(0, m) < alpha:
            return m
    return n_discordant + 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/studies/annotation_reranking/test_scoring.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add studies/annotation_reranking/scoring.py tests/studies/annotation_reranking/test_scoring.py
git commit -m "feat(study): scoring + exact McNemar/Wilson statistics"
```

---

### Task 8: Orchestrator — full matrix, shadow paths, timestamped output, manifest

**Files:**
- Create: `studies/annotation_reranking/run.py`
- Test: `tests/studies/annotation_reranking/test_run.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `build_manifest(csv_path, top_n, seeds, roster, hardware) -> dict` (pure; pins hash/models/seeds/quant/hardware).
  - `score_case(case, candidates, reranker, model_label) -> RerankResult` (pure; handles empty list, off-list `None`, marks `error`; `is_correct=None` when `label_source=="refmet_agreement"`).
  - `run_matrix(csv_path, top_n=20, seeds=(0,1,2), out_dir=None) -> str` — iterates cases × rerankers × models × seeds, writes `results.jsonl` + `manifest.json` + `summary.json` to a **timestamped dir by default**, returns the path.

**Shadow-path rules (encode, don't defer):** empty candidate list → `selected_id=None`, `error="empty_candidates"`, `is_correct=False`; off-list/unparseable LLM output → `error="off_list"`, `is_correct=False` (never silently dropped); API exception → caught, `error=str(e)`, `is_correct=False`, run continues; ordering counterbalanced by shuffling candidates per seed with a seeded RNG.

- [ ] **Step 1: Write the failing test (pure pieces, no network)**

```python
# tests/studies/annotation_reranking/test_run.py
from studies.annotation_reranking.run import build_manifest, score_case
from studies.annotation_reranking.rerankers.deterministic import RmAnchorReranker
from studies.annotation_reranking.models_data import EvalCase, Candidate

def _case(correct, src): return EvalCase("x","MS2","1","r",["CHEBI:2"],"b","cat",correct,src)

def test_manifest_pins_reproducibility_fields():
    m = build_manifest("SOME.csv", 20, (0,1,2), [], "test-box")
    for key in ("dataset_sha256", "top_n", "seeds", "temperature", "models", "hardware"):
        assert key in m
    assert m["temperature"] == 0

def test_score_case_empty_candidates_marks_error_not_drop():
    r = score_case(_case("CHEBI:9","independent_refmet_error"), [], RmAnchorReranker(), None)
    assert r.selected_id is None and r.error == "empty_candidates" and r.is_correct is False

def test_score_case_refmet_agreement_is_unscored():
    cands = [Candidate("CHEBI:2", 5.0, "n", equivalent_ids=["RM:1"])]
    r = score_case(_case(None, "refmet_agreement"), cands, RmAnchorReranker(), None)
    assert r.is_correct is None            # agreement only, never counted as skill

def test_score_case_independent_correct_is_scored():
    cands = [Candidate("CHEBI:9", 3.0, "n", equivalent_ids=["RM:1"]),
             Candidate("CHEBI:2", 5.0, "n", equivalent_ids=[])]
    r = score_case(_case("CHEBI:9","independent_biomapper_error"), cands, RmAnchorReranker(), None)
    assert r.selected_id == "CHEBI:9" and r.is_correct is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/studies/annotation_reranking/test_run.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement `run.py`**

```python
# studies/annotation_reranking/run.py
import json, os, random, datetime as _dt
from studies.annotation_reranking.dataset import load_eval_cases, dataset_sha256
from studies.annotation_reranking.retrieval import fetch_candidates
from studies.annotation_reranking.regimes import classify_regime
from studies.annotation_reranking.models_data import RerankResult
from studies.annotation_reranking.rerankers.base import REGISTRY

def build_manifest(csv_path, top_n, seeds, roster, hardware) -> dict:
    return {
        "dataset_sha256": dataset_sha256(csv_path) if os.path.exists(csv_path) else None,
        "top_n": top_n, "seeds": list(seeds), "temperature": 0,
        "models": [getattr(c, "model_id", str(c)) for c in roster],
        "quant_notes": {getattr(c, "label", ""): getattr(c, "quant_note", "") for c in roster},
        "hardware": hardware,
    }

def score_case(case, candidates, reranker, model_label) -> RerankResult:
    regime = classify_regime(candidates)
    base = dict(case_name=case.name, reranker=reranker.name, model=model_label,
                correct_id=case.correct_id, label_source=case.label_source, regime=regime,
                cost_usd=0.0, latency_s=0.0)
    if not candidates:
        return RerankResult(selected_id=None, is_correct=False, error="empty_candidates", **base)
    try:
        selected = reranker.select(candidates)
    except Exception as e:  # API/parse failure — record, continue
        return RerankResult(selected_id=None, is_correct=False, error=str(e), **base)
    if selected is None:
        return RerankResult(selected_id=None, is_correct=False, error="off_list", **base)
    is_correct = None if case.correct_id is None else (selected == case.correct_id)
    return RerankResult(selected_id=selected, is_correct=is_correct, **base)

def run_matrix(csv_path, top_n=20, seeds=(0, 1, 2), out_dir=None, hardware="unspecified") -> str:
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = out_dir or os.path.join(os.path.dirname(__file__), "runs", stamp)
    os.makedirs(out_dir, exist_ok=True)
    cases = load_eval_cases(csv_path)
    with open(os.path.join(out_dir, "manifest.json"), "w") as fh:
        json.dump(build_manifest(csv_path, top_n, seeds, list(REGISTRY.values()), hardware), fh, indent=2)
    with open(os.path.join(out_dir, "results.jsonl"), "w") as fh:
        for case in cases:
            candidates = fetch_candidates(case.name, "metabolite", top_n=top_n)
            for seed in seeds:
                rng = random.Random(seed)
                shuffled = candidates[:]
                rng.shuffle(shuffled)                      # position-bias control
                for reranker in REGISTRY.values():
                    r = score_case(case, shuffled, reranker, model_label=None)
                    fh.write(json.dumps(r.__dict__) + "\n")
    print(f"[run] results saved to {out_dir}")
    return out_dir
```

*(LLM rerankers are added to `REGISTRY` by constructing `LlmReranker` per `ModelCfg` and registering them before `run_matrix`; the orchestration loop above is model-agnostic. Wire this in `__main__` / README, Task 9.)*

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/studies/annotation_reranking/test_run.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add studies/annotation_reranking/run.py tests/studies/annotation_reranking/test_run.py
git commit -m "feat(study): matrix orchestrator with shadow-path handling + timestamped output"
```

---

### Task 9: CLI entrypoint, README/reproducibility SOP, full suite green

**Files:**
- Create: `studies/annotation_reranking/README.md`
- Modify: `studies/annotation_reranking/run.py` (add `__main__` CLI + LLM registration)
- Modify: `.gitignore` (add `studies/annotation_reranking/runs/`)

**Interfaces:**
- Produces: `python -m studies.annotation_reranking.run --top-n 20 --seeds 0,1,2 [--out DIR] [--models sonnet,qwen3-8b]` — registers deterministic + selected LLM rerankers, runs the matrix, prints the saved path.

- [ ] **Step 1: Add `__main__` CLI + LLM registration to `run.py`**

```python
# append to studies/annotation_reranking/run.py
def _register_llms(model_labels: list[str], blind: bool = True) -> None:
    from studies.annotation_reranking.model_call import ROSTER, call_model
    from studies.annotation_reranking.rerankers.base import register
    from studies.annotation_reranking.rerankers.llm import LlmReranker
    by_label = {c.label: c for c in ROSTER}
    for label in model_labels:
        cfg = by_label[label]
        call_fn = lambda m, p, _cfg=cfg: call_model(_cfg, p)[0]
        register(LlmReranker(cfg.label, call_fn=call_fn, blind_rm=blind))
        register(LlmReranker(cfg.label, call_fn=call_fn, blind_rm=False))

if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="/home/trentleslie/Documents/Trent's Vault/Active 🎯/Work/Projects/biomapper2 - refmet ChEBI analysis/chebi_disagreements_cat.csv")
    ap.add_argument("--top-n", type=int, default=20)
    ap.add_argument("--seeds", default="0,1,2")
    ap.add_argument("--models", default="")   # comma list of roster labels; empty = deterministic only
    ap.add_argument("--out", default=None)
    ap.add_argument("--hardware", default="unspecified")
    a = ap.parse_args()
    if a.models:
        _register_llms([x for x in a.models.split(",") if x])
    path = run_matrix(a.csv, a.top_n, tuple(int(s) for s in a.seeds.split(",")), a.out, a.hardware)
    print(path)
```

- [ ] **Step 2: Write `README.md`**

Include: purpose (one paragraph), the **Phase 0 gate first** instruction, exact run commands (deterministic-only vs. full matrix), where results land (timestamped `runs/<UTC>/` by default), what `manifest.json` pins, and the two caveats that must appear in any writeup: **(1)** without the ≥100-pair curated set the skill-revealing independent subset is ~2 cases (rm_anchor is right-by-construction on the 11 BioMapper-error cases); **(2)** OpenRouter serves open models at fp8, not local Q4 — the local-vs-large *hardware* claim needs a true-Q4 run.

- [ ] **Step 3: Ignore run artifacts**

Add `studies/annotation_reranking/runs/` to `.gitignore`.

- [ ] **Step 4: Run the whole suite**

Run: `uv run pytest tests/studies/annotation_reranking/ -v -m "not external"`
Expected: PASS (all unit tests across Tasks 1–8).

- [ ] **Step 5: Deterministic-only smoke run (no model spend, needs Kestrel)**

Run: `uv run python -m studies.annotation_reranking.run --top-n 20 --seeds 0`
Expected: prints a `runs/<UTC>/` path; `results.jsonl` contains top1 + rm_anchor rows for 172 cases; `manifest.json` has a real `dataset_sha256`.

- [ ] **Step 6: Commit**

```bash
git add studies/annotation_reranking/README.md studies/annotation_reranking/run.py .gitignore
git commit -m "feat(study): CLI entrypoint, reproducibility README, gitignore run artifacts"
```

---

## Self-Review

**Spec coverage (design doc → task):**
- Retrieve top-N candidates (score/name/synonyms/prefixes/equivalent_ids) → Task 2. ✓
- rm_anchor + top-1 baseline → Task 4. ✓
- LLM rerankers (Anthropic/OpenAI/OpenRouter small) → Tasks 5–6. ✓
- **Circularity #1** (don't headline accuracy-vs-RefMet) → `label_source` split; `refmet_agreement` rows carry `is_correct=None` (Task 1, 8). ✓
- **Circularity #2** (independent-label provenance) → the n=2 partition is computed and surfaced; `README` mandates the caveat (Tasks 1, 3, 9). ✓
- **RM: leakage** → RM-blinded condition (Task 5), both conditions registered (Task 9). ✓
- **Statistical validity** → Wilson CI + exact McNemar + `min_discordant_for_sig` (Task 7). ✓
- **Phase 0 regime measurement before model spend** → Task 3 (explicit decision gate). ✓
- **Confounds** (ordering/seed/temperature) → seeded shuffle + temperature=0 (Tasks 6, 8). ✓
- **Shadow paths** (empty/off-list/API failure/tie) → Tasks 4, 8. ✓
- **Reproducibility SOP** (timestamped-by-default, pinned manifest) → Tasks 8–9. ✓
- **Q4-quant caveat / hardware** → `quant_note` in roster + README caveat (Tasks 6, 9). ✓

**Deferred to run-time decisions (not code — flagged in the design doc's Open Questions, not gaps here):** exact GPT-5.5 id (`PIN_AT_RUNTIME`); whether to fund the ≥100-pair curated set (the harness runs on whatever labeled cases exist); local-hosting box for the true-Q4 timing (the fp8 OpenRouter numbers are collected regardless).

**Placeholder scan:** the only intentional literal placeholder is `PIN_AT_RUNTIME` for the GPT-5.5 id and `<AnnotatorClass>`/`<get_equivalent_ids>` in Task 2, each resolved by an explicit confirm-symbol step. No "TODO/handle edge cases" left in logic.

**Type consistency:** `Candidate`, `EvalCase`, `RerankResult` defined once in `models_data.py`; `select()` returns `str | None` everywhere; `call_model` returns `(text, cost, latency)` consistently; `Reranker.name` used as the results key throughout.
