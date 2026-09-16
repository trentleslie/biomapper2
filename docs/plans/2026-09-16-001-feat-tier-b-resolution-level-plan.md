---
title: "feat: graded resolution level and structure escalation for the Tier B certificate"
type: feat
status: active
date: 2026-09-16
origin: docs/brainstorms/2026-09-16-tier-b-certification-cascade-design.md (on branch feat/cross-cohort-eitl-campaign; rescoped to dev-current)
---

# feat: graded resolution level and structure escalation for the Tier B certificate

**Target repo:** biomapper2 (branch `feat/tier-b-resolution-level`, based on `origin/dev`)
**Base for PRs:** `dev` on the personal fork `trentleslie/biomapper2`, Greptile first, then org `dev`, then org `main`.

## Overview

Dev already carries most of the original Tier B cascade design: the LIPID MAPS
independent-structure source (`lipid_structure_resolver.py`), the retinol
RefMet-availability fix, a pinned RefMet freeze with provenance
(`refmet_snapshot.py` / `refmet_store.py`), multi-valued InChIKey matching, full
node-side keys, and a block1-plus-block2 comparison (`structural_agree`). This
plan is the rescoped remainder: surface a graded `resolution_level` on the
certificate, add the structure escalation that reclaims false contradictions,
emit a review hint, extend the freeze and version provenance to the independent
structure fetches, and turn Tier B on by default behind a capture-health gate.
This is what produces the NAR preprint Section 3.7 certificate.

## Problem Frame

Dev's certificate is still a binary structural verdict: `issue()` compares the
independent side (`TierBResult.inchikey_block`, truncated to the first block for
MW and PubChem) against the node's full keys via `structural_agree` and emits
`CORROBORATED` or `CONTRADICTED` under `inchikey_first_block_set_intersection/v1`.
Two consequences: a block-1 disagreement is called `CONTRADICTED` even when the
two keys are the same molecule under a different representation or InChI version
(14 of 56 observed false contradictions are common central-metabolism molecules
like glucose and arginine), and the finer agreement `structural_agree` already
computes internally (connectivity versus stereo) is never surfaced. See origin
design: `docs/brainstorms/2026-09-16-tier-b-certification-cascade-design.md`.

## Requirements Trace

- R1. Surface a graded `resolution_level` on the certificate, reusing the existing block1/block2 logic, reported worst-case alongside best-case over multi-valued key lists.
- R2. Widen `TierBResult` to carry the full independent InChIKey so the independent side can be compared at the stereo (block2) level, not only connectivity.
- R3. Add a bounded structure escalation: on a block-1 disagreement, fetch the full InChI for both sides under one pinned InChI version and reclaim same-molecule-different-representation (`structure_normalized`) versus genuinely different (`contradicted`). Coordinate with dev's existing on-`CONTRADICTED` re-resolution.
- R4. Emit derived `review_recommended` / `review_reason`; routing stays in the EITL layer.
- R5. Extend the freeze mode and per-source version provenance to the independent structure fetches (reuse the RefMet freeze pattern); record `/metagraph` backend identity; patch the `tier_b.py` `CachedSession` redaction gap.
- R6. Default Tier B on for metabolites behind a capture-health gate; no source outage fails a run.

## Scope Boundaries

- Metabolites / `biolink:SmallMolecule` only.
- `issue()` stays pure and IO-free; escalation results are pre-computed in the Tier B module and passed in.
- Reuse dev components; do not rebuild them: `LipidStructureResolver`, `StructureResolver` (`connectivity_match`, `structural_inchikey(s)`, `_frozen_inchikey`), the RefMet freeze (`REFMET_SNAPSHOT_PATH`, `REFMET_FREEZE_MODES`), `structural_agree` / `_split_inchikey`.

### Already on dev (explicitly not in scope)

- LIPID MAPS Tier B source (`lipid_structure_resolver.py`, the third hop in `tier_b.py`). Done.
- Retinol / RefMet-availability fix (PR #68). Done.
- Multi-valued InChIKey matching and full node-side keys (`node_full_inchikeys_from_equivalent_ids`). Done.
- RefMet pinned freeze and its provenance. Done; this plan extends the pattern to the structure fetches, it does not touch RefMet.

### Deferred to Separate Tasks

- The harmonization module (`same_name` / `same_id` over two cohorts): follow-on; only the shared comparator seam lands here.
- The EITL review workflow.
- A `BaseTierBSource` registry generalization: dev's injected-hop pattern already works; the registry is optional generality and is not needed for the preprint. Deferred.

## Context & Research

### Relevant Code and Patterns (dev / `origin/dev`)

- `src/biomapper2/core/certificate.py`: `issue()` at line 331; `structural_agree` (block1 then block2[:8]) and `_split_inchikey`; `node_full_inchikeys_from_equivalent_ids`; `ResolutionCertificate` with `to_api_dict` / `to_flat_columns` and the RefMet provenance fields (`refmet_availability`, `refmet_source`, `refmet_snapshot_version`); `CertificateState` (`CORROBORATED` / `UNCORROBORATED` / `CONTRADICTED` / `UNAVAILABLE` / `NOT_APPLICABLE`); `StructureStatus`, `TierBOutcome`, `independent_of_selection`, `TIER_B_SOURCE_LIPIDMAPS`; comparison-rule constant still `inchikey_first_block_set_intersection/v1`.
- `src/biomapper2/core/tier_b.py`: `IndependentStructureLookup` with injectable `session` / `sleep` / `clock` / `lipid_resolver`; MW and PubChem return first-block-only keys (`inchikey_block=key.split("-")[0]`); the lipid hop returns a full key; `CachedSession` at line 93 WITHOUT `ignored_parameters`.
- `src/biomapper2/core/structure_resolver.py`: `StructureResolver` with `connectivity_match`, `inchikey_block`, `structural_inchikey` (keeps block2), `structural_inchikeys` (all asserted structures), `_frozen_inchikey` (pinned-freeze-first, live MW/PubChem fallback). This is the name-to-structure hop the escalation extends.
- `src/biomapper2/core/lipid_structure_resolver.py`: `LipidStructureResolver.resolve(name)` returning a full-key `TierBResult`.
- `src/biomapper2/config.py`: `TIER_B_ENABLED` default-off (line 249); re-resolution is inert unless enabled and keys on a `CONTRADICTED` certificate (line 260); RefMet freeze config (`REFMET_SNAPSHOT_PATH`, `REFMET_FREEZE_MODES` = off/frozen/live_backup, `get_refmet_freeze_mode`); `CACHE_DIR` at `0o700`; `CACHE_IGNORED_PARAMETERS`.
- `src/biomapper2/provenance.py`: `RunProvenance` / `KgBuildInfo`; `/metagraph` is the backend-identity endpoint.
- RDKit `rdkit>=2025.9.1`: used only for canonical SMILES today; `inchi.MolFromInchi` / `MolToInchiKey` exist; `Chem.MolFromInchiKey` does not (a key cannot be inverted, so the escalation must fetch full InChI).
- Tests: flat `tests/`, injectable-collaborator fakes; `tests/test_certificate_tier_b.py`, `tests/test_resolution_certificate.py`, `tests/test_structure_resolver.py`, `tests/test_provenance.py`, `tests/test_kestrel_auth_header.py`.

### Institutional Learnings

- Multi-valued InChIKey `[0]` is a repeat defect (PR #36, PR #47); compare set-based with a deterministic tie-break; ship a positive control. `studies/shared_gold_set/labeler.py` keeps `keys[0]` on purpose.
- `requests_cache` redaction is case-sensitive; a warm on-disk cache faked a determinism measurement; test on real bytes with a positive control. `docs/solutions/security-issues/kestrel-api-key-persisted-in-cleartext-to-http-cache-2026-08-05.md`.
- HTTP 200 is not proof of data; check a nonzero-result floor on every fetch. `docs/solutions/runtime-errors/benchmark-runner-empty-dataset-fail-fast-2026-08-06.md`.
- Derive backend identity from `/metagraph`; public Kestrel lacks LIPID MAPS. `docs/solutions/integration-issues/...schedule...2026-08-05.md`, `.../internal-api-key-leaked-to-public-kestrel-...md`.
- Sum-composition lipid names are underdetermined and cannot be certified to a molecule by any source; refused, not certified.

## Key Technical Decisions

- **Surface, do not reinvent, the gradation.** The graded `resolution_level` reuses `_split_inchikey` and the block1/block2 comparison already in `structural_agree`. Levels: `exact_inchikey` (full keys equal), `connectivity` (block1 equal), `structure_normalized` (block1 differs but full InChI matches under a pinned version, from escalation), `formula`, `contradicted`, `unavailable`. Worst-case is reported alongside best-case over the multi-valued lists.
- **No chemistry attribution from a hashed key.** The design's `protonation_charge` and `stereochemistry` rungs are dropped: block2 is a combined stereo/isotope/fixed-H hash and the final char mixes protonation with a version flag; the spike showed zero of the 56 contradictions are reclaimable from keys. Stereo agreement is reported only as `connectivity`-plus-block2-match via the existing `structural_agree`, not as a chemistry claim.
- **Escalation only on block-1 disagreement, bounded to tens of pairs.** Fetch full InChI for the independent side (PubChem `/property/InChI`) and resolve the node side to a structure through the existing `StructureResolver` name-to-structure hop, regenerate both InChIs under one pinned InChI version, and compare. Reclaim `structure_normalized` or keep `contradicted`, recording the differing InChI layer. RDKit regenerates InChI under a pinned version; it does not guess tautomers (its catalog does not cover ring-chain mutarotation). A fetch failure degrades to `formula` and never raises.
- **Coordinate with dev's on-CONTRADICTED re-resolution.** Dev re-resolves conflated KG commits when a certificate is `CONTRADICTED`. The escalation runs first and can reclaim a representation artifact to `structure_normalized` so re-resolution is not triggered on a false contradiction; a genuine `contradicted` still flows into re-resolution unchanged.
- **Extend the RefMet freeze pattern, do not fork it.** The structure fetches (independent full InChI, node structure) get the same three-mode freeze semantics (`off` / `frozen` / `live_backup`) and a per-source version pin, reusing the RefMet snapshot design. Content-addressed, read-time checksum verification, loud freeze-miss.
- **Patch the `CachedSession` redaction gap** at `tier_b.py:93` (`ignored_parameters=CACHE_IGNORED_PARAMETERS`, `allowable_methods=["GET"]`) and add a repo-wide test enumerating every `CachedSession(` site.
- **Default-on behind a capture-health gate.** Flip `TIER_B_ENABLED` default true; a capture is invalid if any source was breaker-open, below its nonzero-result floor, or short on coverage. Ordinary runs are best-effort; authoritative preprint numbers come from a health-gated freeze capture against the internal Kestrel build (public lacks LIPID MAPS), recorded via `/metagraph`.
- **`issue()` stays pure.** All new I/O lives in the Tier B / structure modules and is passed in pre-computed.

## Open Questions

### Resolved During Planning

- Most of the design is on dev; this plan is the net-new remainder (verified against `origin/dev`).
- The graded level reuses `structural_agree`; the escalation reuses `StructureResolver`.
- LIPID MAPS is done; sum-composition names remain refused.

### Deferred to Implementation

- Node-side structure resolution for the escalation: reuse `StructureResolver._resolve_name_key` / `_frozen_inchikey`, extended to fetch full InChI (not only the key). Confirm the endpoint (`/property/InChI`) and the pinned InChI version in Unit 3.
- Exact interplay ordering with dev's re-resolution trigger: confirm in Unit 3 against the resolver path.
- Structure-fetch freeze store format: reuse the RefMet snapshot TSV pattern vs a content-addressed store; decide in Unit 5.

## Implementation Units

- [ ] **Unit 1: Patch the Tier B CachedSession redaction gap**

**Goal:** Close the pre-existing cache-redaction gap every later unit builds on.

**Requirements:** R5

**Dependencies:** None

**Files:**
- Modify: `src/biomapper2/core/tier_b.py` (add `ignored_parameters=CACHE_IGNORED_PARAMETERS` and `allowable_methods=["GET"]` to the `CachedSession` at line 93)
- Test: `tests/test_cached_session_redaction.py` (enumerate every `CachedSession(` site in `src/` and assert each passes `ignored_parameters=CACHE_IGNORED_PARAMETERS`)

**Approach:** Small, independent, lands first.

**Patterns to follow:** `tests/test_kestrel_auth_header.py` redaction assertion; the other three correctly-guarded sites (`utils.py`, `structure_resolver.py`, `annotators/metabolomics_workbench.py`).

**Test scenarios:**
- Security: the `tier_b.py` session passes `ignored_parameters`; the repo-wide test fails if any `CachedSession(` site omits it.

**Verification:** Every `CachedSession` site is redaction-guarded.

- [ ] **Unit 2: Graded resolution_level and full independent key**

**Goal:** Surface the graded level (reusing `structural_agree`) and widen `TierBResult` so the independent side carries a full key.

**Requirements:** R1, R2

**Dependencies:** None

**Files:**
- Modify: `src/biomapper2/core/certificate.py` (`ResolutionLevel` enum; `resolution_level` and `resolution_level_worst` fields; a pure `resolve_level(node_keys, independent_keys)` reusing `_split_inchikey`; new comparison-rule constant `inchikey_ladder/v2`; both serializers), `src/biomapper2/core/tier_b.py` (widen `TierBResult` with a full `inchikey` field; stop truncating MW/PubChem to first block, or carry both)
- Test: `tests/test_inchikey_ladder.py`, `tests/test_resolution_certificate.py`, `tests/test_certificate_tier_b.py`, `tests/test_certificate_api_surface.py`

**Approach:** Level is derived from the existing block1/block2 comparison: full-key equal is `exact_inchikey`; block1 equal is `connectivity`; else defer to escalation (Unit 3) or `formula`/`contradicted`. Set-based over full lists, deterministic tie-break, never `[0]`; report worst-case.

**Execution note:** Test-first from a fixture table of key pairs including a multi-key node whose own list is internally contradictory.

**Patterns to follow:** `structural_agree` / `_split_inchikey`; `node_full_inchikeys_from_equivalent_ids`.

**Test scenarios:**
- Happy path: identical full keys -> `exact_inchikey`; block1 equal, keys differ below -> `connectivity`.
- Edge case: match not at index 0 in a multi-valued list -> resolved.
- Edge case: internally contradictory node key list -> `resolution_level_worst` is not `exact_inchikey`.
- Integration: both serializers surface `resolution_level`, `resolution_level_worst`, the full independent key, and the `v2` rule; existing `state` is unchanged.

**Verification:** The level reflects the depth `structural_agree` already computes; the independent side now carries a full key; `issue()` stays pure.

- [ ] **Unit 3: Structure escalation for block-1 disagreements**

**Goal:** Reclaim false contradictions by fetching full InChI on a block-1 disagreement.

**Requirements:** R3

**Dependencies:** Unit 2

**Files:**
- Create: `src/biomapper2/core/structure_escalation.py` (full-InChI fetch for both sides via `StructureResolver`'s hop extended to `/property/InChI`; pinned-version InChI regeneration; layer comparison; differing-layer reason)
- Modify: `src/biomapper2/core/tier_b.py` (trigger escalation on a block-1 disagreement, pass the resolved level in), `src/biomapper2/core/certificate.py` (accept `structure_normalized`; record `escalation_layer_diff` in provenance), `src/biomapper2/core/resolver.py` (ensure escalation runs before the on-`CONTRADICTED` re-resolution so a representation artifact is reclaimed first)
- Test: `tests/test_structure_escalation.py`, `tests/test_certificate_tier_b.py`

**Approach:** Escalation runs only when block1 disagrees. Reuse `StructureResolver._frozen_inchikey` / name-to-structure hop, extended to fetch the full InChI. Regenerate both under one pinned InChI version and compare layers; same molecule -> `structure_normalized`, else `contradicted`. Nonzero-result floor: a 200 with an empty body is a miss, not a match. Fail-soft to `formula`.

**Patterns to follow:** `structure_resolver.py` `_frozen_inchikey` / `_resolve_name_key`; `core/normalizer/cleaners.py` fail-soft RDKit wrapping.

**Test scenarios:**
- Happy path: block1 differs but full InChI matches under the pinned version -> `structure_normalized` with the layer reason (a glucose-class pair reclaimed).
- Error path (positive control): block1 differs and full InChI differs in connectivity -> stays `contradicted` (a gold-defect pair such as glucuronate).
- Edge case: `/property/InChI` returns 200 empty -> `formula`, no fabricated match, no raise.
- Integration: a reclaimed pair does not trigger dev's on-`CONTRADICTED` re-resolution; a genuine contradiction still does.

**Verification:** Glucose-class false contradictions become `structure_normalized`; gold defects stay `contradicted`; re-resolution fires only on genuine contradictions.

- [ ] **Unit 4: review_recommended and review_reason**

**Goal:** Emit a review hint derived from state and level; no routing.

**Requirements:** R4

**Dependencies:** Unit 2

**Files:**
- Modify: `src/biomapper2/core/certificate.py` (derive `review_recommended` / `review_reason`; both serializers)
- Test: `tests/test_certificate_emission.py`

**Approach:** `contradicted` -> `structure_conflict`; resolvable disagreeing `unavailable` -> `unverified_resolvable`; structure-absent lipid only with a conflict signal -> `unverifiable_lipid_conflict`; else none. No blanket lipid flag.

**Patterns to follow:** `derive_chosen_kg_id_review`.

**Test scenarios:**
- Happy path: `contradicted` -> recommended, reason `structure_conflict`.
- Edge case: structure-absent lipid, no conflict signal -> not recommended; with multiple candidate compositions -> `unverifiable_lipid_conflict`.
- Integration: both serializers carry the fields.

**Verification:** Review hint set only for the enumerated cases.

- [ ] **Unit 5: Freeze and version provenance for the structure fetches**

**Goal:** Give the escalation and Tier B structure fetches the RefMet freeze semantics and per-source version pins, and record backend identity.

**Requirements:** R5

**Dependencies:** Units 1, 3

**Files:**
- Modify: `src/biomapper2/core/structure_escalation.py` and `src/biomapper2/core/structure_resolver.py` (three-mode freeze off/frozen/live_backup for structure fetches; per-source version + `fetched_at`; content-addressed store distinct from the working cache; read-time checksum verify; loud freeze-miss), `src/biomapper2/config.py` (freeze-mode config mirroring the RefMet knobs), `src/biomapper2/provenance.py` (per-source versions; `kestrel_metagraph_identity` and `kestrel_endpoint_url` from `GET /metagraph`, env label recorded alongside), `.gitignore` (explicit `!` negation for a committed manifest)
- Create: `scripts/scan-freeze-artifact.sh` (pre-commit / CI scan of the artifact bytes for `CACHE_IGNORED_PARAMETERS` values and credential patterns)
- Test: `tests/test_structure_freeze.py`, `tests/test_provenance.py`

**Approach:** Reuse the RefMet freeze design (`REFMET_SNAPSHOT_PATH`, `REFMET_FREEZE_MODES`, `get_refmet_freeze_mode`). Record versions with `fetched_at` as the floor. Sample `/metagraph` before and after the run.

**Patterns to follow:** `config.py` RefMet freeze; `provenance.py`; `conftest.py` metadata path.

**Test scenarios:**
- Happy path: record then freeze-replay returns identical verdicts with zero network calls.
- Error path: a freeze miss or checksum mismatch fails loud; a warm working cache at the working path is not served as a freeze entry.
- Security: `scripts/scan-freeze-artifact.sh` fails on a planted credential; assertions read real bytes with a positive control.
- Integration: run provenance carries per-source versions and `/metagraph` identity.

**Verification:** Structure fetches replay deterministically and version-pinned; the artifact carries no raw HTTP bytes and passes the scan.

- [ ] **Unit 6: Default-on Tier B with a capture-health gate**

**Goal:** Default Tier B on for metabolites, guarantee degrade-never-fail, and reject a degraded freeze capture.

**Requirements:** R6

**Dependencies:** Units 2 through 5

**Files:**
- Modify: `src/biomapper2/config.py` (`TIER_B_ENABLED` default true; update the default-off contract test), `src/biomapper2/core/tier_b.py` (explicit circuit-breaker cooldown; a source failure degrades to `unavailable`, never raises), the freeze module (capture-health gate: invalid if any source breaker-open, below floor, or short coverage)
- Test: `tests/test_certificate_tier_b.py`, `tests/test_structure_freeze.py`, the config default test

**Approach:** Keep throttle, retry, backoff; add the breaker. A capture that ran degraded is rejected, not pinned. Note that query names are standard chemical names carrying no cohort or study-identifying content; add a per-dataset override.

**Test scenarios:**
- Happy path: default-on run performs Tier B and emits levels.
- Error path: a source raising every call degrades to `unavailable`, run completes, no exception.
- Edge case: the breaker opens after `TIER_B_MAX_ATTEMPTS` for the cooldown (injected clock).
- Capture gate: a capture with a breaker-open source is rejected.
- Contract: the config default test asserts on by default.

**Verification:** Default-on holds; no outage fails a run; a degraded capture is rejected.

## System-Wide Impact

- **Interaction graph:** `issue()` gains `resolution_level` / `resolution_level_worst` and review fields; the Tier B and structure modules gain escalation, freeze, breaker, and version provenance; `provenance.py` gains per-source versions and `/metagraph` identity. Turning `TIER_B_ENABLED` on also activates dev's on-`CONTRADICTED` re-resolution, which the escalation must run ahead of.
- **Error propagation:** escalation and Tier B failures degrade to `formula` or `unavailable`, never a run failure.
- **State lifecycle risks:** the structure-fetch freeze is a new committed artifact; a warm working cache must never be served as a freeze entry (separate content-addressed store plus read-time checksum verify).
- **API surface parity:** both `to_api_dict` and `to_flat_columns` carry every new field.
- **Unchanged invariants:** `issue()` stays pure and IO-free; `studies/shared_gold_set/labeler.py` keeps `keys[0]`; existing states and RefMet provenance fields are reused, not redefined; `structural_agree` semantics are unchanged (the level surfaces them).

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| Escalation misclassifies representation vs real difference | Regenerate both InChIs under one pinned version; positive control that a gold-defect pair stays `contradicted` |
| Escalation double-runs with dev's re-resolution | Escalation runs first; reclaimed pairs do not enter re-resolution; a genuine contradiction still does |
| Multi-valued InChIKey `[0]` reintroduces the repeat defect | Set-based level with deterministic tie-break; worst-case reported |
| Warm cache faked as freeze | Separate content-addressed store; read-time checksum verify; loud miss |
| `CachedSession` leaks the Kestrel key | Patch `tier_b.py:93`; repo-wide `CachedSession` test |
| Degraded capture pinned | Capture-health gate |
| Production run on public Kestrel drops LIPID MAPS | Pin the internal build; record `/metagraph` identity |
| HTTP 200 empty body treated as data | Nonzero-result floor on every fetch |

## Documentation / Operational Notes

- The preprint production run records a structure freeze against the internal Kestrel build, passes the capture-health gate, then Section 3.7 numbers come from a freeze replay; capture `/metagraph` identity and the freeze-manifest hash in run provenance.
- No new runtime dependency expected; if one is added, `uv add` and commit `pyproject.toml` plus `uv.lock`.
- Each unit is one PR on `dev` on the personal fork, Greptile first; run `./scripts/check.sh` before each.

## Sources & References

- Origin design (on `feat/cross-cohort-eitl-campaign`): `docs/brainstorms/2026-09-16-tier-b-certification-cascade-design.md`
- Dev code reused: `src/biomapper2/core/certificate.py`, `tier_b.py`, `structure_resolver.py`, `lipid_structure_resolver.py`, `annotators/refmet_snapshot.py`, `config.py`, `provenance.py`
- Institutional learnings: `docs/solutions/best-practices/audit-instruments-backing-published-claims-2026-08-05.md`, `docs/solutions/security-issues/kestrel-api-key-persisted-in-cleartext-to-http-cache-2026-08-05.md`, `docs/solutions/runtime-errors/benchmark-runner-empty-dataset-fail-fast-2026-08-06.md`
