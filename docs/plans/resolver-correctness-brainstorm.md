# Resolver correctness — brainstorm artifact

Axis: `resolver-correctness` · Project: BioMapper preprint (biomapper2) · Date: 2026-08-05
Baseline: `~/benchmark-runs/suite_20260805T033340Z/` (kraken 2.0.1 `14683250n/92233909e`, biolink 4.2.5, git_sha d059564, `kg_stable_during_run: true`, backend `https://kestrel.krakenkg.com/api`)

## Problem

Three verified defects in the resolution path. All file references are `src/biomapper2/...`
(the input slice used a `core/...` prefix; the package lives under `src/`).

### D1 — Category enforcement is absent (highest value)

All three Kestrel annotators send `category_filter` in the request body
(`kestrel_hybrid.py:229`, `kestrel_text.py:96`, `kestrel_vector.py:95`) and the server ignores it.

Verified live against `https://kestrel.krakenkg.com/api/hybrid-search` with
`category_filter: biolink:SmallMolecule`:

| query | top row | categories |
|---|---|---|
| `glutarylcarnitine (c5-dc)` | `EFO:0800030` glutarylcarnitine (C5-DC) measurement | `['biolink:PhenotypicFeature']` |
| `1-palmitoyl-2-oleoyl-GPC (16:0/18:1)` | `EFO:0800612` …measurement | `['biolink:PhenotypicFeature']` |
| `choline` | `CHEBI:23217` cholines | `['biolink:ChemicalEntity']` |

Also returned for those queries: `biolink:Protein` (UMLS), `biolink:Polypeptide` (NCIT),
`biolink:MolecularActivity` (GO), `biolink:Pathway` (PathWhiz), `HP:`, `UNII:`.

`_kestrel_hybrid_search` (`kestrel_hybrid.py:232`) filters candidates on **score only**.
Every candidate row already carries `categories`, so filtering is free — no extra network call.

The canonical-namespace policy at `_select_canonical` (`kestrel_hybrid.py:201`) filters on the
CURIE **prefix** (CHEBI/HMDB/RM), not category. When that pool is empty it falls back to the
honest overall top-1 (`:203`) — which is how a `biolink:PhenotypicFeature` measurement node
becomes the committed answer.

**Impact, two independent measurements — both stand, they count different things:**

1. *Failing names* (from the run log): 2,053 structure-lookup failures over 1,529 distinct
   names, of which **148 end in the literal word "measurement"**
   (e.g. `1-oleoyl-GPC (18:1) measurement`). Coincidentally 148 also happens to be the number
   of `.tsv` files in the run directory; verified independent.
2. *Committed wrong-category IDs* (recomputed from `*_d_mapped.tsv` `chosen_kg_id`) — **the
   metric of record**, because it counts what the resolver actually committed to:

   | dataset | n | suspect | % | top prefixes |
   |---|---|---|---|---|
   | metlinkr | 7060 | **980** | **13.9%** | CHEBI 4970, RM 660, **EFO 625**, UMLS 285, **NCBIGene 205** |
   | necs | 1488 | 82 | 5.5% | CHEBI 1120, RM 247, EFO 61, UNII 14 |
   | refmet | 1500 | 14 | 0.9% | RM 848, CHEBI 573 |
   | srm1950 | 1058 | 6 | 0.6% | RM 574, CHEBI 457 |
   | lmsd | 1499 | 1 | 0.1% | RM 1025, CHEBI 375 |
   | **hgnc** | 4476 | **0** | **0.0%** | NCBIGene 4359, HGNC 108 |

   Total **1,083** suspect commits on metabolite datasets. Note **205 `NCBIGene` IDs assigned as
   metabolites** in metLinkR — a category error the input slice did not mention.

3. *Off-category commits* — **superseded metric 2 during review and is the one to publish**,
   because it is category-based like the intervention rather than prefix-based. Definition:
   a row is off-category iff its committed node's Biolink `categories` (resolved via keyless
   Kestrel `/get-nodes`) has empty intersection with `descendants(biolink:ChemicalEntity)`.
   All 6,225 distinct committed nodes resolved, 0 unresolved:
   metlinkr **1080/7060 (15.3%)**, necs 65/1488, refmet **0**, srm1950 3/1058, lmsd **0** —
   metabolite total **1,148 / 12,605 (9.1%)**; hgnc 4197/4476 (93.8%, the positive control
   proving the gene path must stay unfiltered). Composition: PhenotypicFeature 692,
   Gene+Protein 202, Protein 160, InformationContentEntity 35, rest <10 each.
   It is a **type-consistency** metric, not accuracy: refmet's 14 prefix-suspects are 0
   off-category (all correctly-typed UNII/NCIT), and `XL-VLDL-P → KEGG.GLYCAN:G11365` is
   on-category and still nonsense.

   HGNC's clean 0/4476 is the empirical licence to scope the fix to the chemical branch: the
   gene path has nothing to gain and everything to lose.

### D2 — the `keys[0]` fix never reached production

`structure_resolver.py:43-60` `inchikey_block` returns only `keys[0]` of a multi-valued
`INCHIKEY` list. Its sibling `inchikey_blocks` (`:62`) exists precisely because the list is
multi-valued (neutral parent, conjugate anion, salt, stereoisomers) — but `connectivity_match`
(`:37-38`) calls the **singular** one.

Caller census: `inchikey_blocks` is used ONLY by `studies/external_benchmarks/oracle.py:44`.
So PR #36's multi-valued fix landed in the benchmark scorer and not in the resolver, and the
benchmark now scores the resolver more generously than the resolver judges itself.

### D3 — first-block comparison (split to a follow-up PR, per L4)

`structure_resolver.py:41` compares `block_a == block_b`. Re-verified against PubChem; **the
input slice's two examples were mis-assigned and the corrected reading changes the fix**:

| compound | CID | InChIKey | formula |
|---|---|---|---|
| D-xylose | 135191 | `SRBFZHDQGSBBOR-IOVATXLUSA-N` | C5H10O5 |
| beta-D-arabinopyranose | 444173 | `SRBFZHDQGSBBOR-SQOUGZDYSA-N` | C5H10O5 |
| choline (neutral/zwitterion) | 170746 | `CRBHXDCYXIISFC-UHFFFAOYSA-N` | C5H13NO |
| choline cation | 305 | `OEYIOHPDSNJKLS-UHFFFAOYSA-N` | C5H14NO+ |

- The xylose/arabinopyranose pair are **stereoisomers** (same block 1, different block 2, same
  formula, both `oxane-2,3,4,5-tetrol` differing only in R/S) — not ring-chain tautomers. This
  is the **silent-accept** direction: current code returns `True`.
- Choline neutral vs cation have **different block 1**, so block 1 is **not** protonation
  invariant. This is the **over-flag** direction, and it needs charge normalisation (a network
  dependency) to fix — a research task, not a defect fix.

Crucially, in `resolver.py:135-139` both the `True` and `False` branches select the **RefMet
node**; only the review flag differs. D3 therefore moves flag volume, never a committed ID.
Per L5: tighten only (block1+block2), in the follow-up PR.

### D4 (minor, same neighbourhood) — `refmet_nodes[0]`

`resolver.py:129,133` takes `refmet_nodes[0]`; order-dependent when RefMet returns >1 node.

## Design

Confirmed enablers:

- `category` is **already** a parameter on every `BaseAnnotator` method. No new plumbing for it.
- Candidate `categories` is a short **leaf list**, not an ancestor closure
  (`['biolink:Drug','biolink:SmallMolecule']`). So the test is "any listed category is accepted".
- `descendants(biolink:ChemicalEntity)` = exactly **12** categories: ChemicalEntity,
  ChemicalMixture, ComplexMolecularMixture, Drug, EnvironmentalFoodContaminant, Food,
  FoodAdditive, MolecularEntity, MolecularMixture, NucleicAcidEntity, ProcessedMaterial,
  SmallMolecule. This cleanly **accepts** the `biolink:ChemicalEntity`-typed `UNII:LYJ3482CB6`
  case and `MolecularMixture` CHEBI nodes, and **rejects** PhenotypicFeature, Protein,
  Polypeptide, Disease, Pathway, MolecularActivity. Exactly the requested semantics, from one root.
- Generic ancestor-walking was rejected on evidence: `parent(SmallMolecule) = MolecularEntity`,
  and `descendants(MolecularEntity)` **excludes** `biolink:ChemicalEntity`, so "one level up"
  would drop the UNII case we were told to keep.
- `bmt.Toolkit()` inits in **0.6 s**; the ~17-minute cost is `BiolinkClient` fetching the pinned
  4.2.5 schema over the network. Reusing the engine-owned client is still right — for that reason.

Decisions (ledger L4–L7), all following the existing `preferred_prefixes` seam:

- Engine computes `accepted_categories` from a new `CATEGORY_ACCEPTED_ROOTS` config map via
  `biolink_client.get_descendants()` in a `cached_property` next to `_category_preferred_prefixes`,
  and threads it through `get_annotations` / `get_annotations_bulk` exactly as
  `preferred_prefixes` is threaded today. No annotator constructor change; the registry stays arg-free.
- Seed the map with `biolink:SmallMolecule -> biolink:ChemicalEntity` only. Unmapped categories
  keep today's unfiltered behaviour, so the gene path is untouched.
- **Failure-open**: a candidate with an empty/missing `categories` list is kept, guarding against
  KRAKEN typing gaps.
- Empty in-category pool ⇒ **refuse** (return no annotation) and log `no_in_category_candidate`.
  Log-only in this PR; one throwaway instrumented run quantifies refusals for the A/B.

## Non-goals

- No score increase. The wrong-category commits were already scored as misses; the win is
  removing confidently-wrong output. A flat A/B is a pass.
- No change to `_select_canonical`'s prefix policy, no score-margin guard, no gene-path change.
- No charge/tautomer normalisation (D3 loosening direction) — research task, out of scope.

## Risks

| risk | mitigation |
|---|---|
| **Over-filtering**: KRAKEN's typing is imperfect; a legitimate compound typed oddly gets dropped | Failure-open on empty `categories`; per-row correctness diff vs baseline is the gate; instrumented run lists every dropped candidate |
| Filter applied before the score cut changes which rows survive `limit` | Filter inside `_kestrel_hybrid_search` alongside the score cut, after the API returns; `limit` is already `HYBRID_SEARCH_LIMIT` when re-ranking is on |
| D2 makes `connectivity_match` more permissive ⇒ fewer `divergent_refmet` flags | Expected and correct; assert flag-count direction in the A/B rather than gating on it |
| KG drift between baseline and rerun | Confirm `kg_snapshot` string and `kg_stable_during_run` match the pinned manifest before comparing |
| NECS/metLinkR regression | Watched explicitly; metLinkR carries 980 of the 1,083 suspects so it is both the biggest win and the biggest risk |
