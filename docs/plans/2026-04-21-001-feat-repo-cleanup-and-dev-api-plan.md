---
title: "feat: Repo cleanup, dev API infrastructure, and stale branch cleanup"
type: feat
status: active
date: 2026-04-21
origin: docs/brainstorms/repo-cleanup-and-dev-api-requirements.md
---

# Repo Cleanup and Dev API Infrastructure

## Overview

Three independent work streams delivered as separate PRs:
1. **PR 1 — Repo Cleanup** (R1–R5): Consolidate dev guidelines into CLAUDE.md, update .gitignore, delete stale files
2. **PR 2 — Dev API Infrastructure** (R6–R10, R13): Second systemd service + GitHub Actions workflow for deploying any branch to a dev API on the same Lightsail instance
3. **PR 3 — Stale Branch Cleanup** (R11–R12): Delete merged remote branches and stale local branches

All PRs are pushed to the `trentleslie/biomapper2` fork and opened against `Phenome-Health/biomapper2:main` to get Greptile review.

## Problem Frame

No way to test API changes on the server without deploying to production. The repo also has accumulated untracked files and stale branches. (see origin: `docs/brainstorms/repo-cleanup-and-dev-api-requirements.md`)

## Requirements Trace

- R1. Pull local main up to date with origin/main
- R2. Delete untracked files
- R3. Consolidate dev_guidelines.md into CLAUDE.md
- R4. Add data/review/ and notebooks/ to .gitignore
- R5. All new commits on a feature branch
- R6. Create biomapper2-api-dev systemd service (port 8002, 1 worker, localhost, log separation)
- R7. Separate .env with its own KESTREL_API_KEY
- R8. GitHub Actions deploy-dev-api.yml with workflow_dispatch + branch input
- R9. Idempotent deploy (clone or update, uv sync, mkdir, restart, fail on health check failure)
- R10. Health check: poll every 2s for 30s, fail workflow if no 200
- R11. Verify and delete merged remote branches
- R12. Delete stale local branches
- R13. Document the dev API setup, deployment trigger, and log access in deploy/README.md

## Scope Boundaries

- No changes to the production deployment workflow or service
- No DNS/subdomain for dev API (localhost only; access from laptops via SSH tunnel: `ssh -L 8002:localhost:8002 ubuntu@<host>`)
- No Docker — bare-metal uv + systemd
- No shared state between dev and prod
- `data/review/` and `notebooks/` kept locally

### Deferred to Separate Tasks

- External access to dev API (requires auth story): future iteration
- Dev API monitoring/alerting: not needed for a dev instance

## Context & Research

### Relevant Code and Patterns

- `deploy/biomapper2-api.service` — production systemd unit to mirror for dev variant
- `.github/workflows/deploy-api.yml` — production deploy workflow to mirror for dev variant
- `.github/workflows/ci.yml` — CI workflow; uses `actions/checkout@v5`, `actions/setup-python@v6`
- `deploy/README.md` — deployment docs with initial setup steps
- `src/biomapper2/config.py` — loads `KESTREL_API_KEY`, `KESTREL_API_URL` from .env
- `src/biomapper2/api/auth.py` — loads `BIOMAPPER2_API_KEYS` (comma-separated) or `BIOMAPPER_API_KEY` (fallback)
- `CLAUDE.md` — current project instructions (merge target for dev_guidelines.md)
- `dev_guidelines.md` — source content to merge

### Environment Variables for Dev .env

| Variable | Required | Notes |
|----------|----------|-------|
| `KESTREL_API_KEY` | Yes | Separate value from prod for blast-radius isolation |
| `BIOMAPPER2_API_KEYS` | Recommended | API auth keys; can differ from prod or omit for open dev access |
| `KESTREL_API_URL` | No | Defaults to the main Kestrel KG endpoint (shared with prod API); only set if targeting a different KG |

## Key Technical Decisions

- **Fork-based PRs**: Push to `trentleslie/biomapper2`, open PRs against `Phenome-Health/biomapper2:main` for Greptile review (see origin)
- **1 worker for dev**: Instance has 6.2 GB available; prod uses ~280 MB at 2 workers; 1 worker (~185 MB) is sufficient (see origin)
- **Localhost binding**: Dev at `127.0.0.1:8002`, not `0.0.0.0` (see origin)
- **Unconditional uv sync**: Always run on deploy — safety is worth the ~10s cost for a manual-trigger workflow
- **appleboy/ssh-action@v1.0.3**: Same SSH action as production workflow for consistency
- **Same GitHub secrets**: `LIGHTSAIL_HOST` and `LIGHTSAIL_SSH_KEY` work for both services (same instance)
- **Fork remote on server**: The server's `~/biomapper2-dev` checkout adds `trentleslie/biomapper2` as a second remote (`fork`) so feature branches can be deployed during the Greptile review phase before they're pushed to Phenome-Health. The workflow accepts an optional `remote` input (default: `origin`) to select which remote to fetch/deploy from
- **CLAUDE.md dedup rule**: Where dev_guidelines.md overlaps with CLAUDE.md, keep the more detailed version. When both versions contain unique useful content, merge them rather than choosing one (e.g., if CLAUDE.md has notes and dev_guidelines has an examples column, combine both)

## Open Questions

### Resolved During Planning

- **Dev .env contents**: Needs `KESTREL_API_KEY` (separate value) and `BIOMAPPER2_API_KEYS` for API auth. `KESTREL_API_URL` optional (defaults to prod KG). Same variable names, different values in a different `.env` file
- **uv sync strategy**: Unconditional — safer for manual workflow, negligible cost
- **milestone branch**: Add to cleanup list — fully merged, zero commits ahead, no semantic reason to preserve
- **GitHub environment for dev workflow**: Use `development` environment (separate from `production`); same secrets but cleaner separation

### Deferred to Implementation

- **Exact content diff for CLAUDE.md merge**: Must diff dev_guidelines.md against CLAUDE.md section-by-section during implementation to catch any content that wasn't called out in the requirements
- **gh auth**: User has expired `GITHUB_TOKEN` env var; needs to `unset GITHUB_TOKEN` and `gh auth login` before pushing to fork

## Implementation Units

### PR 1: Repo Cleanup (R1–R5)

- [ ] **Unit 1: Sync main and set up feature branch**

**Goal:** Get local main current, delete stale untracked files, create feature branch, add fork remote

**Requirements:** R1, R2, R5

**Dependencies:** None

**Files:**
- Delete: `docs/ARPA-H_Milestone_Report_Oct2025_Mar2026.md`, `docs/KRAKEN_SYSTEM_PROMPT.md`, `progress.md`

**Approach:**
- Fast-forward local main to origin/main
- Delete the three files specified in R2 (local filesystem deletions that will become commits on the feature branch via `git add -u`)
- Add fork remote: `git remote add fork https://github.com/trentleslie/biomapper2.git`
- Create and checkout feature branch from updated main (e.g., `chore/repo-cleanup`)

**Test expectation:** none — git operations only, no behavioral change

**Verification:**
- `git log --oneline -1` matches `origin/main`
- The three deleted files no longer exist on disk
- `git remote -v` shows both `origin` and `fork`
- On the new feature branch, not main

---

- [ ] **Unit 2: Consolidate dev_guidelines.md into CLAUDE.md**

**Goal:** Merge useful content from dev_guidelines.md into CLAUDE.md, then delete dev_guidelines.md

**Requirements:** R3

**Dependencies:** Unit 1

**Files:**
- Modify: `CLAUDE.md`
- Delete: `dev_guidelines.md`

**Approach:**
- Diff both files section by section. The research identified these as NEW content in dev_guidelines.md (not already in CLAUDE.md):
  - **Development Workflow** section (branching strategy, PR flow, auto-sync to arpanauts mention)
  - **Code Style** section (type hints/docstrings guidance with example)
  - **IDE Setup** section (Ruff, Black, Pyright extensions)
  - **Project Tracking** section (GitHub Issues, Kanban board workflow, labels)
  - **Dependency Management** section (explicit `uv add` + commit both files pattern)
- These sections OVERLAP and dev_guidelines has the richer version:
  - Commit convention table (dev_guidelines has examples column — use it)
  - Working with Claude Code / Claude Code Workflow (dev_guidelines has a 5-step review workflow)
- Add new sections to CLAUDE.md grouped logically (workflow/tracking together, code style/IDE together)
- Replace the commit convention one-liner with the richer table
- Expand the Claude Code Workflow section with the review steps
- Delete dev_guidelines.md after merge is complete

**Patterns to follow:**
- Keep CLAUDE.md's existing section ordering (Build commands, Code Quality, Architecture, ...) and append new sections logically

**Test expectation:** none — documentation change only

**Verification:**
- CLAUDE.md contains all sections listed above
- No content silently dropped: after the merge, diffing pre-deletion dev_guidelines.md against the new/modified CLAUDE.md sections should show no unique useful content remaining only in dev_guidelines.md
- dev_guidelines.md is deleted
- `./scripts/check.sh` still passes (no code changes)

---

- [ ] **Unit 3: Update .gitignore**

**Goal:** Add data/review/ and notebooks/ to .gitignore to prevent accidental commits

**Requirements:** R4

**Dependencies:** Unit 1

**Files:**
- Modify: `.gitignore`

**Approach:**
- First verify no files in `data/review/` or `notebooks/` are currently tracked (they shouldn't be — `data/review/` is untracked and `notebooks/` ipynb files are already ignored by the `*.ipynb` pattern)
- If any are tracked, run `git rm --cached` before the .gitignore change
- Add entries under the existing "Data" section:
  ```
  data/review/
  ```
  And under a "Notebooks" or "Exploration" comment:
  ```
  notebooks/
  ```

**Test expectation:** none — config change only

**Verification:**
- `git status` no longer shows `data/review/` or `notebooks/` as untracked
- Files still exist locally on disk

---

- [ ] **Unit 4: Push and create PR 1**

**Goal:** Push repo cleanup branch to fork, open PR against Phenome-Health/biomapper2:main

**Requirements:** R5

**Dependencies:** Units 2, 3

**Files:** none (git operations only)

**Approach:**
- Push feature branch to `fork` remote
- Create PR from `trentleslie/biomapper2:<branch>` to `Phenome-Health/biomapper2:main`
- PR title: `chore: consolidate dev guidelines and clean up repo`

**Test expectation:** none — PR operations only

**Verification:**
- PR is open and visible on GitHub
- CI passes on the PR

---

### PR 2: Dev API Infrastructure (R6–R10, R13)

- [ ] **Unit 5: Create dev systemd service file**

**Goal:** Create the systemd unit file for the dev API service

**Requirements:** R6, R7

**Dependencies:** None (can start in parallel with PR 1; on the critical path to server validation via Unit 8 → Unit 9)

**Files:**
- Create: `deploy/biomapper2-api-dev.service`

**Approach:**
- Clone from `deploy/biomapper2-api.service` with these changes:
  - `Description`: `Biomapper2 REST API (Development)`
  - `WorkingDirectory`: `/home/ubuntu/biomapper2-dev`
  - `EnvironmentFile`: `/home/ubuntu/biomapper2-dev/.env`
  - `ExecStart`: `/home/ubuntu/.local/bin/uv run uvicorn biomapper2.api.main:app --host 127.0.0.1 --port 8002 --workers 1`
  - `SyslogIdentifier`: `biomapper2-api-dev`
  - `ReadWritePaths`: `/home/ubuntu/biomapper2-dev/results /home/ubuntu/biomapper2-dev/cache`
- All other directives stay the same, notably: `Environment="PATH=/home/ubuntu/.local/bin:..."`, security hardening (`ProtectHome`, `NoNewPrivileges`, etc.), restart policy, user/group

**Patterns to follow:**
- `deploy/biomapper2-api.service` — mirror structure exactly

**Test scenarios:**
- Happy path: service file parses correctly (run `systemd-analyze verify deploy/biomapper2-api-dev.service` in CI on ubuntu-latest)
- Edge case: WorkingDirectory, EnvironmentFile, ReadWritePaths, and SyslogIdentifier all point to dev paths, not prod paths
- Error path: `ProtectHome=read-only` is preserved; ReadWritePaths explicitly allows dev cache/results

**Verification:**
- `diff deploy/biomapper2-api.service deploy/biomapper2-api-dev.service` shows only the expected path/port/worker/syslog changes

---

- [ ] **Unit 6: Create dev deploy GitHub Actions workflow**

**Goal:** Create the workflow_dispatch workflow that deploys any branch to the dev API

**Requirements:** R8, R9, R10

**Dependencies:** Unit 5 (the service file must exist for the workflow to install it)

**Files:**
- Create: `.github/workflows/deploy-dev-api.yml`

**Approach:**
- Trigger: `workflow_dispatch` only, with two inputs:
  - `inputs.branch` (string, required, default: `main`) — the branch to deploy
  - `inputs.remote` (string, required, default: `origin`) — which remote to fetch from (`origin` = Phenome-Health, `fork` = trentleslie)
- Environment: `development` (prerequisite: verify that `LIGHTSAIL_HOST` and `LIGHTSAIL_SSH_KEY` are accessible from this environment — if they're scoped to `production` only, duplicate them to `development` via the GitHub UI before merging)
- Single job using `appleboy/ssh-action@v1.0.3` with same SSH secrets as prod
- SSH script must be idempotent — handle fresh clone OR existing checkout:
  1. Check if `~/biomapper2-dev` exists; if not, `git clone https://github.com/Phenome-Health/biomapper2.git ~/biomapper2-dev`
  1b. Ensure fork remote exists (idempotent): `cd ~/biomapper2-dev && git remote get-url fork >/dev/null 2>&1 || git remote add fork https://github.com/trentleslie/biomapper2.git`
  2. `git fetch <remote>`
  3. `git checkout -B <branch> <remote>/<branch>` (idempotent: creates or resets the local branch to the remote ref; avoids ambiguity with two remotes)
  4. `UV_BIN="${UV_BIN:-$HOME/.local/bin/uv}" && "$UV_BIN" sync` (unconditional; uses full path since SSH sessions may not load shell profile; overridable via `UV_BIN` env var if uv is installed elsewhere)
  5. `mkdir -p results cache`
  6. `sudo cp deploy/biomapper2-api-dev.service /etc/systemd/system/` (note: this copies from the deployed branch — service file changes from feature branches persist until the next deploy)
  7. `sudo systemctl daemon-reload && sudo systemctl enable biomapper2-api-dev && sudo systemctl restart biomapper2-api-dev`
  8. Health check loop: poll `http://localhost:8002/api/v1/health` every 2 seconds for up to 30 seconds; exit non-zero if no 200
- Failure notification step (same pattern as production)

**Patterns to follow:**
- `.github/workflows/deploy-api.yml` — mirror structure, adapt for dev paths and branch input

**Test scenarios:**
- Happy path: workflow_dispatch with branch `main`, remote `origin` deploys successfully, health check returns 200
- Happy path: workflow_dispatch with a feature branch on `fork` remote deploys that branch
- Edge case: first-ever deploy (no `~/biomapper2-dev` directory) — should clone, add fork remote, and succeed
- Error path: health check timeout — workflow exits non-zero, no silent green deploy
- Error path: invalid branch name — `git checkout` fails, workflow exits non-zero

**Verification:**
- Workflow file passes GitHub Actions syntax validation
- Manual trigger shows the branch input field in the GitHub UI
- Successful deploy shows health check passing in the Actions log

---

- [ ] **Unit 7: Update deploy README with dev setup instructions**

**Goal:** Document the dev API setup in the existing deploy README

**Requirements:** R13

**Dependencies:** Units 5, 6

**Files:**
- Modify: `deploy/README.md`

**Approach:**
- Add a "Development API" section after the existing production docs
- Include: purpose, port, one-time server setup steps (clone, create .env, enable service), how to trigger a deploy via GitHub Actions, log viewing with `journalctl -t biomapper2-api-dev`
- Document the dev `.env` template (KESTREL_API_KEY, BIOMAPPER2_API_KEYS)

**Patterns to follow:**
- Existing `deploy/README.md` format and tone

**Test expectation:** none — documentation only

**Verification:**
- README covers initial setup, deployment trigger, and log access

---

- [ ] **Unit 8: Push and create PR 2**

**Goal:** Push dev API infrastructure branch to fork, open PR

**Requirements:** R6–R10, R13

**Dependencies:** Units 5, 6, 7

**Files:** none (git operations only)

**Approach:**
- Create feature branch (e.g., `feat/dev-api-infrastructure`) from updated main
- Push to `fork` remote
- Create PR from `trentleslie/biomapper2:<branch>` to `Phenome-Health/biomapper2:main`
- PR title: `feat: add dev API deployment infrastructure`

**Test expectation:** none — PR operations only

**Verification:**
- PR is open, CI passes

---

- [ ] **Unit 9: One-time server setup**

**Goal:** Set up the dev checkout, .env, and service on the Lightsail instance. Done before PR 2 merge so the service is validated independently of the workflow

**Requirements:** R6, R7

**Dependencies:** Unit 8 (branch must be pushed to fork so the server can fetch it). Sequence: Units 5-7 → Unit 8 (push) → Unit 9 (validate on server) → merge PR 2

**Files:** none (server operations)

**Approach:**
- SSH into the Lightsail instance
- Clone the repo to `~/biomapper2-dev` and add fork remote: `git clone https://github.com/Phenome-Health/biomapper2.git ~/biomapper2-dev && cd ~/biomapper2-dev && git remote add fork https://github.com/trentleslie/biomapper2.git` (this clone establishes the directory and remotes; main does not yet contain the dev service file)
- Checkout the feature branch with the service file: `git fetch fork && git checkout feat/dev-api-infrastructure` (the service file and workflow come from this branch, not main)
- Create `~/biomapper2-dev/.env` with separate `KESTREL_API_KEY` and `BIOMAPPER2_API_KEYS` values
- Copy the service file: `sudo cp ~/biomapper2-dev/deploy/biomapper2-api-dev.service /etc/systemd/system/`
- Enable and start: `sudo systemctl daemon-reload && sudo systemctl enable biomapper2-api-dev && sudo systemctl start biomapper2-api-dev`
- Verify health: `curl http://localhost:8002/api/v1/health`
- Verify logs: `journalctl -t biomapper2-api-dev --no-pager -n 5`

**Test scenarios:**
- Happy path: health endpoint returns 200, logs show startup messages under `biomapper2-api-dev` identifier
- Integration: prod API still responds normally on port 8001 after dev service starts

**Verification:**
- Both services running simultaneously (`systemctl status biomapper2-api biomapper2-api-dev`)
- Dev API responds: `curl http://localhost:8002/api/v1/health`
- Prod API unaffected: `curl http://localhost:8001/api/v1/health`
- Logs separated: `journalctl -t biomapper2-api-dev` shows only dev entries

---

### PR 3: Stale Branch Cleanup (R11–R12)

- [ ] **Unit 10: Verify and delete merged remote branches**

**Goal:** Clean up confirmed-merged remote branches

**Requirements:** R11

**Dependencies:** None (independent of PRs 1 and 2)

**Files:** none (git operations only)

**Approach:**
- For each candidate branch, verify merge status with `git merge-base --is-ancestor origin/<branch> origin/main`
- Delete confirmed-merged branches: `feature/60-dockerize`, `feature/rest-api`, `44-batch-bulk-requests-to-kestrel`, `2-switch-to-pydantic-for-entity-model-internally`, `api-patch-1`, `17-repo-mirror`, `milestone`
- For any NOT-merged branch, print `SKIP: <branch> (not merged into main)` to stdout and continue with remaining branches. Do not fail the script
- Preserve: `explore/kg-o1-paper`, `feature/kestrel-evaluation-analysis`

**Test scenarios:**
- Happy path: all 7 candidates verified as merged, all deleted
- Edge case: one or more candidates NOT merged — printed as SKIP, remaining branches still cleaned up

**Verification:**
- `git branch -r` no longer shows the deleted branches
- `explore/kg-o1-paper` and `feature/kestrel-evaluation-analysis` still exist

---

- [ ] **Unit 11: Delete stale local branches**

**Goal:** Clean up local branches that are no longer needed

**Requirements:** R12

**Dependencies:** None

**Files:** none (git operations only)

**Approach:**
- Delete `explore/kg-o1-paper` and `feature/kestrel-evaluation-analysis` locally to keep `git branch` clean. Safe because the remote counterparts are being preserved on origin — work is not lost

**Test expectation:** none — git operations only

**Verification:**
- `git branch` shows only `main` and any active feature branches

## System-Wide Impact

- **Interaction graph:** The dev service is a fully independent instance — no callbacks, middleware, or shared state with production. Shared resources: Lightsail instance CPU/RAM/disk and the external Kestrel KG API endpoint (both services default to the same `KESTREL_API_URL`; heavy concurrent usage could impact KG API rate limits)
- **Error propagation:** A broken dev deploy fails the GitHub Action but does not affect production. A crashing dev service restarts via systemd but does not impact prod
- **State lifecycle risks:** None — separate git checkouts, separate .env files, separate results/cache directories
- **API surface parity:** Dev API serves the same endpoints as prod (same codebase, different branch). No additional API surface created
- **Unchanged invariants:** Production deploy workflow, production systemd service, and production .env are not modified by any unit in this plan

## Risks & Dependencies

| Risk | Mitigation |
|------|------------|
| gh auth failure blocks PR creation | User must `unset GITHUB_TOKEN && gh auth login` before execution |
| Dev service file has wrong paths | Unit 5 test: diff against prod to verify only expected changes |
| Health check loop timing too tight | 30s with 2s polling gives 15 attempts — generous for a uvicorn startup |
| Server setup requires manual SSH | Documented in Unit 9; could be automated later but not in scope |
| Fork not synced with upstream | Fork currently synced; re-sync before pushing if upstream has advanced since this plan was written |
| workflow_dispatch not testable before merge | Can test via `gh workflow run deploy-dev-api.yml --ref <branch>` if the workflow file exists on a branch GitHub can see. Otherwise validate YAML syntax and structure via code review |
| Service file overwritten on every deploy | Feature branch deploys copy their version of the service file to systemd; persists until next deploy. Acceptable for a dev service — noted in workflow comment |

## Documentation / Operational Notes

- `deploy/README.md` updated with dev API setup instructions (Unit 7)
- CLAUDE.md updated with consolidated dev guidelines (Unit 2)
- One-time server setup (Unit 9) happens before PR 2 merge — validates the service independently, then the workflow automates future deploys

## Sources & References

- **Origin document:** [docs/brainstorms/repo-cleanup-and-dev-api-requirements.md](docs/brainstorms/repo-cleanup-and-dev-api-requirements.md)
- Production service: `deploy/biomapper2-api.service`
- Production workflow: `.github/workflows/deploy-api.yml`
- Deploy docs: `deploy/README.md`
- API config: `src/biomapper2/config.py`
- API auth: `src/biomapper2/api/auth.py`
