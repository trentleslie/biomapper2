# Certificate-state audit

Suite: `/home/trentleslie/benchmark-runs/suite_20260805T033340Z`
Provenance: `{"kg_stable_during_run": true, "suite_manifest": "/home/trentleslie/benchmark-runs/suite_20260805T033340Z/suite_manifest.json"}`

## Tier A certificate state and precision by state

| dataset | rows | structure_absent share | struct-oracle blended | struct-oracle present | id-oracle blended | id-oracle present | absent rows id-oracle COULD score |
|---|---|---|---|---|---|---|---|
| necs | 1488 | 29.1% | 83.5% | 92.6% | 76.7% | 88.9% | 0 |
| refmet | 1500 | 6.9% | 89.3% | 96.0% | 58.3% | 64.6% | 0 |
| srm1950 | 1058 | 49.1% | 42.7% | 84.7% | - | - | 0 |
| lmsd | 1499 | 65.4% | 14.3% | 41.4% | 21.7% | 58.8% | 0 |
| metlinkr:CHEBI | 1412 | 31.7% | - | - | - | - | 0 |
| metlinkr:HMDB | 1412 | 31.7% | - | - | - | - | 0 |
| metlinkr:KEGG | 1412 | 31.7% | - | - | - | - | 0 |
| metlinkr:PUBCHEM | 1412 | 31.7% | - | - | - | - | 0 |
| metlinkr:REFMET | 1412 | 31.7% | - | - | - | - | 0 |

The last column is the admissibility test for any precision claim about the
`structure_absent` bucket: when it is zero, neither oracle can adjudicate that bucket and
the honest certificate state is `unavailable`, not `contradicted`.

## Figure 5 — panel A: declared abstention rate

Abstention is a coverage statistic, NOT an operating point. A precision delta plotted across
the `unavailable` boundary would assert that refusing those rows buys precision, which no
oracle here can support; this panel shows the refusal happening without implying the refused
answers were wrong.

| dataset | rows | unavailable | not_applicable | abstention rate | certificate source |
|---|---|---|---|---|---|
| necs | 1488 | 433 | 0 | 29.1% | derived_from_kg_equivalent_ids |
| refmet | 1500 | 104 | 0 | 6.9% | derived_from_kg_equivalent_ids |
| srm1950 | 1058 | 520 | 0 | 49.1% | derived_from_kg_equivalent_ids |
| lmsd | 1499 | 980 | 0 | 65.4% | derived_from_kg_equivalent_ids |
| metlinkr:CHEBI | 1412 | 448 | 0 | 31.7% | derived_from_kg_equivalent_ids |
| metlinkr:HMDB | 1412 | 448 | 0 | 31.7% | derived_from_kg_equivalent_ids |
| metlinkr:KEGG | 1412 | 448 | 0 | 31.7% | derived_from_kg_equivalent_ids |
| metlinkr:PUBCHEM | 1412 | 448 | 0 | 31.7% | derived_from_kg_equivalent_ids |
| metlinkr:REFMET | 1412 | 448 | 0 | 31.7% | derived_from_kg_equivalent_ids |

## Figure 5 — panel B: precision-coverage within the verifiable population

Stratified by independent source, never averaged: a verdict from the same registry that
supplied the committed node is not independent evidence of it.

### necs

Publishable: `False` — input carries no certificate_* columns; Tier A was derived, Tier B never ran

```json
{
  "panel_b": {
    "n_verifiable": 718,
    "strata": {
      "none": {
        "n_verifiable": 718,
        "independent_of_selection": null,
        "points": [
          {
            "certificate_state": "uncorroborated",
            "n": 718,
            "coverage": 0.4825,
            "precision": 0.9262
          }
        ]
      }
    }
  },
  "tier_b": {
    "n_rows_with_tier_b_outcome": 1488,
    "n_tier_b_resolved": 0,
    "n_tier_b_lookup_failed": 0,
    "resolution_rate_all_rows": 0.0,
    "n_verifiable": 718,
    "n_tier_b_resolved_verifiable": 0,
    "resolution_rate": 0.0,
    "outcomes": {
      "off": 1488
    },
    "min_resolution_rate_floor": 0.5
  }
}
```

### refmet

Publishable: `False` — input carries no certificate_* columns; Tier A was derived, Tier B never ran

```json
{
  "panel_b": {
    "n_verifiable": 1396,
    "strata": {
      "none": {
        "n_verifiable": 1396,
        "independent_of_selection": null,
        "points": [
          {
            "certificate_state": "uncorroborated",
            "n": 1396,
            "coverage": 0.9307,
            "precision": 0.9599
          }
        ]
      }
    }
  },
  "tier_b": {
    "n_rows_with_tier_b_outcome": 1500,
    "n_tier_b_resolved": 0,
    "n_tier_b_lookup_failed": 0,
    "resolution_rate_all_rows": 0.0,
    "n_verifiable": 1396,
    "n_tier_b_resolved_verifiable": 0,
    "resolution_rate": 0.0,
    "outcomes": {
      "off": 1500
    },
    "min_resolution_rate_floor": 0.5
  }
}
```

### srm1950

Publishable: `False` — input carries no certificate_* columns; Tier A was derived, Tier B never ran

```json
{
  "panel_b": {
    "n_verifiable": 496,
    "strata": {
      "none": {
        "n_verifiable": 496,
        "independent_of_selection": null,
        "points": [
          {
            "certificate_state": "uncorroborated",
            "n": 496,
            "coverage": 0.4688,
            "precision": 0.8468
          }
        ]
      }
    }
  },
  "tier_b": {
    "n_rows_with_tier_b_outcome": 1058,
    "n_tier_b_resolved": 0,
    "n_tier_b_lookup_failed": 0,
    "resolution_rate_all_rows": 0.0,
    "n_verifiable": 496,
    "n_tier_b_resolved_verifiable": 0,
    "resolution_rate": 0.0,
    "outcomes": {
      "off": 1058
    },
    "min_resolution_rate_floor": 0.5
  }
}
```

### lmsd

Publishable: `False` — input carries no certificate_* columns; Tier A was derived, Tier B never ran

```json
{
  "panel_b": {
    "n_verifiable": 519,
    "strata": {
      "none": {
        "n_verifiable": 519,
        "independent_of_selection": null,
        "points": [
          {
            "certificate_state": "uncorroborated",
            "n": 519,
            "coverage": 0.3462,
            "precision": 0.4143
          }
        ]
      }
    }
  },
  "tier_b": {
    "n_rows_with_tier_b_outcome": 1499,
    "n_tier_b_resolved": 0,
    "n_tier_b_lookup_failed": 0,
    "resolution_rate_all_rows": 0.0,
    "n_verifiable": 519,
    "n_tier_b_resolved_verifiable": 0,
    "resolution_rate": 0.0,
    "outcomes": {
      "off": 1499
    },
    "min_resolution_rate_floor": 0.5
  }
}
```

### metlinkr:CHEBI

Publishable: `False` — input carries no certificate_* columns; Tier A was derived, Tier B never ran

```json
{
  "panel_b": {
    "n_verifiable": 0,
    "strata": {}
  },
  "tier_b": {
    "n_rows_with_tier_b_outcome": 1412,
    "n_tier_b_resolved": 0,
    "n_tier_b_lookup_failed": 0,
    "resolution_rate_all_rows": 0.0,
    "n_verifiable": 0,
    "n_tier_b_resolved_verifiable": 0,
    "resolution_rate": null,
    "outcomes": {
      "off": 1412
    },
    "min_resolution_rate_floor": 0.5
  }
}
```

### metlinkr:HMDB

Publishable: `False` — input carries no certificate_* columns; Tier A was derived, Tier B never ran

```json
{
  "panel_b": {
    "n_verifiable": 0,
    "strata": {}
  },
  "tier_b": {
    "n_rows_with_tier_b_outcome": 1412,
    "n_tier_b_resolved": 0,
    "n_tier_b_lookup_failed": 0,
    "resolution_rate_all_rows": 0.0,
    "n_verifiable": 0,
    "n_tier_b_resolved_verifiable": 0,
    "resolution_rate": null,
    "outcomes": {
      "off": 1412
    },
    "min_resolution_rate_floor": 0.5
  }
}
```

### metlinkr:KEGG

Publishable: `False` — input carries no certificate_* columns; Tier A was derived, Tier B never ran

```json
{
  "panel_b": {
    "n_verifiable": 0,
    "strata": {}
  },
  "tier_b": {
    "n_rows_with_tier_b_outcome": 1412,
    "n_tier_b_resolved": 0,
    "n_tier_b_lookup_failed": 0,
    "resolution_rate_all_rows": 0.0,
    "n_verifiable": 0,
    "n_tier_b_resolved_verifiable": 0,
    "resolution_rate": null,
    "outcomes": {
      "off": 1412
    },
    "min_resolution_rate_floor": 0.5
  }
}
```

### metlinkr:PUBCHEM

Publishable: `False` — input carries no certificate_* columns; Tier A was derived, Tier B never ran

```json
{
  "panel_b": {
    "n_verifiable": 0,
    "strata": {}
  },
  "tier_b": {
    "n_rows_with_tier_b_outcome": 1412,
    "n_tier_b_resolved": 0,
    "n_tier_b_lookup_failed": 0,
    "resolution_rate_all_rows": 0.0,
    "n_verifiable": 0,
    "n_tier_b_resolved_verifiable": 0,
    "resolution_rate": null,
    "outcomes": {
      "off": 1412
    },
    "min_resolution_rate_floor": 0.5
  }
}
```

### metlinkr:REFMET

Publishable: `False` — input carries no certificate_* columns; Tier A was derived, Tier B never ran

```json
{
  "panel_b": {
    "n_verifiable": 0,
    "strata": {}
  },
  "tier_b": {
    "n_rows_with_tier_b_outcome": 1412,
    "n_tier_b_resolved": 0,
    "n_tier_b_lookup_failed": 0,
    "resolution_rate_all_rows": 0.0,
    "n_verifiable": 0,
    "n_tier_b_resolved_verifiable": 0,
    "resolution_rate": null,
    "outcomes": {
      "off": 1412
    },
    "min_resolution_rate_floor": 0.5
  }
}
```

## Review flag vs Tier A state

### necs

```json
{
  "conflict_no_structure": {
    "structure_absent": 75,
    "structure_present": 9
  },
  "divergent_refmet": {
    "structure_absent": 13,
    "structure_present": 117
  },
  "no_flag": {
    "structure_absent": 345,
    "structure_present": 929
  }
}
```

### refmet

```json
{
  "conflict_no_structure": {
    "structure_absent": 85
  },
  "divergent_refmet": {
    "structure_absent": 1,
    "structure_present": 34
  },
  "no_flag": {
    "structure_absent": 18,
    "structure_present": 1362
  }
}
```

### srm1950

```json
{
  "conflict_no_structure": {
    "structure_absent": 235,
    "structure_present": 27
  },
  "divergent_refmet": {
    "structure_absent": 17,
    "structure_present": 46
  },
  "no_flag": {
    "structure_absent": 268,
    "structure_present": 465
  }
}
```

### lmsd

```json
{
  "conflict_no_structure": {
    "structure_absent": 32,
    "structure_present": 20
  },
  "divergent_refmet": {
    "structure_absent": 30,
    "structure_present": 7
  },
  "no_flag": {
    "structure_absent": 918,
    "structure_present": 492
  }
}
```

### metlinkr:CHEBI

```json
{
  "conflict_no_structure": {
    "structure_absent": 64,
    "structure_present": 8
  },
  "divergent_refmet": {
    "structure_absent": 4,
    "structure_present": 108
  },
  "no_flag": {
    "structure_absent": 380,
    "structure_present": 848
  }
}
```

### metlinkr:HMDB

```json
{
  "conflict_no_structure": {
    "structure_absent": 64,
    "structure_present": 8
  },
  "divergent_refmet": {
    "structure_absent": 4,
    "structure_present": 108
  },
  "no_flag": {
    "structure_absent": 380,
    "structure_present": 848
  }
}
```

### metlinkr:KEGG

```json
{
  "conflict_no_structure": {
    "structure_absent": 64,
    "structure_present": 8
  },
  "divergent_refmet": {
    "structure_absent": 4,
    "structure_present": 108
  },
  "no_flag": {
    "structure_absent": 380,
    "structure_present": 848
  }
}
```

### metlinkr:PUBCHEM

```json
{
  "conflict_no_structure": {
    "structure_absent": 64,
    "structure_present": 8
  },
  "divergent_refmet": {
    "structure_absent": 4,
    "structure_present": 108
  },
  "no_flag": {
    "structure_absent": 380,
    "structure_present": 848
  }
}
```

### metlinkr:REFMET

```json
{
  "conflict_no_structure": {
    "structure_absent": 64,
    "structure_present": 8
  },
  "divergent_refmet": {
    "structure_absent": 4,
    "structure_present": 108
  },
  "no_flag": {
    "structure_absent": 380,
    "structure_present": 848
  }
}
```

