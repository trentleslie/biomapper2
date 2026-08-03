# Resolve lipid shorthand names to chemical structures

You are given a list of lipids named in **LIPID MAPS shorthand notation** (e.g.
`TG 57:6`, `PC 34:1`, `Cer 42:0;O`, `FA 18:2`). Your job is to determine the chemical
structure each shorthand denotes and emit it as a **SMILES** string.

## Input

`/app/lipids.txt` — one lipid shorthand per line.

## What to produce

Write `/app/results/predictions.tsv` — a tab-separated file with **one row per input
lipid**, two columns, no required header:

```
<lipid shorthand><TAB><SMILES>
```

- The shorthand in column 1 must match the input line exactly (character for character).
- Column 2 is a single valid SMILES for the structure that shorthand denotes.
- Emit an isomeric SMILES if you are confident of the stereochemistry; otherwise a valid
  non-isomeric SMILES is acceptable.
- Include a row for every input lipid. If you cannot resolve one, still emit a row with
  your best attempt (an empty second column counts as no answer).

## Rules

- **No network access.** Resolve each name from your own knowledge and reasoning; you may
  write and run code, and use any locally installed libraries, but you cannot fetch data
  from the internet.
- Do not modify `/app/lipids.txt`.

## Notes

A lipid shorthand encodes a head-group / class, the total acyl carbon count, the total
number of double bonds, and any functional-group modifiers (e.g. `;O2`, `O-` ether
linkage). Reconstruct a chemically valid structure consistent with what the shorthand
specifies.
