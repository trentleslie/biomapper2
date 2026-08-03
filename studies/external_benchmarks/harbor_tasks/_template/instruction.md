# <Task title — the resolution problem, agent-facing>

You are given <N> <entity>s named in <notation>. Determine the <answer> each denotes and
emit it as <format>.

## Input
`/app/lipids.txt` (rename per candidate) — one <entity> per line.

## What to produce
`/app/results/predictions.tsv` — one row per input, tab-separated: `<name><TAB><answer>`.
- Column 1 must match the input line exactly.
- Include a row for every input.

## Rules
- **No network access.** Resolve from your own knowledge/reasoning; local libraries + code
  are allowed, but no internet.
- Do not modify the input file.

## Notes
<Describe what the notation encodes — WITHOUT revealing the grader's resolution level or that
any particular over-specification is tolerated. The resolution is a grader-side choice.>
