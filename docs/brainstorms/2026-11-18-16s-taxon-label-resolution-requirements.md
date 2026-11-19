---
date: 2026-11-18
topic: 16s-taxon-label-resolution
---

# 16S Taxon Label Resolution

## Problem Frame

Public users of BioMapper (biomapper2 engine, `biomapper` PyPI/MCP client) want to map 16S rRNA taxonomy tables to KRAKEN. The rows are labels written by classifiers: Greengenes 13_8, SILVA, RDP, MGnify, Greengenes2 or bare names. They are not identifiers. Today `entity_type="microbiome"` falls back to `biolink:NamedThing` and generic hybrid search.

The 2026-11-18 baseline ran 1,721 labels from 7 public sources (mockrobiota, HMP1 V1-V3/V3-V5, MicrobiomeHD, AGP, MGnify mouse). The run directory is `run_20261118T182527Z`, under the vault's 16s_probe datasets folder.

- Raw labels resolve acceptably 4% of the time. After a simple clean-up, 85%.
- 87 labels commit to UMLS/EFO/NCIT duplicate nodes instead of NCBITaxon.
- Search abstained on 1 of the 108 labels the truth set marks as having no NCBI node. That truth set is defective: 88 of the 108 are phylum, class or order labels, and several are real NCBI taxa (Actinobacteria class, Cyanobacteria, Deferribacteres, Gemellales, Kiritimatiellae, underscored `Candidatus_*` names). It must be re-adjudicated (R19) before any abstention number is quoted.
- 68 labels commit to eukaryote nodes. 17 of those are resolvable prokaryote labels hitting a homonym (e.g. *Proteus* the bacterium resolving to the salamander). The rest are no-node clone codes and organelle labels, about 36 and 15 respectively, both by the defective truth set.

A wrong-kingdom or wrong-family answer silently corrupts cross-study pooling. That is worse than no answer.

The draft implementation plan is `docs/plans/2026-11-18-001-feat-16s-taxon-label-resolution-plan.md`. Web and literature validation (2026-11-18, checked live against NCBI E-utilities) changed several of its rules. This document records the product decisions that supersede the draft.

## Requirements

**Input recognition**
- R1. `microbiome`, `microbe(s)`, `taxon`, `taxa`, `taxonomy`, `organism`, `bacteria`, `bacterium` and `16s` map to `biolink:OrganismTaxon`.
- R2. Accept every 16S label format seen in the baseline:
  - Greengenes / RDP `k__..g__`, with an optional `Root;`
  - SILVA `D_n__`
  - MGnify `sk__;k__;...`
  - Greengenes2 suffixed names
  - plain `;` lineages
  - bare names, handled per R12

  Truncate at genus and query the deepest named, non-placeholder rank. For lettered prefixes, take the rank from the letter. For SILVA `D_n__`, the index is depth, not rank. Use it only as a hint, confirm the rank by the name's rank in the snapshot, and drop padded repeats (a level repeating its parent's name).
- R3. Rank model follows NCBI's March 2025 change (cellular root, domain, kingdom). `sk__` is domain. `k__` is domain when no `sk__` is present (Greengenes, RDP), and kingdom when `sk__` is present (MGnify).

**Resolution behavior**
- R4. Target namespace is NCBITaxon only. Never commit a UMLS/EFO/NCIT duplicate node for a taxon row.
- R5. A name that matches exactly one NCBI prokaryote taxon at the label's rank, by scientific name or synonym, resolves to it as **exact**. This holds even when the label's own lineage disagrees with current NCBI; in that case the row carries a `lineage_drift` flag. For a same-rank name match, lineage is used to choose between multiple candidates and to enforce the prokaryote domain. A unique candidate is vetoed only by deep disagreement: when the label's named **phylum or class** resolves in NCBI and is not in the candidate's lineage, the match is treated as wrong and falls to R7 (parent walk) or abstention. Disagreement at order or family is accepted with `lineage_drift`. (R8 separately constrains *broad parent* commits.) The relation is `exact` whether the name matched as a scientific name or a synonym. The route records which (`exact` or `synonym`).
- R6. Legacy phylum names (Oren & Garrity 2021; e.g. "Firmicutes", which current NCBI holds as a synonym of kingdom Bacillati) resolve to the renamed **phylum** when the label puts them at phylum rank. They never resolve to the kingdom.
- R7. These label classes resolve to an NCBI taxon as **broad**:
  - suffixed or sensu-stricto genera (`Prevotella_9`, `Faecalibacterium_A_123`) → the base genus
  - merged genera (`Escherichia-Shigella`, `Escherichia/Shigella`) → their common ancestor
  - bracketed, incertae-sedis and informal names (`[Ruminococcus]`, `Ruminococcus2`, `Lachnospiracea_incertae_sedis`, clone codes) → the nearest ancestor *named in the label* that exists in NCBI
- R8. A broad parent must not contradict NCBI. If the label's parent name exists in NCBI but NCBI places the matched taxon elsewhere, prefer abstention over emitting a parent NCBI disagrees with.
- R9. Never commit a eukaryote or homonym node for a prokaryote label (e.g. *Bacillus* the stick insect, *Proteus* the salamander).
- R10. 16S labels with no defensible NCBI node abstain, returning no node and a stated reason. Under default annotator selection, generic search never runs for a 16S-format label, so it cannot override an abstention. A caller's explicit `annotators` list is honored as a power-user override, as it is for every other entity type. The docs and the row's route make clear the 16S guarantees do not apply then.
- R11. Host and organelle labels (eukaryote lineages, Chloroplast, mitochondria) abstain with reason `host_or_organelle`.
- R12. Bare names (no rank prefix, no `;` lineage) go **snapshot first**:
  - A name that is a prokaryote taxon in the snapshot (e.g. "Bacteroides") gets full 16S treatment (R5-R10): exact or broad, abstain, and no search.
  - A name absent from the snapshot ("Homo sapiens", "mouse", "E. coli" abbreviations) is delegated to hybrid search (route `delegated`). Its hit is rejected if it is a prokaryote/eukaryote homonym node (R9).
  - Bare-name rows, both prokaryote and non-prokaryote controls, are added to the benchmark so R17's zeros cover this path.

**Output and provenance**
- R13. Each taxon row reports:
  - a route:
    - `exact` and `synonym` (R5)
    - `superset`, `merged_lca` and `parent:<rank>` (R7, in its bullet order)
    - `delegated` (R12)
    - `link_miss` (R14)
    - an abstain reason: `no_ncbi_node`, `host_or_organelle`, `empty`
  - a mapping relation (`skos:exactMatch` / `skos:broadMatch`)
  - the `lineage_drift` flag (R5)
  - the NCBI taxonomy snapshot version that served it

  These fields are null on non-taxon rows. Non-taxon rows gain only these null-valued keys (as the ICD-10-CM fields did). Every existing field value and every certificate stays byte-identical.
- R14. *Taxon selection* is deterministic and offline at request time, against a pinned, versioned NCBI prokaryote taxonomy snapshot. Committing a node still needs KRAKEN canonicalization (a live call). When a snapshot-selected taxid has no KRAKEN node, the row reports route `link_miss` with no node, never a silent unresolved. The KRAKEN linkage rate is reported in the benchmark. A configured-but-missing snapshot fails loudly. The kill switch restores the generic hybrid annotator for OrganismTaxon; the R1 aliases and the NCBITaxon preference stay on.
- R15. (Moved to follow-up.) The `concept_drift` note for split genera (*Lactobacillus*, Zheng 2020) needs a curated split-genus list. See Scope Boundaries.

**Evaluation**
- R16. A public, pinned benchmark ships with the feature: the 1,721-label panel plus results saved by default with input hashes, git SHA and KG build.
- R17. Merge gate for PR2:
  - 0 eukaryote or homonym commits
  - 0 duplicate-node commits
  - ≥ 90% abstention on labels with no NCBI node, computed on the R19-corrected truth
  - an **independent stratum** whose 95% CI lower bound on acceptable rate is ≥ 90%. The stratum:
    - is about 120 rows: deliberately reorganized taxa (the Lactobacillus split, Clostridiales→Eubacteriales and Lachnospirales, GG2 suffixes, renamed phyla), type-strain names, and a random sample of labels the rules were not designed around
    - is **frozen before ladder code is written**
    - is adjudicated by someone blind to the rule each row exercises and to the system's answers
  - no regression below PR1 on the NCBI-derived panel truth

  The headline overall percentage is reported but not gated.
- R18. Abstentions are blind-audited as well as commits, so "abstained" is shown to be correct and not just safe.
- R19. Before any abstention or accuracy number is gated or quoted, re-adjudicate the panel truth's no-node rows. Any row whose deepest named rank has an NCBI node (by scientific name, synonym, the R6 rename, or with `_` normalized in `Candidatus_*` names) moves to resolvable. Recompute the baseline after the move.

**Delivery slicing**
- PR1, cheap and search-based:
  - R1, R2 (parser), R4 (NCBITaxon preference) and the cleaned-query annotator
  - a prokaryote filter on search hits, backed by the pinned NCBI snapshot (moved into PR1 during planning, because Kestrel rows carry no lineage), and abstention on placeholder or clone-code labels
  - R16 (benchmark harness), R19, and freezing the R17 stratum. The answers are **sealed** outside the repo (only their sha256 is committed) and revealed only at the PR2 gate. PR1 is not scored on the stratum.
- **Checkpoint after PR1, with a pre-stated rule.** If PR1 meets all four of these, PR2 shrinks to the output fields plus `link_miss` and the gate:
  - 0 eukaryote/homonym commits
  - 0 duplicate-node commits
  - ≥ 90% abstention on corrected no-node rows
  - ≥ 95% equivalence-set acceptable on the panel

  Otherwise PR2 is the full ladder. Trent confirms.
- PR2 (expected): R3, R5-R14 (ladder, guards, abstention, fields) and the R17 gate. "PR1" in R17 means PR1's code, re-run on the same KG build as PR2, within the measured noise tolerance.
- **Gate failure policy (pre-committed):** never re-adjudicate or rescore a frozen stratum. Fix the code and gate on a freshly drawn sealed stratum.

## Success Criteria
- A user can pass a raw 16S table to BioMapper and get, for each row, the right NCBITaxon node, a declared broad parent, or an explicit abstention with a reason. No wrong-kingdom and no duplicate-node answers.
- On the frozen independent stratum, the 95% CI lower bound on accuracy is ≥ 90%, with every safety zero held.
- The route and relation fields are enough for a downstream user to aggregate to a common rank without silently merging unrelated lineages.

## Scope Boundaries
- Prokaryote 16S labels only. Fungal ITS and eukaryote 18S resolution are out of scope: 16S-format eukaryote labels abstain (R11), and bare names follow R12.
- No GTDB or SILVA identifiers emitted, and no GTDB↔NCBI genome-level crosswalk.
- No species-level resolution from 16S labels; truncate at genus.
- No measurement provenance (primer, region, reference release) in this feature. That is a separate brainstorm.
- No KRAKEN changes. Asks for a rank attribute and duplicate-node cleanup are filed separately.
- Client repo surfacing (MCP `list_entity_types`, docs) is a follow-up PR.
- `concept_drift` for split genera (former R15) is a follow-up. It needs a curated split-genus list.
- Merged/stale KRAKEN taxid retry is a follow-up, unless the PR2 `link_miss` rate shows it matters.

## Key Decisions
- **Bare names: snapshot first, then search** (R12). A bare 16S genus keeps the 16S guarantees, and "Homo sapiens" still resolves.
- **PR2 is confirmed after PR1's numbers** (Delivery slicing). The adversarial review showed most eukaryote hits are clone codes and organelles a cheap filter may fix. Only 17 are homonyms.
- **The gate stratum is frozen before code, has about 120 rows with a random component, uses a blind adjudicator, and gates on the CI lower bound** (R17). A hand-picked 40-row stratum tested the rules against themselves, and 38/40 has a lower bound of only about 83%.
- **Lineage is a tiebreak and domain guard; only phylum/class disagreement vetoes** (R5). Under a veto, correct legacy genera like *Blautia* and *Dorea* (Greengenes `o__Clostridiales`, NCBI now Lachnospirales) would fail, and false parents would appear (*Faecalibacterium* placed in Ruminococcaceae when NCBI has Oscillospiraceae). Balvočiūtė & Huson 2017 (doi:10.1186/s12864-017-3501-4) map by name, rank and synonym, with nearest-ancestor fallback.
- **The deterministic ladder replaces generic search for 16S-format labels** (R10, R12). In the baseline, search abstained on 1 of 108 labels and produced 68 wrong-kingdom hits, 17 of them prokaryote homonyms. Determinism makes routes auditable.
- **Host and organelle labels abstain** (R11). This is standard 16S practice: those reads are contamination, not community members.
- **Gate on an independent stratum** (R17). The NCBI-derived panel truth shares rules with the ladder, so scoring well on it is partly by construction. It is used only to catch regressions.
- **Build our own snapshot from NCBI taxdump.** TaxonKit (MIT) checks it at build time and is not a runtime dependency. No existing tool resolves classifier labels end to end. ete3/ete4 is GPL-3. SILVA's NCBI mapping works per accession, not per name.

## Dependencies / Assumptions
- NCBI facts checked live on 2026-11-18:
  - *Blautia* (572511) sits under Lachnospirales.
  - "Firmicutes" is a Synonym of Bacillati (1783272). On Bacillota (1239) it appears only as lowercase GenbankCommonName/BlastName.
  - Two homonym pairs: *Bacillus* (1386/55087) and *Proteus* (583/210425).
- Unverified: whether mockrobiota's "expected taxonomy" strings were themselves made by Greengenes or SILVA classifiers. If they were, mockrobiota tests the parser, not the mapping, and cannot serve as independent truth.

## Outstanding Questions

### Resolve Before Planning
(none)

### Deferred to Planning
- [Affects R17][User decision, needed before the stratum is frozen in PR1] Who is the blind adjudicator for the ~120-row stratum? Options: a colleague, Trent given a sheet without rule tags or answers, or an isolated agent with LPSN/NCBI access whose output Trent spot-checks.
- [Affects R6][Needs research] Use a curated 42-phylum rename table, or allow rank-restricted GenbankCommonName matches? TaxonKit's behavior is a useful reference.
- [Affects R9][Technical] Derive the homonym list from taxdump (names shared by prokaryote and non-prokaryote nodes) and record its size.
- [Affects R8][Technical] Define "parent contradicts NCBI" precisely for informal labels, e.g. `Ruminococcus2` under `f__Lachnospiraceae`, where the parent is right but the bare genus name is wrong.
- [Affects R2][Technical] SILVA padded-repeat detection, and SILVA 138.x / 144 label conventions.
- [Affects R10, R11, R13][Technical] An abstention casts no vote, so no existing channel carries its reason from the annotator. Today only availability/source maps exist, and the ICD side-map starts in the linker. Planning must choose the annotation-stage side channel and how an abstained row appears in output (unresolved with a route, or a new status).
- [Affects R9, R12][Technical] The prokaryote-only snapshot cannot tell a eukaryote NCBITaxon hit from a legitimate non-prokaryote. Ship the homonym list (prokaryote names that also exist outside prokaryotes, from the full taxdump) next to the snapshot, so the bare-name guard has a data source.

## Next Steps
-> /ce:plan to revise `docs/plans/2026-11-18-001-feat-16s-taxon-label-resolution-plan.md` against this document.
