---
status: active
created: 2026-09-08
origin: docs/brainstorms/2026-09-08-resolver-selection-determinism-requirements.md
depth: standard
reviewed: 2026-09-08 (document-review: coherence clean; feasibility + adversarial P1s folded in)
---

# Deterministic node selection in the resolver — Plan

## Problem frame

`Resolver._choose_best_kg_id` (`src/biomapper2/core/resolver.py:100`) picks the winning KG node by a
majority vote (line 130): `majority = max(kg_ids_dict, key=lambda k: len(kg_ids_dict[k]))`. `max()` has
**no tie-break on count ties**, so it returns whichever key is first in dict-iteration order — which
follows Kestrel API-response order and therefore varies with batch/process history. The adjacent
RefMet-conflict branch was already hardened with `sorted()` (lines 142+) with a comment naming this exact
hazard, but the **default majority path was left order-dependent**. Retinol's two ChEBI siblings
(`CHEBI:12777` correct, `CHEBI:132246` wrong) tie on count with no RefMet vote, fall through to line 130,
and flip between runs — spuriously "missing" a cross-cohort link (see origin:
docs/brainstorms/2026-09-08-resolver-selection-determinism-requirements.md).

**Determinism, not correctness.** This fix removes the run-to-run FLIP. It does NOT claim to pick the
chemically-correct sibling on a genuine tie — the winner is arbitrary-but-stable. To keep that honest
(and to preserve the "this row was a coin-flip" signal the flip used to give for free), a genuine 2+
candidate tie now **logs a warning and returns a review flag** (`arbitrary_tiebreak`), mirroring the
existing RefMet branch. Determinism buys reproducibility; the flag buys honesty.

## Scope boundary

- IN: the tie-break for the default majority vote in `_choose_best_kg_id`; a review flag + warning on
  genuine ties; a determinism regression test incl. the tie x RefMet interaction; an audit for ALL
  order-dependent single-winner selection on the resolution path (not just `max()`).
- OUT: the RefMet source-weighting rule itself, annotation, linking, structure-resolution logic; any
  studies/ production change; any new candidate source or re-scoring of the majority rule. This changes
  behavior ONLY on rows that have a genuine count tie.

## Requirements traceability

| Req | Where addressed |
|-----|-----------------|
| R1 determinism (same name -> same node regardless of batch history) | Unit 2 stable tie-break |
| R2 canonical-prefix preference + deterministic total-order fallback | Unit 2 `_stable_majority` |
| R3 no-op on clear majority (only genuine ties change) | Unit 2 single-candidate fast path + Unit 3 T2 |
| R4 RefMet path *determinized, not bypassed* — outcome now stable on tied small-molecule rows | Unit 2 (majority is the branch's input) + Unit 3 T5 |
| R5 determinism regression test fails pre-fix | Unit 3 T1 |
| R6 genuine tie is surfaced (warning + review flag), not silently resolved | Unit 2 flag + Unit 3 T4 asserts the flag |

## Approach & key decisions

**Decision D1 — deterministic total order is the floor; canonical-prefix is a refinement; the flag makes
arbitrariness honest.** The final fallback must be a genuine total order over CURIEs that is
batch-independent (satisfies R1/R5). Lexicographic string sort is one such order but is chemically
arbitrary AND not even numeric within a namespace (`sorted(['CHEBI:12777','CHEBI:132246','CHEBI:983'])`
puts `CHEBI:983` last). So the fallback sorts by `(local-id as int when integer else +inf, full CURIE
string)` to avoid implying "lower CURIE is canonical" while staying total and stable. On top of that,
among the tied-max candidates, prefer those whose prefix is in the category's preferred-prefix set. A
genuine tie still emits `arbitrary_tiebreak` regardless of which layer decides it.

**Decision D2 — tie-break fires only on a genuine count tie.** Compute `max_count`; collect candidates at
that count; if exactly one, return it unchanged (byte-identical to today, R3). Only 2+ tied candidates
run the deterministic ordering + flag. This is what makes the change a no-op on clear-majority rows.

**Decision D3 — reuse the existing canonical-namespace *policy source*, reconstructed for the resolver
(NOT the AnnotationEngine property).** `_category_preferred_prefixes` is a `@cached_property` on
`AnnotationEngine`; `Resolver.__init__` holds only `linker/biolink_client/lipid_resolver` and has no
AnnotationEngine reference — so the property is NOT directly reusable. The reusable pieces are the config
constant `CATEGORY_PREFERRED_NAMESPACES` (importable from `..config`, already used by AnnotationEngine)
plus `self.biolink_client` for subtree expansion. O1 (below) decides whether to reconstruct the
category->preferred-prefix set in the resolver from that config or to ship the numeric/lexicographic
floor alone. Do not describe this as "reusing the property."

Retinol worked example (coincidence, labeled as such): both candidates are `CHEBI:` so the preferred-prefix
layer keeps both; the numeric fallback orders `12777 < 132246` -> `CHEBI:12777`, which *happens* to be the
correct node. A differently-numbered correct sibling could be deterministically wrong every run — hence the
`arbitrary_tiebreak` flag. The guarantee is reproducibility, not chemical correctness.

## Implementation units

### Unit 0 — diagnostic spike (BLOCKING, supervised operator step; # pragma: no cover)
Files: `studies/external_benchmarks/diagnostics/resolver_determinism_probe.py` (new; studies = fork-only,
off org).
- Reproduce the flip on the live #64-patched instance: resolve "retinol (Vitamin A)" (a) in isolation and
  (b) after replaying a large batch (>= the 659-name arivale pass) in the same process, on 8007/8008;
  assert the two chosen nodes differ pre-fix. Persist the transcript (both chosen CURIEs + the
  `kg_ids_dict` at the decision point) to a timestamped path by default.
- Confirm the decision rides line 130 AND identify WHY dict order varies — API-response order vs a
  concurrent-annotator-population race. If the variance source is the kg_ids_dict CONSTRUCTION path rather
  than the max() selection, the fix target moves (see Unit 1); do not attribute to line 130 without this.
- Data-scan (mirrors `refmet_multi_node_rate`): over the benchmark corpus, count how many real rows have a
  genuine default-majority count tie. This quantifies whether the bug is live-and-material or rare.
- GATE (resolves the STOP-vs-ship tension in R-c): 
  * flip reproduces AND traces to the tie-break -> proceed to Unit 2 as a **fix**.
  * flip does NOT reproduce (e.g. instance restarted) but the data-scan shows real rows tie -> proceed as a
    **reproducibility hardening** with that scan as evidence.
  * neither reproduces nor any real row ties -> **STOP**, report a no-op (code hygiene only). Never cite the
    synthetic Unit 3 T1 as evidence a live bug exists — a hand-built tie is order-dependent by construction.

### Unit 1 — audit ALL order-dependent single-winner selection on the resolution path
Files: read-only scan of `src/biomapper2/core/` (resolver, mapper, annotation_engine, structure resolvers,
annotators) AND the kg_ids_dict construction path.
- Grep/inspect not just `max(...)` but every place a single winner is taken from an unordered collection:
  `next(iter(...))`, `[0]` on an unsorted list, set-iteration order, `.pop()`, dict-first-key, and the code
  that BUILDS `kg_ids_dict` in Kestrel-response order. Reproducibility fails if ANY of these stay
  order-dependent — fixing only line 130 is necessary but maybe not sufficient.
- Fix same-path sites that share the batch-order dependence (fold in the same helper); scope genuinely
  separate ones to a follow-up and say so in the PR. Record all findings in the PR description.

### Unit 2 — deterministic tie-break + review flag on the default majority  [feature-bearing]
Files: `src/biomapper2/core/resolver.py`.
- Add an instance method `self._stable_majority(kg_ids_dict, category) -> tuple[str, str | None]` used in
  place of line 130 (it needs `self.biolink_client`/config, so it is a METHOD, not a free pure function —
  correcting the earlier "pure helper" framing):
  1. `max_count = max(len(v) for v in kg_ids_dict.values())`.
  2. `tied = [k for k, v in kg_ids_dict.items() if len(v) == max_count]`.
  3. if `len(tied) == 1`: return `(tied[0], None)` (R3 no-op, no flag).
  4. else: partition `tied` by whether the CURIE prefix is in the category's preferred set (empty/unknown ->
     no partition); return `(min(preferred or tied, key=_curie_sort_key), "arbitrary_tiebreak")` and log a
     warning naming the tied set — mirroring the RefMet branch's existing warning.
  `_curie_sort_key` gives a total order without implying canonicality: `(int(local) if local.isdigit()
  else inf, full_curie)`.
- `majority` becomes `_stable_majority(...)[0]`; thread the `arbitrary_tiebreak` flag through so it reaches
  the returned review_flag when the RefMet branch does not override it. The RefMet branch keeps reading
  `majority` — now a stable value — so its outcome on tied small-molecule rows becomes deterministic (this
  is R4, and is TESTED in T5).
- Resolve O1 here; if reconstructing the preferred-prefix set is non-trivial, ship the numeric/lexicographic
  floor (still satisfies R1/R5/R6) and leave a typed TODO referencing D3.

### Unit 3 — determinism regression + no-op + interaction tests  [feature-bearing, <=8 tests]
Files: `tests/test_resolver_determinism.py` (new). Monkeypatch network; no live entry.
- T1 (MUST fail pre-fix): two count-tied candidates, called with insertion order A,B then B,A; assert
  identical chosen node.
- T2: clear-majority (one candidate strictly more curies) returns it regardless of order — proves R3 no-op
  and asserts review_flag is None (no spurious flag).
- T3: cross-namespace tie — preferred-prefix candidate tied with a non-preferred one -> preferred wins
  (skip/xfail with a note if O1 ships numeric-only).
- T4: retinol-shaped same-namespace tie -> stable numeric-lower CURIE AND review_flag == "arbitrary_tiebreak"
  (asserts R6 honesty).
- T5 (the interaction the old plan missed): count-tied SMALL-MOLECULE row WITH a single-node RefMet vote and
  mocked connectivity; assert identical chosen_kg_id AND identical review_flag across A,B vs B,A — proves the
  RefMet branch is determinized (R4), not accidentally flipped.

### Unit 4 — supervised live confirmation (operator step, not pytest; # pragma: no cover)
- Re-run the Unit 0 probe against the patched resolver on 8007/8008 for retinol AND >=1 non-retinol tied
  metabolite surfaced by the Unit 0 data-scan: identical in isolation vs after-batch. Persist the confirming
  transcript by default. A single-metabolite check does not substantiate "pipeline reproducible" — cover a
  second case before claiming it. This is the human gate before promotion.

## Test scenarios summary
- Determinism under candidate re-ordering (T1, the failing-first gate).
- Clear-majority invariance / no spurious flag (T2).
- Canonical-prefix preference on cross-namespace ties (T3).
- Retinol-shaped tie -> stable pick + honesty flag (T4).
- Tie x RefMet interaction determinized (T5).
- Live isolation-vs-batch parity on retinol + a non-retinol tie (Unit 4, supervised).

## Sequencing & gates
Unit 0 (blocking spike + data-scan, three-way gate) -> Unit 1 audit -> Unit 2 fix + Unit 3 tests
(co-developed, T1 red before Unit 2) -> `uv run` ruff/black/pyright/pytest green -> Unit 4 supervised live
parity -> PR to fork trentleslie/biomapper2 base dev -> Greptile loop to 5/5 -> then Phenome-Health. Never
straight to org/main.

## Open questions (implementation-time)
- O1 (RESOLVED 2026-09-08, post-Greptile): `_preferred_prefixes` reconstructs the category->preferred
  set in Resolver from `CATEGORY_PREFERRED_NAMESPACES` + `self.biolink_client.get_descendants`, so a
  descendant category (e.g. `biolink:Drug`) inherits its configured ancestor's policy — matching
  AnnotationEngine's semantics. The numeric total-order fallback still guarantees determinism when no
  policy applies.
- O2 (RESOLVED by the Unit 1 audit, 2026-09-08): `resolver.py:286 matches.pop()` is safe (guarded by
  `len(matches) == 1`). Two genuine order-dependent sites remain UPSTREAM at the annotator —
  `core/annotators/kestrel_hybrid.py:191/193` (`max(..., key=score)` picks first on a score tie, gene
  path) and `:183/187/226` (`term_results[0]` top-hit relies on stable Kestrel rank order). These are a
  different selection axis (score-ranked, not count-tie) and are SCOPED TO A FOLLOW-UP with their own
  score-tie stabilizer + tests. **Bounded claim:** this PR determinizes the RESOLVER majority (the
  traced retinol flip); full pipeline reproducibility also needs the annotator follow-up.

## Constraints
uv run; ruff/black line-length 120; pyright gates src+tests (studies excluded, keep clean); <=8 tests/file;
monkeypatch network in tests (never a live call in pytest; 8007/8008 reproduction + PubChem are supervised
operator steps marked # pragma: no cover); persist diagnostic artifacts by default; fork-first PR flow.

## Risks
- R-a: over-correction — the tie-break changes a non-tie resolution. Mitigated by D2 (single-candidate fast
  path) + T2.
- R-b: a deterministic-but-wrong sibling on a genuine tie is a reproducible wrong answer, arguably worse for
  benchmark integrity than an observable flip. Mitigated by the `arbitrary_tiebreak` warning + review flag
  (R6): the coin-flip signal is preserved for downstream honesty rather than silently discarded.
- R-c: Unit 0 cannot reproduce live. Resolved by the three-way gate above — ship as "hardening" ONLY if the
  data-scan shows real rows tie; otherwise STOP. Do not launder a synthetic test into live evidence.
- R-d: a second order-dependent site (Unit 1 / O2) leaves the benchmark non-reproducible after this fix.
  Mitigated by broadening the audit beyond `max()` and requiring a non-retinol live case in Unit 4.
