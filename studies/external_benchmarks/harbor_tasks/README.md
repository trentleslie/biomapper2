# Harbor task-build + eval pipeline (reusable)

A reusable pipeline for turning a **benchmark candidate** (a name→answer resolution task
with third-party gold) into a **Terminal-Bench Science (Harbor Task Format)** submission,
plus a Docker-free proxy for the "is it too easy?" difficulty read. The **lipid-shorthand**
task (`lipid-shorthand-structure/`) is the first instance; the structure is deliberately
generic so a different candidate drops in with minimal change.

## Why this exists

TB-Science tasks must be **hard for a tool-using terminal agent** (10–20% solve band),
graded by a **deterministic, isolated pytest verifier**, with **defensible third-party
gold**. Standing up the build + verify + analyze scaffolding once — and reusing it — is the
real deliverable; lipid is the proving instance. See the vault refs:
`Active 🎯/Work/Projects/Terminal-Bench Science/`.

## Layout

```
harbor_tasks/
├── _lib/
│   └── harbor_grade.py        # candidate-AGNOSTIC verifier core (gate + score + reward)
├── _template/                 # skeleton to copy for a NEW candidate (placeholders)
│   ├── task.toml
│   ├── instruction.md
│   ├── environment/Dockerfile
│   ├── tests/{test.sh, grade.py, test_outputs.py}
│   └── solution/{solve.sh, solve.py}
├── lipid-shorthand-structure/ # FIRST INSTANCE — complete, self-tested (see below)
└── proxy/
    └── run_proxy.py           # Docker-free "too-easy" proxy (reasoning-enabled model)
```

## The reusable core: `_lib/harbor_grade.py`

Knows nothing about lipids. It defines:
- the **agent output contract** — `/app/results/predictions.tsv` (`name<TAB>answer`),
- the **gold contract** — `gold.jsonl` (one JSON row per case),
- an **`AdapterProtocol`** — the only candidate-specific surface (4 methods),
- the **gate + two-metric scoring + failure taxonomy** (imported from the spike's
  validated `score.py`), and
- the **reward emission** — `reward.json` / `reward.txt` / `score_breakdown.json`, with a
  binary reward = `1.0` iff the fractional score ≥ `pass_threshold` (the difficulty dial,
  mirroring the `ont-tn-qc` reference task's normalize-then-threshold pattern).

## How a NEW candidate plugs in (the reusable-pipeline ask)

To add candidate **X** (e.g. a different namespace-resolution task with public gold):

1. **Copy** `_template/` → `X-task/`.
2. **Gold** — produce `tests/gold.jsonl`: one `{"name": ..., "gold_*": ...}` per case, from
   a *third-party* source (never the tool under test). Dedupe by `name`.
3. **Adapter** — write `tests/reference_X.py` exposing four methods
   (`parse_reference`, `formula_from_answer`, `inchikey_from_answer`, `class_check` — or the
   analogous "normalize the answer to a comparable invariant" functions for X's domain), and
   point `tests/grade.py`'s `Adapter` at it. Vendor the shared `score.py` + `harbor_grade.py`
   into `tests/` (Harbor copies only `tests/` into the verifier container).
4. **task.toml** — fill `[metadata]`, set `[environment].allow_internet = false` (the
   no-network difficulty lever), generate a fresh `harbor-canary GUID`.
5. **instruction.md** — describe the task WITHOUT leaking the grader resolution.
6. **environment/Dockerfile** — install only what the agent legitimately needs; **never**
   install the oracle grammar/grader in the agent image (that would trivialize it).
7. **solution/** — an oracle that emits the third-party gold answers → 100% on the fair
   metric (the required "oracle passes / no-op fails" invariant).
8. **Self-test locally** (no Docker): run `tests/grade.py` with `*_GOLD_PATH` / `*_PRED_PATH`
   / `*_VERIFIER_DIR` env overrides against (a) a weak baseline (reward 0) and (b) the oracle
   gold (reward 1); run `pytest tests/test_outputs.py`.
9. **Calibrate the threshold** via a real Harbor run + `harbor analyze` to land 10–20% solve.

Only steps 2 + 3 are candidate-specific work; everything else is fill-in-the-blank.

## The lipid instance (reference)

`lipid-shorthand-structure/` — resolve LIPID MAPS shorthand (`TG 57:6`, `Cer 42:0;O`) →
SMILES, graded at **sum-composition** resolution (molecular-formula match, isomer-tolerant),
`no-network`. Neutral grader = **pygoslin** (name→sum formula, gate) + **RDKit**
(SMILES→formula/InChIKey) — never BioMapper (circular). Dataset = the 94 unique gate-eligible
names from the seed-8617 spike subset; runtime gate reproduces ~68 gradeable.

Self-test results (main biomapper2 `.venv`, pygoslin 2.2.3 / RDKit 2025.9.3):
- naive one-shot SMILES (thinking-disabled, from the spike): **species-match 13.2% (9/68) →
  reward 0** at threshold 0.40
- oracle gold SMILES: **species-match 100% → reward 1**
- `pytest tests/test_outputs.py`: **4/4 pass** (gate sane, reward files consistent, scoring is
  species-not-InChIKey, oracle floor = 1.0)

## Container reality / Docker

Harbor runs agents in **containers** (Docker locally; Daytona/Modal/E2B/Runloop are paid
cloud backends needing API keys). **No local non-container backend exists.** Authoring +
local verifier self-test need no container; the real agent run + `harbor analyze` do. See
`INFRA.md` for the exact prereqs Trent must provision.
