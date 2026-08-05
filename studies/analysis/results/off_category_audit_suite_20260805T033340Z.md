## Off-category commit audit

- Pinned input: `/home/trentleslie/benchmark-runs/suite_20260805T033340Z`
- KG snapshot: `kraken 2.0.1 (14683250n/92233909e)` (kg_stable_during_run=True)
- biomapper2 git_sha: `d05956459ece9dffbc737250df98d2119c2eb0e6` | Biolink `4.2.5`
- Acceptance set: 12 descendants of `biolink:ChemicalEntity`
- Generated: 2026-08-05T23:21:22.409171+00:00

### Per dataset

| dataset | arm | files | commits | off-category | % | failure-open |
|---|---|---:|---:|---:|---:|---:|
| metlinkr | metabolite | 5 | 7,060 | 1,070 | 15.16% | 10 |
| necs | metabolite | 1 | 1,488 | 65 | 4.37% | 0 |
| refmet | metabolite | 1 | 1,500 | 0 | 0.0% | 0 |
| srm1950 | metabolite | 1 | 1,058 | 3 | 0.28% | 0 |
| lmsd | metabolite | 1 | 1,499 | 0 | 0.0% | 0 |
| hgnc | gene_control | 3 | 4,476 | 4,197 | 93.77% | 0 |
| **METABOLITE TOTAL** | metabolite | | **12,605** | **1,138** | **9.03%** | 10 |

The gene arm (hgnc, 4,476 commits, 93.77% off-category) is a control and is deliberately excluded from the metabolite total: a gene commit is *supposed* to be off-category relative to a chemical root, which is why the gene path ships with the validator disabled.

Counting the 10 failure-open rows as off-category (the literal "carried no chemical category" reading) gives 1,148 / 12,605 = 9.11%. The validator itself refuses only the 1,138.

### Off-category composition (metabolite arm, by exact category set)

| categories | rows |
|---|---:|
| biolink:PhenotypicFeature | 692 |
| biolink:Gene + biolink:Protein | 202 |
| biolink:Protein | 160 |
| biolink:InformationContentEntity | 35 |
| biolink:CellLine | 10 |
| biolink:OrganismTaxon | 10 |
| biolink:Gene | 7 |
| biolink:BiologicalEntity | 6 |
| biolink:AnatomicalEntity | 5 |
| biolink:Phenomenon | 5 |
| biolink:DiseaseOrPhenotypicFeature | 5 |
| biolink:ClinicalAttribute | 1 |

### Refusal cost: how many refusals were the RIGHT compound?

#### Population: protein/gene-typed off-category commits (n=369)

| verdict | rows | % of population | % of adjudicable |
|---|---:|---:|---:|
| CORRECT_BUT_REFUSED | 0 | 0.0% | 0.0% |
| WRONG_AND_REFUSED | 2 | 0.54% | 100.0% |
| UNRESOLVABLE | 367 | 99.46% | - |

Gold instrument used: {'none': 367, 'gold_database_id': 2}

Unresolvable breakdown: {'node_carries_no_chemical_identifier': 367}

**Refusal provably costless for 369 / 369 (100.0%)** -- WRONG_AND_REFUSED plus rows whose committed node carries no chemical identifier in any namespace (so it cannot be the right compound under a wrong type).

| category | CORRECT_BUT_REFUSED | WRONG_AND_REFUSED | UNRESOLVABLE |
|---|---:|---:|---:|
| `biolink:Gene` | 0 | 2 | 207 |
| `biolink:Protein` | 0 | 2 | 360 |


#### Population: all off-category commits, metabolite arm (n=1,138)

| verdict | rows | % of population | % of adjudicable |
|---|---:|---:|---:|
| CORRECT_BUT_REFUSED | 0 | 0.0% | 0.0% |
| WRONG_AND_REFUSED | 132 | 11.6% | 100.0% |
| UNRESOLVABLE | 1,006 | 88.4% | - |

Gold instrument used: {'none': 1006, 'gold_database_id': 132}

Unresolvable breakdown: {'node_carries_no_chemical_identifier': 1001, 'row_has_no_gold_structure_or_id': 5}

**Refusal provably costless for 1,133 / 1,138 (99.56%)** -- WRONG_AND_REFUSED plus rows whose committed node carries no chemical identifier in any namespace (so it cannot be the right compound under a wrong type).

| category | CORRECT_BUT_REFUSED | WRONG_AND_REFUSED | UNRESOLVABLE |
|---|---:|---:|---:|
| `biolink:AnatomicalEntity` | 0 | 0 | 5 |
| `biolink:BiologicalEntity` | 0 | 1 | 5 |
| `biolink:CellLine` | 0 | 0 | 10 |
| `biolink:ClinicalAttribute` | 0 | 1 | 0 |
| `biolink:DiseaseOrPhenotypicFeature` | 0 | 0 | 5 |
| `biolink:Gene` | 0 | 2 | 207 |
| `biolink:InformationContentEntity` | 0 | 0 | 35 |
| `biolink:OrganismTaxon` | 0 | 0 | 10 |
| `biolink:Phenomenon` | 0 | 0 | 5 |
| `biolink:PhenotypicFeature` | 0 | 128 | 564 |
| `biolink:Protein` | 0 | 2 | 360 |


#### Population: ON-category commits, metabolite arm (positive control) (n=11,467)

| verdict | rows | % of population | % of adjudicable |
|---|---:|---:|---:|
| CORRECT_BUT_REFUSED | 4,434 | 38.67% | 52.21% |
| WRONG_AND_REFUSED | 4,059 | 35.4% | 47.79% |
| UNRESOLVABLE | 2,974 | 25.94% | - |

Gold instrument used: {'none': 2974, 'gold_database_id': 5463, 'inchikey_first_block': 3030}

Unresolvable breakdown: {'row_has_no_gold_structure_or_id': 2782, 'node_carries_no_chemical_identifier': 187, 'gold_present_but_node_not_comparable': 5}

_these rows were NOT refused; read CORRECT_BUT_REFUSED here as simply 'gold agrees with the committed node'. The point of this block is only that the adjudicator can return that verdict._

| category | CORRECT_BUT_REFUSED | WRONG_AND_REFUSED | UNRESOLVABLE |
|---|---:|---:|---:|
| `biolink:ChemicalEntity` | 2 | 63 | 302 |
| `biolink:Drug` | 787 | 807 | 402 |
| `biolink:MolecularEntity` | 0 | 0 | 10 |
| `biolink:MolecularMixture` | 2 | 8 | 6 |
| `biolink:NamedThing` | 0 | 0 | 10 |
| `biolink:NucleicAcidEntity` | 32 | 20 | 25 |
| `biolink:OrganismTaxon` | 0 | 11 | 0 |
| `biolink:Protein` | 9 | 22 | 15 |
| `biolink:SmallMolecule` | 4,432 | 3,987 | 2,635 |

