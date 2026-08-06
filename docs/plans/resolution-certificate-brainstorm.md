# Resolution certificate — brainstorm artifact

Axis: `certificate` · Project: BioMapper preprint (biomapper2) · Date: 2026-08-05
Branch: `feat/resolution-certificate` (off `dev`; queued behind PR #47 `fix/resolver-category-acceptance`)
Baseline: `~/benchmark-runs/suite_20260805T033340Z/` (`kg_stable_during_run: true`)

**Every number below regenerates offline, with no network access, from**
`studies/analysis/certificate_state_audit.py` **over the pinned suite. Artifact:**
`studies/analysis/results/certificate_state_audit_suite_20260805T033340Z.{json,md}`.

---

## Problem

The preprint claims a structural certificate is issued for a name-input metabolite resolution, with
refusal when one cannot be issued. That claim is not true of the code.

`Resolver._choose_best_kg_id` (`src/biomapper2/core/resolver.py:119-139`) computes a structural
verdict and discards it. What escapes is `chosen_kg_id` plus `chosen_kg_id_review`, a flag string.
Three defects, all verified:

1. **The test barely runs.** It fires only when the category is `biolink:SmallMolecule` AND RefMet
   voted AND RefMet disagrees with the majority. On the NECS baseline the flag is set on 214 of
   1,488 committed rows; the other 1,274 were accepted on an unchecked vote.
2. **`chosen_kg_id_review = None` is overloaded** across four states, including "structure confirmed
   identical". The one case where the machinery ran and passed is indistinguishable from never
   having looked.
3. **It is not independent of the KG.** `StructureResolver.inchikey_block` reads the graph's own
   `equivalent_ids["INCHIKEY"]` first; MW and PubChem are a fallback only when the node carries no
   key. On NECS, 1,055 of 1,488 committed nodes carry a KG InChIKey, so the common path never
   leaves the graph. (The metLinkR benchmark arm's independence came from PubChem PUG-REST and is a
   different mechanism — keep them distinct.)

---

## What the evidence actually supports — and the claim it kills

### Finding 1 — Tier A is already emitted, just not named

The chosen node's InChIKey is **already in every output today**, inside `kg_equivalent_ids` under
the `INCHIKEY` prefix (`mapper.py:126-128` calls `get_equivalent_ids`, which returns all prefixes).
So the Tier-A self-certificate needs no new lookup and no new pipeline run. Its value is not the
data — it is making the status a **schema-level contract** instead of a property a consumer must
infer by introspecting a nested dict.

`structure_absent` share of committed rows: necs 29.1%, refmet 6.9%, srm1950 49.1%, lmsd 65.4%,
metlinkr 31.7% (all five vocabulary arms).

### Finding 2 — the split is large

Precision within Tier-A state, structure oracle (gold InChIKey block ∈ node's block set):

| dataset | blended | `structure_present` (coverage) | precision within present |
|---|---|---|---|
| necs | 83.5% | 90.2% | 92.6% |
| refmet | 89.3% | 93.1% | 96.0% |
| srm1950 | 42.7% | 50.5% | 84.7% |
| lmsd | 14.3% | 34.6% | 41.4% |

### Finding 3 — THE CONFOUND, and it changes the design

`structure_absent` scored **0.0% precision on all four datasets**. That is the headline the input
slice's framing invites, and **it is not admissible.**

- Under the structure oracle it is tautological: a node with no InChIKey can never match a gold
  InChIKey, by construction.
- A second, fully non-structural oracle was added to escape that — gold HMDB/KEGG/PubChem
  identifier ∈ the node's `kg_equivalent_ids`. It still returned 0/135 on NECS.
- **The sparsity control shows why, and it is decisive.** Of the 135 NECS `structure_absent` rows
  the identifier oracle could nominally score, the number carrying *any* of HMDB / KEGG / PubChem
  is **zero**. The oracle never had a chance to fire. Field: `sparsity_control.n_absent_oracle_could_fire`,
  which is 0 on every dataset (srm1950: 0 after quarantine, see Finding 4).

**Therefore:** `structure_absent` does not identify *wrong* answers. It identifies **unverifiable**
ones — nodes carrying no cross-reference into any structure-bearing vocabulary, which no available
oracle can confirm or refute. That is the `unavailable` certificate state, not `contradicted`.

This is the single most important design input on the axis. Claiming "refusing `structure_absent`
buys +9 to +42 points of precision" would have been confidently wrong in exactly the way that is
hardest to catch: the number is real, reproducible, and means something other than it appears to.

### Finding 4 — a benchmark data defect found on the way

`srm1950`'s `gold_hmdb` column is a strictly monotonic, fully-unique sequential counter
(`HMDB0000001`, `HMDB0000002`, … in file order) — a row index wearing an accession's clothes, not a
curated mapping. Scoring against it yields a 0.1% precision that reads as catastrophic resolver
failure and is an input defect. The audit now detects this generically (uniqueness + monotonicity)
and reports it in `quarantined_gold_columns` rather than special-casing srm1950. **This belongs to
whichever axis owns the benchmark gold sets; it is filed here, not fixed here.**

### Finding 5 — the two existing flags have opposite information content

NECS, both oracles agree in direction:

| flag | n | correct (structure oracle) | correct (identifier oracle) | share of flag that is `structure_absent` |
|---|---|---|---|---|
| `conflict_no_structure` | 84 | 0 / 45 scored | 0 / 60 scored | 75 / 84 |
| `divergent_refmet` | 130 | 74 / 85 scored | 85 / 115 scored | 13 / 130 |
| `no_flag` | 1,274 | 591 / 666 scored | 667 / 806 scored | 345 / 1,274 |

`conflict_no_structure` is very largely the `structure_absent` population under another name —
Tier A subsumes it. `divergent_refmet` is a genuine, *independent* weak-negative signal (below the
`structure_present` baseline under both oracles). They are currently emitted through one channel as
if they meant the same thing. **The certificate must separate them.**

---

## Design

### Certificate states

| state | meaning | issued when |
|---|---|---|
| `corroborated` | an independent structure agrees with the committed node | Tier B lookup resolves and matches |
| `contradicted` | an independent structure disagrees | Tier B lookup resolves and does not match |
| `uncorroborated` | node has a structure; nothing independent checked it | Tier A only, `structure_present` |
| `unavailable` | no structure could be obtained for the node at all | Tier A, `structure_absent` |

`unavailable` is the honest home of the whole `structure_absent` population per Finding 3. It is a
**declared abstention**, not a claim of error.

### Tier A — self-certificate (no new I/O)

Emit, on every small-molecule mapping: the committed node's InChIKey block set, a
`structure_present`/`structure_absent` status, and the state above. Free: the data is already
fetched at `mapper.py:126-128`.

### Tier B — independent certificate (one external call)

Resolve the **query name** through Metabolomics Workbench → PubChem and compare against the
committed node's KG InChIKey. `StructureResolver._fetch_mw_inchikey(name)` and
`_fetch_pubchem_inchikey(name)` already take a name; today they are only ever called with the
**node's** name as a fallback. Calling them with the *query* name is what makes independence real,
and is what differentiates this from UniChem, which needs a registered identifier or a structure and
cannot start from a name.

### Refusal as a first-class state

Two distinct overloaded `None`s exist and must not be merged carelessly:

- `chosen_kg_id_review = None` — four states (this axis).
- `chosen_kg_id = None` — "nothing matched" vs, after PR #47, "an off-category node was refused".
  PR #47's own follow-up list item (c) files exactly this: *"refusal reason surfaced in
  `AssignedIDsDict` so the scorer can distinguish refusal from no-match."* **That follow-up is this
  axis's territory** and must be claimed explicitly rather than implemented twice.

---

## Open decisions

Carried to CP1 — see the checkpoint payload. In short: certificate schema shape; whether Tier A
`unavailable` withholds the answer or merely labels it; whether Tier B is default-on; how the new
certificate relates to `chosen_kg_id_review` and to #47's annotator-level refusal; and how the
certificate records which structure-comparison rule produced it (D3 will change that rule).

---

## Risks

| risk | mitigation |
|---|---|
| **Restating Finding 3 as an accuracy claim.** The most likely failure of this axis is publishing "structure_absent is 0% accurate". | The audit emits `sparsity_control` next to every precision number; the plan must gate on it. Any prose claim about the absent bucket is inadmissible while `n_absent_oracle_could_fire` is 0. |
| **Cache confound at scale.** Every external dependency is served from persistent `requests_cache` (Kestrel 1h incl. POST, MW 7d, structure resolver never expires). A prior determinism run had two processes disagreeing on identical queries; a cold cache returned `LOINC:45207-8` for glutarylcarnitine. Tier B default-on recreates this at larger scale. | Cache state must be recorded in certificate provenance (hit/miss, store path, whether the entry pre-existed the run). Non-negotiable if Tier B is default-on. |
| **External lookups are fallible.** PubChem name lookup returned 4-acetyloxyphenolate for 4-hydroxyphenylacetate. | `contradicted` must be defined as "a human should look", never "the resolver is wrong". Wording matters in the schema description, not just the docs. |
| **D3 changes the comparison rule underneath the certificate.** L5 defers block1+block2 tightening to a separate PR. Certificates issued before and after are not comparable. | Certificate carries the comparison-rule identifier. Coordinate on `structure-comparison-semantics`; do not implement D3 here. |
| **Collision with PR #47** on `resolver.py` / `structure_resolver.py`. | Branch is off `dev`; rebase on #47 when it merges. #47's `connectivity_match` set-intersection change is a dependency, not a duplicate — build on it. |
| Backend config: `config.py:21` still defaults to the internal host; `KESTREL_API_URL=https://kestrel.krakenkg.com/api` is keyless but still needs a placeholder `KESTREL_API_KEY`. | Pin in the run manifest alongside cache state. |

---

## Non-goals

- **No D3.** Tighten-only, separate PR, per ledger L5.
- **No change to which node is committed.** The certificate describes the answer; it does not
  re-rank. (Whether `unavailable` withholds the answer is an open decision, and the recommendation
  is that it does not.)
- **No namespace whitelist, no pool filter.** Ledger L11 stands.
- **No accuracy claim about the `structure_absent` bucket** until an oracle exists that can score it.
