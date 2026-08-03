# Infra prereqs for a REAL Harbor run (Trent's to provision)

The task artifact and the local verifier self-test need **no container**. The real
tool-using-agent run and the mandatory `harbor analyze` failure analysis **do**. This box
has only `uv` — **no Docker, Podman, Daytona**. Installing a container runtime is a
sudo/system change and is **Trent's to do**; this agent did not attempt it.

## What Harbor requires (verified against harborframework.com/docs + the live repo, 2026-07-22)

- Harbor runs each agent attempt in a **container**. Local execution requires **Docker
  installed and running**. The other supported backends — **Daytona, Modal, E2B, Runloop** —
  are **cloud sandboxes that need a paid API key** (e.g. `DAYTONA_API_KEY`). There is **no
  local non-container / subprocess backend**. So the real run is blocked until a runtime exists.
- Task format confirmed from a live TB-Science task (`tasks/life-sciences/biology/ont-tn-qc`):
  `task.toml` (top-level `schema_version`, `artifacts`, `[metadata]`, `[verifier]
  environment_mode="separate"`, `[agent]`, `[environment]` with **`allow_internet`** — the
  current schema uses `allow_internet=false` for no-network, not `network_mode`), plus
  `instruction.md`, `environment/Dockerfile`, `tests/{test.sh,test_outputs.py,Dockerfile}`,
  `solution/{solve.sh,...}`. The lipid task matches this shape.

## Steps for Trent to run the real thing

```bash
# 1. Install Docker (sudo; Trent's task) — e.g. Pop!_OS / Ubuntu:
#    sudo apt-get install docker.io && sudo usermod -aG docker $USER   (re-login)
#    verify: docker run --rm hello-world

# 2. Get Harbor + the TB-Science harness (uv is already present):
uv tool install harbor            # or: pipx install harbor  (confirm pkg name in the docs)
git clone https://github.com/harbor-framework/terminal-bench-science

# 3. Drop the task in and build/validate locally (Docker backend):
cp -r <worktree>/studies/external_benchmarks/harbor_tasks/lipid-shorthand-structure \
      terminal-bench-science/tasks/physical-sciences/chemistry/lipid-shorthand-structure
#    build the two images, run the oracle (must pass) + no-op (must fail):
harbor task build   lipid-shorthand-structure
harbor task test    lipid-shorthand-structure          # oracle solve.sh -> reward 1
harbor run --agent <claude|gpt> --task lipid-shorthand-structure --n-attempts 20

# 4. Mandatory difficulty read (the PR checklist requires it):
harbor analyze <run-dir>          # confirm 10-20% solve + meaningful (chemistry) failures
```

## Calibration note (the too-easy question)

`LIPID_PASS_THRESHOLD` (default **0.40** in `tests/grade.py`) is the difficulty dial: reward
= 1 iff the agent's species-match rate over the ~68 gradeable names ≥ threshold. The naive
thinking-disabled baseline is 13.2%; a code-executing agent will score higher. Tune the
threshold on the real run so the empirical **solve rate lands in 10–20%** — that is what
`harbor analyze` validates. If a code-writing agent blows past any defensible threshold
(scripts sum-composition→formula→SMILES near-deterministically via pygoslin-equivalent
logic), the task is TOO-EASY and should be hardened (stricter resolution, or a
sphingo/glyco-only stratum) before submission.
