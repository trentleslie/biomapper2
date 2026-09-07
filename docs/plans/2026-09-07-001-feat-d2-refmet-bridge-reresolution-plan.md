---
title: "feat: productionize the certificate-gated RefMet-name bridge (D2 structure-guided re-resolution)"
type: feat
status: draft
date: 2026-09-07
origin: studies/external_benchmarks/scorers/refmet_bridge.py (validated prototype, 2026-09-03 run)
depends_on: fork trentleslie/biomapper2 #60/#61 (lipid resolver + node re-resolution foundation), promoted to org first
gate: studies/external_benchmarks/conflation_gate.py + studies/external_benchmarks/run_conflation_gate_live.py
---

# Productionize the certificate-gated RefMet-name bridge (D2)

## Overview

Move the validated, off-org RefMet-name bridge from the benchmark tree (`studies/external_benchmarks/`)
into the shipped package (`src/biomapper2/`) as a **pure, certificate-gated cross-cohort re-linking
step**, default-off, promoted only if it clears the falsifiable conflation gate.

BioMapper links two cohort entities when their identifier-only CURIE sets intersect (Arm M / R6). The
bridge **adds** a link when two entities share a **RefMet standardized name** but **not** a CURIE, and
**only** when the two sides' **KG-independent** structures certify (agree at `block1 + block2[:8]`). It
rejects the refuted (the other method's wrong-molecule matches), holds the refused (no independent
structure — the frontier), and never imports an un-certified link. On the 2026-09-03 `ab_lipid_oracle`
run the prototype recovered +5/5 certified NECS↔Arivale links and rejected the Monti-error candidates,
importing zero un-certified links.

This is the complement to the node-level re-resolution already shipped in fork #60/#61
(`Resolver.reresolve_on_contradiction` / `Mapper._certify_and_reresolve`): that step **switches** a
committed conflated node when its structure contradicts the query's independent structure; D2
**re-resolves the LINK** — it recovers a cross-cohort link the identifier-only linker missed. Both reuse
the one KG-independent structural certificate seam, so the linker stays structure-free and the
certificate stays non-circular.

Everything except the independent-structure lookups on the frontier population and the single live gate
run is offline and unit-testable first, with the network monkeypatched.

## Problem Frame

- **What D2 is.** A cross-cohort harmonization pass that increases link **recall** without lowering
  precision: for each frontier pair (share a RefMet standardized name, do not share a CURIE), issue the
  KG-independent structural certificate and adopt only the certified links. The prototype lives at
  `studies/external_benchmarks/scorers/refmet_bridge.py` (`certified_bridge_links` + `BridgeResult`),
  driven offline by `studies/external_benchmarks/refmet_bridge_prototype.py`.
- **Why it needs productionizing.** The prototype consumes benchmark run caches and the studies-only
  scorers (`cross_cohort_overlap.curie_set`, `link_certificate.certify_link`), which are excluded from
  the shipped package's ruff/black/pyright gates (`pyproject.toml`: `studies/**` excluded). To ship, the
  logic must live in `src/`, be pyright-clean, be covered by gated `tests/`, and reuse the src-side
  certificate primitives rather than the studies ones.
- **Where the recall gap comes from.** The RefMet standardized name is a fuzzy-normalized label that
  collapses vendor naming differences; two cohorts can resolve the same molecule to different KG nodes
  with non-intersecting CURIE sets (cold-start, namespace divergence, lipid shorthand) yet share a
  RefMet standardized name. The bridge recovers exactly those, gated by structure.

### Scope boundary — explicitly out

- **Not** the node-level re-resolution (switching a committed node) — that is fork #60/#61, already
  built in `src/biomapper2/core/resolver.py::reresolve_on_contradiction` and
  `src/biomapper2/mapper.py::_certify_and_reresolve`. D2 depends on it but does not modify it.
- **Not** a change to the linker's linking rule. The linker stays **identifier-only / structure-free**
  (R6); the bridge is a separate, additive pass, never a new linking namespace inside
  `link_by_intersection`.
- **Not** the benchmark harness itself (`studies/`), except the one gate-arm extension needed to score a
  link-adding treatment (Phase 3). The studies prototype stays as the reference/oracle.
- **Not** a new fuzzy matcher. The bridge keys on the **already-produced** RefMet standardized name
  string; it does not invent a new name-similarity metric.
- **Not** turning any lookup on by default. The bridge and its frontier-population independent-structure
  lookups are default-off, operator-gated (mirrors `TIER_B_ENABLED` / `RERESOLUTION_ENABLED`).
- **Not** an EITL/queue export path. D2 emits links + per-link verdicts; expert triage is downstream.

## Where it slots into the `src/` resolution path

The bridge is a **pure** cross-cohort function; it does not live inside single-entity `resolve`. Three
seams, all already present in `src/`:

1. **The certificate seam (reused, not reinvented).** `src/biomapper2/core/certificate.py` already
   implements the exact `block1 + block2[:8]` verdict the studies `link_certificate.certify_link` uses:
   `structural_key_parts` (splits an InChIKey into `(block1, block2[:8]|None)`, upper-cased) and
   `structural_agree` (connectivity on block1, stereo on block2[:8] only when **both** sides carry it,
   never a silent stereo pass). Productionizing `certify_link` = adding a thin three-verdict wrapper next
   to these (certified / refuted / refused), so the bridge and the node re-resolver share one seam.
2. **The independent-structure anchor (reused).** Each side's structure is the **KG-independent**
   `ResolutionCertificate.independent_inchikey_block` (Tier B / `IndependentStructureLookup` →
   PubChem / LIPID MAPS via `LipidStructureResolver`, or repaired gold), the same anchor
   `reresolve_on_contradiction` takes as `query_independent_inchikey`. Never the committed node's own
   `kg_equivalent_ids["INCHIKEY"]`.
3. **The identifier-only CURIE set (reused, ported).** The frontier test ("do NOT already share a
   CURIE") uses the same identifier-only, structure-namespace-stripped CURIE set the linker uses
   (`studies/.../cross_cohort_overlap.curie_set`, which excludes `INCHIKEY`/`INCHI`/`SMILES`). Port that
   helper into `src/` so the bridge's "already linked?" test is byte-for-byte the linker's rule.

**Which function re-resolves.** The new
`src/biomapper2/core/refmet_bridge.py::certified_bridge_links(...)` re-resolves the **link**: for each
A-side name with a RefMet standardized name, it finds B-side names sharing that standardized name and not
already CURIE-linked, and calls the certificate verdict on the two sides' independent structure blocks —
certified → adopt (`Link` carrying `REFMET:<name>` as the shared key), refuted → reject, refused → hold.
It returns a `BridgeResult` whose `combined_links = curie_links + bridge_certified`. This is the direct
production port of the validated `certified_bridge_links`; the signature stays pure (consumes
already-resolved maps: `{name: curie_set}`, `{name: refmet_std_name}`, `{name: independent_block}`).

**Node-level analogue, for orientation (unchanged here).** The disagreement case the task describes —
"a committed node's structure disagrees with the query's INDEPENDENT structure" — is the node
re-resolution already in `Resolver.reresolve_on_contradiction` (anchor = `query_independent_inchikey`,
committed node excluded from the match, ambiguous/no-match → refuse; L2/KTD5). D2 is its sibling for the
**missed-link** case and shares the certificate seam with it.

## Non-circularity guarantee (preserves R6)

The certificate is trustworthy only if it carries information the link formation did not already imply. Two
structural invariants, each mapped to an existing ledger constraint:

- **The re-link key is a NAME, never a structure.** The bridge joins on the RefMet standardized name
  string — a fuzzy-normalized label, not a structure hash and not a KG CURIE. The identifier-only linker
  (`link_by_intersection`) is untouched and still excludes `INCHIKEY`/`INCHI`/`SMILES` (R6). Adding the
  bridge does not make the linker structural.
- **The validating structure is KG-independent on both sides.** The verdict reads only each side's
  `independent_inchikey_block` (PubChem / LIPID MAPS / MW-by-name / repaired gold), **never** the
  conflated node's own `kg_equivalent_ids["INCHIKEY"]` (R6a). A shared KG node therefore cannot
  mechanically manufacture a certified bridge — the Deliverable-1 "reads KRAKEN's own InChIKey first"
  failure is structurally impossible here. A side with no independent structure is **refused**
  (counts-only), never certified off the KG (R6b).
- **`block1 + block2[:8]`, degrade honestly.** Verdicts come from `structural_agree`: connectivity on
  block1, stereo on block2[:8] only when both sides carry it; a first-block-only side degrades to
  connectivity-only and is recorded as such (`stereo_checked=False`), never a silent stereo pass. This is
  the same seam the benchmark scorers and the node re-resolver use.
- **Enforced by test.** `tests/test_refmet_bridge.py` asserts (a) a bridge never adopts when either
  side's independent block is absent, (b) the bridge input for the "already linked?" test is the
  identifier-only CURIE set (structure namespaces excluded), and (c) no code path passes a node's own
  `kg_equivalent_ids["INCHIKEY"]` as a certificate operand.

## Requirements / units

- **U1 — src certificate verdict.** Add `certify_link(a_key, b_key) -> LinkCertificate` (certified /
  refuted / refused, `stereo_checked`) to `src/biomapper2/core/certificate.py`, built on the existing
  `structural_key_parts` / `structural_agree`. Faithful port of `studies/.../link_certificate.certify_link`.
- **U2 — src identifier-only CURIE set + intersection linker.** Port `curie_set` (structure-namespace
  stripped) and a minimal `link_by_intersection` / `Link` into `src/biomapper2/core/cohort_linker.py`
  (or reuse an existing linker helper if one already covers it). Identifier-only; R6-preserving.
- **U3 — src bridge.** `src/biomapper2/core/refmet_bridge.py::certified_bridge_links` + `BridgeResult` —
  the pure port. Adopts certified, rejects refuted, holds refused, never double-counts a CURIE-linked
  pair.
- **U4 — RefMet standardized name surfaced as output (dependency, see Risks).** The MW annotator today
  keeps only `refmet_id` (`src/biomapper2/core/annotators/metabolomics_workbench.py`); the `/match`
  payload also carries the standardized `refmet_name`. Surface it as a per-entity output field so the
  bridge has a join key. Without this, the bridge has no key and is a no-op.
- **U5 — frontier independent-structure population.** The bridge needs
  `independent_inchikey_block` on the **no-CURIE-link** population. Wire a gated pass that resolves the
  independent structure for frontier entities via the existing Tier B / `LipidStructureResolver` seam,
  reusing the structure HTTP cache. Operator cost decision (rate-limited lookups), default-off.
- **U6 — wiring + flag.** New default-off flag `BIOMAPPER2_REFMET_BRIDGE_ENABLED` in
  `src/biomapper2/config.py` (mirror `RERESOLUTION_ENABLED`). A cross-cohort harmonization entry point
  invokes `certified_bridge_links` behind the flag and emits per-link verdicts.
- **U7 — gate-arm extension (studies).** Extend `studies/external_benchmarks/conflation_gate.py` arm
  construction to score a **link-adding** treatment (baseline links vs baseline + certified bridge
  links), so refuted-regression / over-correction / RefMet-parity guards apply to the bridge.

## Context & Research

- **Prototype (source of truth):** `studies/external_benchmarks/scorers/refmet_bridge.py`,
  `studies/external_benchmarks/refmet_bridge_prototype.py`,
  `studies/external_benchmarks/tests/test_refmet_bridge.py`. All on branch
  `feat/monti-biomapper-refmet-bridge`.
- **Certificate seam to reuse:** `src/biomapper2/core/certificate.py`
  (`structural_key_parts`, `structural_agree`, `STRUCTURAL_KEY_BLOCK2_LEN`, `ResolutionCertificate.independent_inchikey_block`).
- **Node re-resolution foundation (dependency):** `src/biomapper2/core/resolver.py::reresolve_on_contradiction`,
  `src/biomapper2/mapper.py::_certify_and_reresolve`, `src/biomapper2/config.py::RERESOLUTION_ENABLED`.
- **Independent-structure hops:** `src/biomapper2/core/tier_b.py`,
  `src/biomapper2/core/lipid_structure_resolver.py`, `src/biomapper2/core/structure_resolver.py`.
- **R6 constraint (studies, non-negotiable):** `studies/external_benchmarks/scorers/cross_cohort_overlap.py`
  (`_STRUCTURAL_NAMESPACES`, `curie_set`, `link_by_intersection`, `stability_descriptor_set` warning).
- **Gate:** `studies/external_benchmarks/conflation_gate.py`,
  `studies/external_benchmarks/run_conflation_gate_live.py`,
  `studies/external_benchmarks/tests/test_conflation_gate_*.py`.
- **Tooling:** `pyproject.toml` — black/ruff line-length 120; pyright gates `src/` + `tests/`, excludes
  `studies/**`. `CLAUDE.md` — `uv run` for all commands.

## Implementation phases

### Phase 0 — dependencies (blocking; no code here)

- **Confirm fork #60/#61 promoted to org first.** D2 reuses the certificate independent-structure seam,
  `LipidStructureResolver`, and the `reresolve_on_contradiction` foundation those PRs introduced.
  Promotion order: fork #60/#61 → org, **then** D2. Do not open the org D2 PR before #60/#61 lands in the
  Phenome-Health org.
- **Decide U4 (RefMet standardized name output).** Confirm whether the standardized name is surfaced now
  (small MW-annotator change) or D2 is scoped to consume a name map supplied by the caller. Flag to Trent;
  do not infer.

### Phase 1 — pure src port (TDD, offline)

Files added under `src/` (all pyright-clean, black/ruff 120):
- `src/biomapper2/core/certificate.py` — **edit**: add `LinkCertificate` + `certify_link`.
- `src/biomapper2/core/cohort_linker.py` — **new**: `Link`, identifier-only `curie_set`,
  `link_by_intersection` (ported from studies `cross_cohort_overlap`, R6-preserving).
- `src/biomapper2/core/refmet_bridge.py` — **new**: `BridgeResult`, `certified_bridge_links`.

Tests (gated `tests/`, ≤8 tests/file, network monkeypatched — these are pure so no network is touched):
- `tests/test_refmet_bridge.py` — enumerated scenarios (mirrors `studies/.../tests/test_refmet_bridge.py`):
  1. **certified → adopt** — shared RefMet name, agreeing independent blocks ⇒ pair in `bridge_certified`,
     `combined_links == curie_links + bridge_certified`.
  2. **refuted → reject** — shared RefMet name, block-1 (or block2[:8]) disagree ⇒ pair in
     `bridge_refuted`, `bridge_certified == ()`.
  3. **refused → hold** — shared RefMet name, one side's independent block absent ⇒ pair in
     `bridge_refused`, not adopted.
  4. **no RefMet → no-op** — empty standardized name on a side ⇒ no bridge of any kind.
  5. **already CURIE-linked → no double count** — pair shares a CURIE; bridge must not re-add it;
     `len(curie_links) == 1`, `bridge_certified == ()`.
  6. **non-circularity guard** — a pair that shares only a KG-node InChIKey (never passed to the verdict)
     is NOT certified; asserts the verdict is called only with `independent_inchikey_block` operands.
  7. **combined = curie + certified** — one CURIE link + one certified bridge ⇒ both in `combined_links`.
- `tests/test_certificate_certify_link.py` — ≤8: certified (block1 match, stereo match / first-block-only
  degrade), refuted (connectivity differs; stereo differs when both present), refused (either side None).

### Phase 2 — wiring (offline, gated by flag)

- `src/biomapper2/config.py` — **edit**: add `REFMET_BRIDGE_ENABLED` (env `BIOMAPPER2_REFMET_BRIDGE_ENABLED`,
  default False), plus a test asserting the default is False (mirrors the `TIER_B_ENABLED` assertion).
- Cross-cohort harmonization entry point — **edit/new**: invoke `certified_bridge_links` behind the flag,
  supplying the identifier-only CURIE maps, the RefMet standardized-name map (U4), and the frontier
  independent-structure map (U5); emit per-link verdicts (certified/refuted/refused) alongside CURIE links.
- `src/biomapper2/core/annotators/metabolomics_workbench.py` — **edit (if U4 accepted)**: keep the
  standardized `refmet_name` from the `/match` payload and surface it.
- Tests: `tests/test_refmet_bridge_wiring.py` — ≤8, network monkeypatched: flag-off ⇒ exact baseline
  (byte-identical links, no bridge, no frontier lookups fired); flag-on ⇒ certified bridges added,
  refused/refuted counted, independent-structure lookups scoped to the frontier population only.

### Phase 3 — gate arm + live run (operator step, persists by default)

- `studies/external_benchmarks/conflation_gate.py` — **edit**: extend arm construction so the treatment
  is "baseline + certified bridge links" (a link-adding arm), keeping the existing guards
  (refuted-regression per-link FAIL, over-correction bound, RefMet parity, noise floor, cold-cache canary,
  positive control). Tests: extend `studies/external_benchmarks/tests/test_conflation_gate_*.py`.
- Live run via `studies/external_benchmarks/run_conflation_gate_live.py` — supervised, persists
  `prereg.json` then `result.json` to a timestamped path by default (R23); pins deployed commit,
  `/metagraph` fingerprint, ChEBI release, cold-cache canary.

### Phase 4 — fork-first PR flow

- Open on the personal fork **trentleslie/biomapper2**, base **dev**, so Greptile reviews first.
- Run the `greptile-loop` skill to closure (5/5 or zero un-addressed comments; report `no-review` /
  `unavailable` / `exhausted` out loud).
- Only after the gate PASSes and the fork PR is green, open the org **Phenome-Health** PR — **after**
  fork #60/#61 has already been promoted to org.

## The gate this must clear (falsifiable; a STOP is acceptable)

Before any prod promotion, the change must clear the conflation benchmark gate
(`studies/external_benchmarks/conflation_gate.py` + `run_conflation_gate_live.py`), scored on the
KG-independent certificate (`CertifiedOverlap`), never on the KG's own InChIKey. Pass conditions,
pre-registered before the arms are observed:

- **Refuted false-positive links → 0.** The bridge must import zero un-certified links (per-link
  refuted-regression FAIL fires even if the aggregate stays within the floor — the anti-pooling guard).
- **Refused fraction ↓ or unchanged.** The bridge should convert frontier/refused pairs to certified,
  not manufacture new refusals.
- **Certified links NOT reduced (no over-correction).** As a link-adding treatment the bridge must never
  drop a baseline certified link.
- **Positive control** must produce its pre-registered FAIL/ABSTAIN on the known-bad arm, or the gate is
  invalid (ABORT).
- **Noise floor** (≥3 replicates) — a gain smaller than run-to-run jitter is NOOP, not a win.
- **Cold-cache canary** — a warm/re-served KG cache reading is refused.

**A no-op or net-negative is an acceptable STOP.** If the gate returns NOOP / FAIL / ABSTAIN, do not
promote; record the result artifact and stop. The prototype's +5/5-with-zero-error result is the target,
not a guarantee the production population reproduces it.

## Sequencing summary

1. **Phase 0** — fork #60/#61 promoted to org; U4 decision confirmed (blocking).
2. **Phase 1** — pure src port + tests, offline, TDD.
3. **Phase 2** — flag + wiring, offline, flag-off is exact baseline.
4. **Phase 3** — gate-arm extension + one supervised live gate run (persists by default). **STOP if
   NOOP/FAIL/ABSTAIN.**
5. **Phase 4** — fork trentleslie/biomapper2 (base dev) → Greptile loop → then Phenome-Health org PR
   (only after #60/#61 is in org and the gate PASSes).

## Constraints

- All commands via `uv run` (e.g. `uv run pytest tests/test_refmet_bridge.py`, `uv run ruff`,
  `uv run black`, `uv run pyright`).
- black + ruff line-length **120**; pyright gates `src/` **and** `tests/` (studies/** excluded — so the
  port must be pyright-clean once in `src/`, which the studies prototype was not required to be).
- **≤8 tests per file.**
- **Monkeypatch the network in every test** (the pure bridge touches none; the wiring/frontier-lookup
  tests must patch Tier B / `LipidStructureResolver` / structure HTTP).
- **Persist runs by default** — the live gate writes `prereg.json` + `result.json` to a timestamped path
  with pinned commit / `/metagraph` fingerprint / ChEBI release; `--out` is an override, never the only
  way to save.

## Risks & open questions

- **U4 is a real gap, not a detail.** Production does not currently emit a RefMet standardized name
  (`metabolomics_workbench.py` keeps only `refmet_id`). If it is not surfaced, the bridge has no join key
  and is a silent no-op. Confirm the source of the standardized name before Phase 1 completes. (Keying on
  the RefMet **CURIE** instead would defeat the purpose: a shared RefMet CURIE is already an
  identifier-set member and the linker would have caught it.)
- **U5 cost.** Enabling the bridge implies independent-structure lookups on the no-CURIE-link frontier —
  rate-limited external calls, an operator decision. Scope strictly to the frontier population; reuse the
  never-expiring structure HTTP cache.
- **Architectural placement.** The bridge is inherently cross-cohort and does not fit inside single-entity
  `resolve`; it is a pure harmonization function invoked by a cross-cohort entry point. Confirm that entry
  point exists / where it should live before Phase 2 (surface to Trent; do not infer a decision).
- **Gate scores switching today, not adding.** Phase 3's arm extension is required, or the gate cannot
  score a link-adding treatment. Land it with tests before the live run.
