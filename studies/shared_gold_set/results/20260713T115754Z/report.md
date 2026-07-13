# Shared hard-case gold set — auto-labeling report

- Generated (UTC): `2026-07-13T11:58:03.893448+00:00`
- Git commit: `8acdc58fa33439db08f79a401f9e079094536bef`
- KG: `https://kestrel.nathanpricelab.com/api`
- Label: **inchikey_first_block_connectivity** (non-circular; independent of RefMet/BioMapper ID choice)
- Input SHA256 (disagreements): `af7162b374be781a…`

## Headline
- **Pairs:** 172
- **Auto-labeled (inchikey_auto):** 22 (13%)
- **Expert residual:** 150 (87%), which decomposes into:
  - **113 genuinely connectivity-ambiguous** — same 2-D skeleton, differ only by stereo/charge/positional/salt. This is the real ≥100-pair long-pole the plan warned about; first-block InChIKey *cannot* adjudicate it, so it is the true human-expert set.
  - **37 resolution-limited** — expert only because the query name did not resolve to a structure via MW/PubChem `/name` (mostly lipid shorthand / complex IUPAC). These are *recoverable* with a stronger query-structure source (provided InChIKey/SMILES), not genuine chemistry ambiguity.
- **Retrievable@200:** 11 (6%) (retrievable@200 from the chebi_filter probe arm; probe window n_candidates~50 is a conservative lower bound for @200).

The flagged *same-molecule variant* set is captured cleanly by the ambiguous bucket: **76/101** of those rows land in connectivity-ambiguous — confirming the plan's thesis that the stereo/charge/positional set is exactly what needs the human.

### Adjudication breakdown
| difficulty_flag | n | kind |
|---|---|---|
| ambiguous_shared_connectivity | 113 | genuine-ambiguous |
| query_unresolvable | 32 | resolution-limited |
| connectivity_match | 22 | auto |
| no_candidate_matches_query | 5 | resolution-limited |

### Expert residual by source category
| category | n |
|---|---|
| same-molecule variant (stereo/charge/acid-anion) | 97 |
| divergent (different compound) | 22 |
| multi-id (biomapper ambiguous set) | 16 |
| parent/child or substring (generic vs specific) | 15 |

### Consumer eligibility (auto rows only; expert rows await adjudication)
| track | n |
|---|---|
| tier1 | 22 |
| ablation | 11 |
| tbench | 11 |

## Independence demonstration (inter-method agreement)
Auto label = InChIKey first-block connectivity. Hand label = structure-from-nomenclature reasoning on a deterministic sample of 12 auto-labeled rows — a *different* signal. Agreement: **12/12** (100%). Full sample in `handcheck_sample.json`.

| query | auto_gold | hand_gold | agree | rationale |
|---|---|---|---|---|
| (15:3)-anacardic acid | CHEBI:174627 | CHEBI:174627 | ✓ | 2-OH-6-pentadecatrienyl-benzoate = anacardic C15:3; B nocardic acid is unrelated |
| 1-methylguanidine | CHEBI:16628 | CHEBI:16628 | ✓ | free-base methylguanidine; B is the HCl salt |
| 2-Methylmaleate | CHEBI:17626 | CHEBI:17626 | ✓ | citraconate = 2-methylmaleate; B 3-methylmalate differs |
| 2-hydroxypalmitate | CHEBI:65101 | CHEBI:65101 | ✓ | palmitate = C16:0; B palmitoleate is C16:1 |
| 3-hydroxymandelate | CHEBI:86553 | CHEBI:86553 | ✓ | meta-OH; B is the 4-OH para isomer |
| 3-methylhistidine | CHEBI:70959 | CHEBI:70959 | ✓ | exact name; B are N(pros)/N(tele) ring isomers |
| 4-acetamidophenol | CHEBI:46195 | CHEBI:46195 | ✓ | = paracetamol; B 2-acetamidophenol is the ortho isomer |
| 4-hydroxyhippurate | CHEBI:71018 | CHEBI:71018 | ✓ | para-OH; B is meta |
| 4-methylbenzenesulfonate | CHEBI:27849 | CHEBI:27849 | ✓ | = p-toluenesulfonate; B 4-formyl differs |
| 4-methylcatechol sulfate | CHEBI:232803 | CHEBI:232803 | ✓ | generic name match; A is the 1-O-position-specific node |
| 6-shogaol | CHEBI:10138 | CHEBI:10138 | ✓ | [6]-shogaol; A is the [8] homolog |
| 9-hydroxystearate | CHEBI:136638 | CHEBI:136638 | ✓ | 9-OH-octadecanoate; B is the 8-OH isomer |

## What downstream consumers get now
- **22 auto-labeled pairs** ready for the Tier-1 hard slice / ablation / TB-Science gold (gated on retrievability), each with an `rm_blinded_view` for the leakage control.
- **113-pair expert queue**, pre-narrowed to genuinely stereo/charge/positional cases — the actual human effort, and (being >100) enough on its own to hit the ablation's ≥100-pair bar once adjudicated.
- **37 resolution-limited pairs** flagged for a cheaper fix (supply a query structure) before they need a human.
