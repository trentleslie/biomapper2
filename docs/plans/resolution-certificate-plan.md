# Plan — resolution certificate (Tier A + schema + Tier B opt-in)

Artifact: `docs/plans/resolution-certificate-brainstorm.md`
workType: **research** (researchMode: analysis) · Base: `dev` on personal fork `trentleslie/biomapper2`
(Greptile first, never straight to the org) · Branch: `feat/resolution-certificate`

Ledger constraints treated as fixed: **L19** (label-only; Tier B opt-in), **L20** (nested API / flat
TSV; certificate is source of truth; this axis owns the refusal-reason follow-up; record
`comparison_rule`), **L21** (`structure_absent` is `unavailable`, NEVER `contradicted`; publish no
precision gain for refusing it), **L26** (`independent_of_selection`; independence claimed only
where it holds; curve stratified by source), **L27** (no precision delta across the `unavailable`
boundary in Figure 5; abstention reported as a rate), **L28** (refusal-reason ships as a separate
follow-up PR, still owned by this axis), **L29** (dispatch held until #47 merges), **L5** (D3
tighten-only, separate PR), **L11** (category check is a validator on the committed node), **L13**,
**L25** (srm1950 `gold_hmdb` quarantine only).

Branch is rebased onto `origin/dev` @ `b3682bc`, which already contains **#46** (public-Kestrel
default) and **#48** (zero-row fail-fast). Neither is re-fixed here.

> **Revision note.** This plan was rewritten after adversarial + feasibility review. Twenty findings
> were auto-applied (listed in "Review fixes applied"). Three were **premise** problems that a
> reviewer cannot fix unilaterally and were carried to CP2 as decisions: Tier B's independence, how
> Figure 5 renders `unavailable` without restating the L21-forbidden number, and the true size of
> the refusal-reason work. All three are now decided — **L26**, **L27**, **L28** — and folded in below.
>
> **Status: dispatch HELD (L29) until PR #47 merges.** See "Hard dependency ordering".

---

## The one thing this plan must not get wrong

`structure_absent` is **unverifiable**, not wrong (L21). Three places make it easy to reintroduce:

1. **Prose** — no precision claim about the bucket while `sparsity_control.n_absent_oracle_could_fire` is 0.
2. **The state machine** — nothing may assign `contradicted` to a structure-less node (G3, a test).
3. **The figure** — a precision delta plotted *across* the `unavailable` boundary is that same
   forbidden claim rendered as a line. See CP2 decision **D2**.

---

## Hard dependency ordering

**#47 (`fix/resolver-category-acceptance`) must merge before this lands.** It is a functional
dependency, not a rebase hazard, and review found the collision is **same-hunk**:

- #47 rewrites `resolver.py:126-139` — exactly the region this work reads.
- #47 changes `connectivity_match` to first-block **set intersection**; `comparison_rule`'s seed
  value is defined by that semantics, which does not exist on this branch yet.
- `tests/test_no_measured_figures_in_prose.py` (gate G5) is a #47 file.
- The `.gitignore` un-ignore of `studies/analysis/results/*.json` is #47's; the JSON artifact on
  this branch is currently force-added and re-stages cleanly only after the rebase.
- #47 also edits `tests/test_resolver_source_weighting.py` and `tests/test_structure_resolver.py`.

**Dispatch is HELD on this (L29).** #47 is open, mergeable and passed Greptile 5/5; merging it is
Trent's action. On merge: rebase this branch onto it, re-stage the JSON artifact (it is currently
force-added and becomes legitimate under #47's `.gitignore` entry), then dispatch.

---

## Phase 0 — Failing tests (TDD), all offline

1. `tests/test_resolution_certificate.py` — assert no certificate today (red), then one (green).
2. **State table test**, parametrized over **both** emission paths (see Phase 2) and over every
   combination of {`structure_present`, `structure_absent`, non-small-molecule, no committed node} ×
   {Tier B off, resolves+matches, resolves+differs, unresolvable, lookup failed}.
3. **G3 / L21 invariant** — `test_structure_absent_is_never_contradicted`: `state == "contradicted"`
   implies the committed node carried ≥1 InChIKey block. The guard that makes the paper's claim safe.
4. **Legacy-derivation test** — `chosen_kg_id_review` derived from `selection_conflict` is identical
   to today's value across its **three** values (`None`, `divergent_refmet`, `conflict_no_structure`
   — `resolver.py:136-139`; *not* four; the brainstorm's "four states" counts situations collapsed
   into `None`, which is a different thing).
5. **Committed row fixtures.** The pinned baseline lives at `~/benchmark-runs/…`, outside the repo,
   so no test or gate may read it. Commit a small anonymized row fixture under `tests/fixtures/`
   covering all three legacy flag values and both Tier-A states. G4 uses the same fixture.
6. `tests/test_certificate_state_audit.py` — covers the already-committed instrument, including
   `test_unscorable_rows_leave_the_denominator` (the pandas `str`-dtype / `pd.NA` trap fixed in
   `_structure_oracle`, already referenced by name from `certificate_state_audit.py`) and the
   monotonic-counter quarantine.

## Phase 1 — The certificate model

7. New `src/biomapper2/core/certificate.py`: a frozen dataclass `ResolutionCertificate` plus a pure,
   I/O-free `issue(...)`. Pure so Phase 0's table test needs no network.

   | field | type | meaning |
   |---|---|---|
   | `state` | enum | `corroborated` / `uncorroborated` / `contradicted` / `unavailable` / `not_applicable` |
   | `structure_status` | enum | `structure_present` / `structure_absent` / `not_applicable` |
   | `node_inchikey_blocks` | `list[str]` | sorted; committed node's blocks |
   | `independent_source` | `str \| None` | `metabolomics-workbench` / `pubchem` / None |
   | `independent_inchikey_block` | `str \| None` | Tier B result for the QUERY NAME |
   | `independent_of_selection` | `bool \| None` | **L26** — false when the Tier B source is the same registry as the annotator that supplied the committed node (see item 12a) |
   | `comparison_rule` | `str` | identifier of the rule that produced the verdict (L20) |
   | `selection_conflict` | `str \| None` | `divergent_refmet` / `conflict_no_structure` / None |
   | `equivalent_ids_lookup_ok` | `bool` | see item 12 |
   | `refusal_reason` | `str \| None` | **deferred to a follow-up PR (L28)**; field reserved so the schema does not change shape later |
   | `provenance` | `dict` | Tier B enabled?, cache store + hit/miss, expiry policy |

8. **`state` and `selection_conflict` are different axes and must never merge.** `state` describes
   the committed node vs *independent* evidence. `selection_conflict` describes which *candidate*
   won an intra-KG disagreement — both sides from the graph. Today's `divergent_refmet` is a
   selection conflict, **not** a contradiction; folding it into `contradicted` would restate a
   KG-internal disagreement as independent refutation — the same class of error as L21. Tested.
   Note `selection_conflict == "conflict_no_structure"` can legitimately co-occur with
   `structure_status == "structure_present"` (`connectivity_match` returns `None` if *either* node
   is unresolvable, so the committed node may carry a key — 9 such rows on the NECS baseline). The
   legacy name is misleading; it is retained unchanged for compatibility and documented, not renamed.

9. **`not_applicable` is a required state, not a nicety.** Nothing at stage 5 gates on category, so
   without it every gene/protein row derives `structure_absent` → `unavailable`. The pinned suite
   contains `hgnc` and `nlmgene` arms, and HGNC symbol resolution measures high on the batch path
   (figure: `gate.py` capability artifact — not restated here per the provenance standard). Labeling
   that population `unavailable` would be the Finding-3 confound relocated onto genes.

   **Record why this state exists, not just that it does.** `not_applicable` is not defensive
   padding: without it the certificate makes its strongest negative claim about the one population
   it was never designed to judge. `unavailable` means "we looked for a structure and the graph has
   none" — a meaningful statement about a metabolite and a meaningless one about a gene. Deleting
   the state to "simplify the enum" reintroduces L21's error in a new population.

10. State assignment, Tier A only (the default path): non-small-molecule → `not_applicable`;
    `structure_absent` → `unavailable`; `structure_present` → `uncorroborated`. With Tier B on,
    `structure_present` refines to `corroborated` / `contradicted` / stays `uncorroborated`.
    `structure_absent` stays `unavailable` regardless — nothing to compare against.

11. `comparison_rule` seeded to #47's shipped semantics (first-block **set intersection**). D3's
    tightening introduces a second value later; **D3 is not implemented here** (L5).

12. **`structure_absent` must not absorb a Kestrel outage.** `Linker.get_equivalent_ids` returns
    `{}` on any exception and only logs a warning (`core/linker.py:175-177`), so a transient
    `/get-nodes` failure would silently mark an entire run `unavailable`, and an offline rerun on the
    resulting TSV could never detect it. Record `equivalent_ids_lookup_ok` and refuse to issue a
    Tier-A verdict when it is false.

## Phase 2 — Wire it through, changing no committed ID

13. **Both emission paths, or the work is invisible.** Review's top finding: the plan previously
    anchored only on `mapper.py:126-128` (`map_entity_to_kg`, single-entity). Every artifact this
    plan cites — the audit, the suite arms, the Figure 5 curve — comes from `map_dataset_to_kg`,
    whose stage 5 is a *different* block at `mapper.py:250-256` (batched `get_equivalent_ids` +
    `.map`). Both sites build the certificate; the state-table test parametrizes over both.
14. **Build the certificate OUTSIDE the `chosen_kg_id is not None` guard** (`mapper.py:126`). Inside
    it, the rows the certificate most needs to describe — no committed node — get no certificate at
    all, and the two emission surfaces would disagree precisely there.
15. **Do not change `_choose_best_kg_id`'s return signature.** Dropped from the plan. It computes a
    structural verdict only inside the RefMet-conflict branch (`resolver.py:129-139`), so it cannot
    supply `structure_status` for the majority of rows anyway; a 3-tuple would break the
    `x, _ = ...` unpacks at `resolver.py:72,82` plus seven tests, and collides same-hunk with #47
    for no gain. The certificate takes only the flag the resolver already returns.
16. **Tier A reads `kg_equivalent_ids["INCHIKEY"]` only — never `StructureResolver.inchikey_blocks()`.**
    That helper falls through to `_fetch_mw_inchikey`/`_fetch_pubchem_inchikey` when the KG lists no
    key (`structure_resolver.py:75-81`), i.e. on exactly the `structure_absent` population (29.1%
    of NECS rows … 65.4% of LMSD). Calling it would fire an external request per absent row and
    silently reclassify some as `structure_present` from a non-KG source, changing the very
    distribution the committed audit measured.

    **Do not "simplify" this back to the shared helper.** The two look interchangeable in a diff and
    are not: `inchikey_blocks()` answers "what structure can I find for this node by any means",
    Tier A answers "what structure does the GRAPH assert for this node". Only the second is a
    self-certificate, and only the second is free. A future reader consolidating them would break
    the zero-I/O guarantee (G6) and shift the state distribution without any test going red — which
    is why G6 asserts on the StructureResolver session specifically.
17. **Label only (L19).** `chosen_kg_id` is emitted unchanged in every state. **Zero coverage delta
    on this axis** — the PR body says so explicitly rather than borrowing #47's coverage framing.
    Withholding stays a documented extension point, not built.

## Phase 3 — Emission surface (nested API, flat TSV)

18. `api/models/responses.py`: nested `resolution_certificate` on `EntityMappingResult`.
    `chosen_kg_id_review` keeps its field with a deprecation note naming the replacement.
19. **Serialization is specified, because both call sites break by default.** Verified by review:
    pydantic rejects a raw dataclass (`Input should be a valid dictionary or instance of …`), so the
    `EntityMappingResult` construction at `routes/mapping.py:50-51` needs `dataclasses.asdict()` (or
    `from_attributes` + `model_validate`). The streaming endpoint at `:346-347` builds a **plain
    dict**, unvalidated by the response model, and `json.dumps(result)` at `:359` sits **outside**
    the `try/except` at `:352` — a dataclass there raises `TypeError` mid-stream after a 200 is
    already sent. Both sites dump to plain types; a test covers the NDJSON path.
20. Mapped TSV: flat `certificate_*` columns, scalars only. `node_inchikey_blocks` joined on `|`;
    `provenance` split into flat scalar columns; enums serialized as `.value`. **No repr'd dicts** —
    an object column through `df.to_csv` emits `ResolutionCertificate(state=…)`, reintroducing the
    `ast.literal_eval`-only column this design exists to eliminate. Ensure no intermediate object
    column survives `mapper.py:247`'s join to `:270`'s write.
21. Columns are **namespaced to the committed answer**. `chosen_kg_id_provided` and
    `chosen_kg_id_assigned` are separately-emitted columns from `_choose_best_kg_id` calls at
    `resolver.py:72,82` that never receive `category` and get no certificate; a bare
    `certificate_state` would be read as covering them. Document the scope in the column comment
    and the API field description.
22. `chosen_kg_id_review` is **derived** from `selection_conflict` (C4/L20), identical for one
    release, deprecation filed as a follow-up. The derivation rests on an invariant that must be
    stated and tested: a non-`None` flag always co-occurs with a non-`None` `chosen_kg_id` and a
    small-molecule category.

## Phase 4 — Tier B, opt-in (L19)

23. Config flag, default **off**. When on, resolve the QUERY NAME via MW → PubChem. Both
    `_fetch_mw_inchikey` and `_fetch_pubchem_inchikey` already take a name; today they are only ever
    called with the *node's* name as a fallback.

23a. **Tier B via MW is NOT independent of the selector, and that is the whole ballgame (L26).**
    `REFMET_ANNOTATOR = "metabolomics-workbench"` (`resolver.py:21`) is the annotator the resolver
    source-weights *toward*; it queries MW's fuzzy `/refmet/match` with the query name to produce
    the candidate that then wins. Tier B's first hop is MW's `/refmet/name` — **the same registry,
    keyed on the same query name**. On any row where the committed node came from RefMet's vote,
    Tier B asks RefMet whether RefMet was right, and a `corroborated` verdict there is circular.
    That is exactly the population where the independence claim matters, and independence from a
    name is the entire differentiation from UniChem (which needs a registered identifier or a
    structure and cannot start from a name).

    Resolution: keep both hops for coverage, but compute `independent_of_selection` = (the Tier B
    source is not the registry that supplied the committed node) and **claim independence only on
    the subset where it is true**. Figure 5 is stratified by `independent_source`. A test asserts
    that an MW-corroborated row whose committed node came from the RefMet vote has
    `independent_of_selection == False`.
24. **Call them through a guarded wrapper, not directly.** The swallow-everything `try/except` lives
    only in `inchikey_block` (`structure_resolver.py:53-58`); calling the private fetchers directly
    bypasses it and a `raise_for_status()` on a 503 propagates into the mapping loop. Add throttle +
    backoff: PUG-REST is rate-limited, and Tier B moves these calls from a small conflict subset to
    every unique query name across ~10 arms.
25. **A failed lookup is its own state, not `uncorroborated`.** Otherwise a rate-limited PubChem
    turns Figure 5 into a network artifact that `provenance` does not record. Add `lookup_failed`
    (or an explicit provenance flag) distinct from "name genuinely unresolvable".
26. **Report Tier B's own resolution rate.** `MW_INCHIKEY_URL` is the **exact-name** endpoint
    (`config.py`), while the annotator uses fuzzy `refmet/match`. Metabolon-style names
    (`X-12345`, `1-methylhistidine*`) will miss exact lookup often, so `corroborated`/`contradicted`
    would be computed on a biased easy subset. Emit `n_tier_b_resolved / n_unique_query_names`
    beside every Tier-B operating point and refuse to publish the curve below a stated floor.
27. **Cache provenance points at the right cache.** Review correction: the cited confound (a cold
    cache returning `LOINC:45207-8` for glutarylcarnitine) is a **Kestrel resolution** result cached
    in `CACHE_DIR/"kestrel_http"` with a 1-hour expiry (`utils.py:190-194`) — *not* the
    `structure_http` store (`structure_resolver.py:30`, no expiry). Record state for **both**
    stores. Note `_fetch_*` currently discard the `Response`, so `from_cache` requires changing
    those signatures, and `_name_cache` short-circuits before any HTTP call — a third case
    (process memo, no response object) the hit/miss binary does not model.
28. `contradicted` is documented as **"a human should look"**, never "the resolver is wrong" —
    PubChem name lookup returned 4-acetyloxyphenolate for 4-hydroxyphenylacetate. That wording goes
    in the API field description, not only the docs.

## Phase 5 — The Figure 5 curve

29. Extend the already-committed `studies/analysis/certificate_state_audit.py` rather than adding a
    second instrument. **Curve shape is fixed by L27:**
    - **Never plot a precision delta across the `unavailable` boundary.** That delta *is* "refusing
      `structure_absent` buys +N precision" — the L21-forbidden claim, rendered as a line, in the
      one artifact that travels without its caveat.
    - `unavailable` is reported as a **declared abstention rate** (a coverage statistic), not as an
      operating point on a precision curve.
    - The precision-coverage curve is drawn **only within the verifiable population** — the rows an
      oracle can actually adjudicate — and is stratified by `independent_source` per L26.
    - Two-panel form (abstention rate | precision-coverage) is the preferred presentation if the
      floats axis returns panel budget; single-panel with the abstention rate stated in the caption
      otherwise.
30. One committed Tier-B sweep over the pinned suite, saved by default to a timestamped path with
    cache state and inputs pinned. The only network-touching step in the plan. The sweep artifact
    must be **committed and referenced by a fixed name** as a second audit input, or the Tier-B half
    of the figure has no reproducible provenance (the pinned suite has no `certificate_*` columns).
31. Every operating point carries `sparsity_control` and Tier B's resolution rate alongside it.

## Phase 6 — Provenance standard and PR

32. **PR #47's standard is enforced** by `tests/test_no_measured_figures_in_prose.py`: no measured
    figure in any comment or docstring; comments **name the artifact field**. Five review rounds
    established it; the new audit code already complies.
33. Do not duplicate #47's `connectivity_match` change, its `.gitignore` entry, or its validator.
34. PR body leads with: the certificate exists and the paper's central claim is now true of the
    code; **this PR has zero coverage delta** (unlike #47); and L21 stated plainly.

---

## Gates (rewritten — the previous four were unevaluable)

| gate | pass condition |
|---|---|
| **G1 — no committed ID changes** | *Not* a live suite re-diff (unattributable against a 1-hour Kestrel cache expiry and KG drift, and the baseline is outside the repo). Instead: (a) the selection branch is byte-untouched — item 15 removes the only proposed edit to it; (b) unit tests over `_choose_best_kg_id` on frozen inputs; (c) an optional warm-cache single-process A/B, reported not gated. |
| **G2 — legacy flag preserved** | Derived `chosen_kg_id_review` identical across its **three** values on the committed fixture, enums serialized as `.value`. |
| **G3 — L21 invariant** | `contradicted` never issued for a structure-absent node (test, not inspection). |
| **G4 — offline reproducibility** | Audit reruns bit-identical on the **committed fixture** with no network. |
| **G5 — provenance standard** | `tests/test_no_measured_figures_in_prose.py` green (available after #47). |
| **G6 — default path adds no I/O** | Assert on the **StructureResolver session and the Kestrel session**, not the linker — MW/PubChem calls never traverse `Linker`, so a mocked-linker counter is blind to exactly the calls Tier A must not make. |

## Review fixes applied

Both paths wired (13) · certificate built outside the null guard (14) · `not_applicable` state added
(9) · return-signature change dropped (15) · `inchikey_blocks()` banned from Tier A (16) · Kestrel
outage separated from `structure_absent` (12) · three legacy values not four (Phase 0.4, G2) ·
committed fixtures replace out-of-repo baseline (Phase 0.5, G4) · pydantic + NDJSON serialization
specified (19) · enum `.value` and no repr'd columns (20) · column scope namespaced (21) · derivation
invariant stated (22) · guarded Tier B wrapper with throttle/backoff (24) · `lookup_failed` state
(25) · Tier B resolution rate reported (26) · cache provenance retargeted to `kestrel_http` (27) ·
G1/G6 made evaluable · #47 reclassified as a hard functional dependency · line refs corrected to
`routes/mapping.py:50-51` and `:346-347`.

## Non-goals

- **No D3** (L5); no charge/tautomer normalization.
- **No withholding of `chosen_kg_id`** (L19) — extension point only.
- **No fix to srm1950's `gold_hmdb`** (L25); evidence-base owns it.
- **No change to `_select_canonical`**, no namespace whitelist, no pool filter (L11).
- **No re-fix of #46 or #48**; no duplication of #47.
- **No refusal-reason plumbing (L28).** It ships as a separate follow-up PR, still owned by this
  axis. It is a per-annotator, `AssignedIDsDict`-contract-breaking change that cannot be designed
  correctly against an unmerged #47, and bundling it would delay the one thing that makes the
  preprint's central claim true of the code.
