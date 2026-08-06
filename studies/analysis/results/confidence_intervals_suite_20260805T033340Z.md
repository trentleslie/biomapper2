# Confidence intervals — suite_20260805T033340Z

- backend: `https://kestrel.krakenkg.com/api`
- commit: `d05956459ece9dffbc737250df98d2119c2eb0e6`
- graph snapshot: `kraken 2.0.1 (14683250n/92233909e)`
- biolink: `4.2.5`
- ChEBI release: `unrecorded` (node-count fingerprint: `202220`)

> These intervals are MARGINAL, not simultaneous. No claim of the form 'X exceeds Y' may be derived from two intervals failing to overlap: non-overlap is neither necessary nor sufficient for a difference, and several rows in this table are not independent of each other. Where a difference is claimed, use the paired_difference field on the dependent row.

Intervals are **marginal**, seed-free and closed-form.

| row | dataset | regime | metric | flag | k | n | rate | interval | ±pt | role | family |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `metabench:overall:strict` | metabench | overall | strict | `correct` | 527 | 1000 | 0.5270 | [0.4960, 0.5578] | 3.0885 | derived_aggregate | `metabench:grounding` |
| `metabench:KEGG:strict` | metabench | KEGG | strict | `correct` | 303 | 400 | 0.7575 | [0.7132, 0.7969] | 4.1873 | primary | `metabench:grounding` |
| `metabench:HMDB:strict` | metabench | HMDB | strict | `correct` | 69 | 400 | 0.1725 | [0.1386, 0.2126] | 3.698 | primary | `metabench:grounding` |
| `metabench:CHEBI:strict` | metabench | CHEBI | strict | `correct` | 155 | 200 | 0.7750 | [0.7123, 0.8274] | 5.7559 | primary | `metabench:grounding` |
| `necs:CHEBI:overall:strict` | necs | overall | strict | `correct` | 609 | 796 | 0.7651 | [0.7344, 0.7932] | 2.9408 | primary | `necs:CHEBI` |
| `necs:CHEBI:overall:charge_normalized` | necs | overall | charge_normalized | `charge_normalized_correct` | 624 | 796 | 0.7839 | [0.7540, 0.8111] | 2.8555 | nested | `necs:CHEBI` |
| `necs:CHEBI:overall:kg_equivalence_set` | necs | overall | kg_equivalence_set | `kg_equivalence_set_correct` | 668 | 796 | 0.8392 | [0.8121, 0.8631] | 2.551 | nested | `necs:CHEBI` |
| `hgnc:ENSEMBL:any-namespace:strict` | hgnc | overall | strict | `correct` | 1442 | 1496 | 0.9639 | [0.9532, 0.9722] | 0.9515 | derived_union | `hgnc:symbol-sample` |
| `hgnc:ENSEMBL:ENSEMBL:strict` | hgnc | ENSEMBL | strict | `correct` | 1106 | 1399 | 0.7906 | [0.7685, 0.8111] | 2.1308 | nested | `hgnc:symbol-sample` |
| `hgnc:ENSEMBL:NCBIGene:strict` | hgnc | NCBIGene | strict | `correct` | 1441 | 1475 | 0.9769 | [0.9680, 0.9835] | 0.7748 | nested | `hgnc:symbol-sample` |
| `hgnc:ENSEMBL:UniProtKB:strict` | hgnc | UniProtKB | strict | `correct` | 594 | 643 | 0.9238 | [0.9007, 0.9419] | 2.0601 | nested | `hgnc:symbol-sample` |
| `metaboliteannotator:positive:name_hit` | metaboliteannotator | overall | name_hit_rate | `hit` | 4179 | 4314 | 0.9687 | [0.9631, 0.9735] | 0.521 | standalone | `metaboliteannotator:positive` |
| `metlinkr:curator_agreement` | metlinkr | overall | curator_agreement_rate | `linked` | 333 | 401 | 0.8304 | [0.7906, 0.8640] | 3.6688 | standalone | `metlinkr:curator-pairs` |
| `metlinkr:structural_concordance` | metlinkr | overall | inchikey_structural_concordance | `concordant` | 543 | 649 | 0.8367 | [0.8063, 0.8631] | 2.8426 | standalone | `metlinkr:structural` |
| `refmet:CHEBI:overall:strict` | refmet | overall | strict | `correct` | 1319 | 1500 | 0.8793 | [0.8619, 0.8949] | 1.6492 | primary | `refmet:CHEBI` |
| `refmet:CHEBI:overall:charge_normalized` | refmet | overall | charge_normalized | `charge_normalized_correct` | 1321 | 1500 | 0.8807 | [0.8633, 0.8961] | 1.6413 | nested | `refmet:CHEBI` |
| `refmet:CHEBI:overall:kg_equivalence_set` | refmet | overall | kg_equivalence_set | `kg_equivalence_set_correct` | 1347 | 1500 | 0.8980 | [0.8817, 0.9123] | 1.533 | nested | `refmet:CHEBI` |
| `srm1950:CHEBI:overall:strict` | srm1950 | overall | strict | `correct` | 411 | 983 | 0.4181 | [0.3877, 0.4492] | 3.0776 | primary | `srm1950:CHEBI` |
| `srm1950:CHEBI:overall:charge_normalized` | srm1950 | overall | charge_normalized | `charge_normalized_correct` | 413 | 983 | 0.4201 | [0.3897, 0.4513] | 3.0797 | nested | `srm1950:CHEBI` |
| `srm1950:CHEBI:overall:kg_equivalence_set` | srm1950 | overall | kg_equivalence_set | `kg_equivalence_set_correct` | 450 | 983 | 0.4578 | [0.4269, 0.4890] | 3.1085 | nested | `srm1950:CHEBI` |
| `lmsd:CHEBI:overall:strict` | lmsd | overall | strict | `correct` | 255 | 1500 | 0.1700 | [0.1518, 0.1898] | 1.9004 | derived_aggregate | `lmsd:CHEBI` |
| `lmsd:CHEBI:overall:charge_normalized` | lmsd | overall | charge_normalized | `charge_normalized_correct` | 263 | 1500 | 0.1753 | [0.1569, 0.1954] | 1.9236 | nested | `lmsd:CHEBI` |
| `lmsd:CHEBI:overall:kg_equivalence_set` | lmsd | overall | kg_equivalence_set | `kg_equivalence_set_correct` | 263 | 1500 | 0.1753 | [0.1569, 0.1954] | 1.9236 | nested | `lmsd:CHEBI` |
| `lmsd:CHEBI:common_systematic:strict` | lmsd | common_systematic | strict | `correct` | 189 | 451 | 0.4191 | [0.3744, 0.4651] | 4.5349 | primary | `lmsd:CHEBI:common_systematic` |
| `lmsd:CHEBI:common_systematic:charge_normalized` | lmsd | common_systematic | charge_normalized | `charge_normalized_correct` | 196 | 451 | 0.4346 | [0.3896, 0.4807] | 4.5559 | nested | `lmsd:CHEBI:common_systematic` |
| `lmsd:CHEBI:shorthand:strict` | lmsd | shorthand | strict | `correct` | 66 | 1049 | 0.0629 | [0.0498, 0.0793] | 1.4753 | primary | `lmsd:CHEBI:shorthand` |
| `lmsd:CHEBI:shorthand:charge_normalized` | lmsd | shorthand | charge_normalized | `charge_normalized_correct` | 67 | 1049 | 0.0639 | [0.0506, 0.0803] | 1.4856 | nested | `lmsd:CHEBI:shorthand` |

## Paired differences (nested contrasts)

Reported as differences rather than as two side-by-side intervals: the relaxed flag is a
superset of the strict one over the same rows, so their marginal intervals overlap by
construction and reading them as independent understates the contrast.

The interval inverts the SCORE statistic, so `score p` is its coherent partner: those
two agree about zero by construction. `exact p` is the conservative binomial test and
can disagree with the interval at small discordant totals -- that is a property of the
two tests, not an inconsistency in the estimate. The multiplicity correction is applied
to `exact p`. A row where the interval's exclusion of zero disagrees with `score p` is
flagged, since that WOULD be incoherent.

| row | contrast | b | c | difference | interval | score p | exact p | adjusted p | family |
|---|---|---|---|---|---|---|---|---|---|
| `necs:CHEBI:overall:charge_normalized` | charge_normalized_correct minus correct | 34 | 19 | 0.01884 | [0.00095, 0.03775] | 0.0394 | 0.0534 | 0.0748 | `oracle_variant_contrasts` |
| `necs:CHEBI:overall:kg_equivalence_set` | kg_equivalence_set_correct minus correct | 59 | 0 | 0.07412 | [0.05790, 0.09444] | 1.58e-14 | 3.47e-18 | 2.43e-17 | `oracle_variant_contrasts` |
| `refmet:CHEBI:overall:charge_normalized` | charge_normalized_correct minus correct | 3 | 1 | 0.00133 | [-0.00194, 0.00527] | 0.317 | 0.625 | 0.729 | `oracle_variant_contrasts` |
| `refmet:CHEBI:overall:kg_equivalence_set` | kg_equivalence_set_correct minus correct | 28 | 0 | 0.01867 | [0.01295, 0.02685] | 1.21e-07 | 7.45e-09 | 1.74e-08 | `oracle_variant_contrasts` |
| `srm1950:CHEBI:overall:charge_normalized` | charge_normalized_correct minus correct | 6 | 4 | 0.00203 | [-0.00507, 0.00968] | 0.527 | 0.754 | 0.754 | `oracle_variant_contrasts` |
| `srm1950:CHEBI:overall:kg_equivalence_set` | kg_equivalence_set_correct minus correct | 39 | 0 | 0.03967 | [0.02916, 0.05378] | 4.24e-10 | 3.64e-12 | 1.27e-11 | `oracle_variant_contrasts` |
| `lmsd:CHEBI:overall:charge_normalized` | - | - | - | - | - | - | - | - | per-row ids under 'name' are not unique, so a paired contrast keyed on them would manufacture discordant pairs; no difference statistic emitted |
| `lmsd:CHEBI:overall:kg_equivalence_set` | - | - | - | - | - | - | - | - | per-row ids under 'name' are not unique, so a paired contrast keyed on them would manufacture discordant pairs; no difference statistic emitted |
| `lmsd:CHEBI:common_systematic:charge_normalized` | charge_normalized_correct minus correct | 7 | 0 | 0.01552 | [0.00694, 0.03169] | 0.00815 | 0.0156 | 0.0273 | `oracle_variant_contrasts` |
| `lmsd:CHEBI:shorthand:charge_normalized` | - | - | - | - | - | - | - | - | per-row ids under 'name' are not unique, so a paired contrast keyed on them would manufacture discordant pairs; no difference statistic emitted |

## Datasets absent or partial

Listed rather than dropped: an omitted dataset is indistinguishable from one that
scored badly.

| dataset | suite status | reason |
|---|---|---|
| metaboliteannotator | failed | RuntimeError: metaboliteannotator-negative: no target vocab produced a result (mapper failed: {'CHEBI': '500 Server Error: Internal Server Error for url: https://kestrel.krakenkg.com/api/hybrid-search', 'HMDB': '500 Server Error: Internal Server Error for url: https://kestrel.krakenkg.com/api/hybrid-search', 'PUBCHEM': '500 Server Error: Internal Server Error for url: https://kestrel.krakenkg.com/api/hybrid-search', 'KEGG': '500 Server Error: Internal Server Error for url: https://kestrel.krakenkg.com/api/hybrid-search'}). |
| nlmgene | failed | RuntimeError: nlm-gene primary vocab 'NCBIGene' produced no result (mapper failed: '500 Server Error: Internal Server Error for url: https://kestrel.krakenkg.com/api/hybrid-search'). |
| swisslipids | failed | RuntimeError: SwissLipids primary vocab 'CHEBI' produced no result (mapper failed: "columns overlap but no suffix specified: Index(['lipid_name', 'query_source', 'held_out_pubchem',\n       'gold_inchikey_swisslipids', 'gold_smiles', 'gold_hmdb',\n       'gold_inchikey', 'has_gold_pubchem', 'assigned_ids'],\n      dtype='object')"). |
| provided-id | skipped | a --dataset family over bulk backbones; needs a pinned artifact, not a URL |
| pham | skipped | source is a MetaNetX FTP path requiring hand reconstruction, not a fetchable file |
| hajjar | skipped | no pinned source_url; the supplement is hand-passed via --supplement |

## Cross-dataset weighting

the file-weighted cross-dataset rate multiplies a dataset by the number of target-vocabulary files it ships, and those files carry identical resolutions. Quote the deduplicated figure below; the file-weighted one is named, not carried, so it cannot be lifted from here

Deduplicated off-category rate: **4.05%** (282 of 6957 committed rows).
