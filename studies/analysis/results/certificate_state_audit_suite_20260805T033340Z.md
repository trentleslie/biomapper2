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

