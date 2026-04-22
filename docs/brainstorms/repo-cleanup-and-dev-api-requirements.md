---
date: 2026-04-21
topic: repo-cleanup-and-dev-api
---

# Repo Cleanup and Dev API Setup

## Problem Frame

The biomapper2 repo has accumulated untracked working files, the local `main` is 2 commits behind origin, and there is no way to test API changes on the server without deploying to production. This work cleans up the repo state and establishes a standard dev API alongside the existing production deployment on AWS Lightsail.

## Requirements

**Branch and Repo Cleanup**

- R1. Pull local `main` up to date with `origin/main` (fast-forward, 2 commits behind)
- R2. Delete untracked files: `docs/ARPA-H_Milestone_Report_Oct2025_Mar2026.md`, `docs/KRAKEN_SYSTEM_PROMPT.md`, `progress.md`
- R3. Incorporate useful content from `dev_guidelines.md` into `CLAUDE.md`, then delete `dev_guidelines.md`. Planning step should diff both files and produce a consolidation list before editing, so nothing gets quietly dropped. Key additions: auto-sync to arpanauts mention, project tracking workflow (GitHub Issues/Kanban), IDE setup suggestions, expanded Claude Code PR review workflow. Where content overlaps (commit conventions, test guidelines, PR workflow), deduplicate in favor of the more detailed version
- R4. Add `data/review/` and `notebooks/` to `.gitignore` (keep files locally, prevent accidental commits). Implementation note: verify no files in these dirs are already tracked; if so, `git rm --cached` is needed before `.gitignore` takes effect
- R5. All new commits (R3, R4, and subsequent work) go on a feature branch, not `main`

**Dev API on AWS Lightsail**

- R6. Create a second systemd service (`biomapper2-api-dev`) running 1 worker on port 8002, bound to `127.0.0.1` (not `0.0.0.0`), from a separate checkout (`~/biomapper2-dev`) on the same Lightsail instance. The service file must set `ReadWritePaths` to the dev checkout's `results/` and `cache/` directories (mirroring production's security directives). Must set `SyslogIdentifier=biomapper2-api-dev` for log separation (`journalctl -t biomapper2-api-dev` gives dev-only logs)
- R7. Dev service uses its own `.env` file with a separate `KESTREL_API_KEY` value (same env var name, different value in a different `.env` file) for blast-radius isolation (prevents a buggy dev branch from burning the production key's rate limit, and allows independent revocation)
- R8. Create a GitHub Actions workflow (`deploy-dev-api.yml`) triggered only by `workflow_dispatch` with a branch name input parameter
- R9. The dev deploy workflow must be idempotent: handle both initial clone and subsequent updates to `~/biomapper2-dev`, run `uv sync` unconditionally, ensure `results/` and `cache/` directories exist, and restart `biomapper2-api-dev`. The workflow must exit non-zero if the health check fails
- R10. Dev API health check: the GitHub Action must poll `http://localhost:8002/api/v1/health` every 2 seconds for up to 30 seconds after service restart, and fail the workflow if it doesn't return 200 within that window. No green deploys with a broken service

**Stale Branch Cleanup**

- R11. Verify each candidate branch is actually merged before deleting (use `git merge-base --is-ancestor`). Clean up confirmed-merged remote branches: `feature/60-dockerize`, `feature/rest-api`, `44-batch-bulk-requests-to-kestrel`, `2-switch-to-pydantic-for-entity-model-internally`, `api-patch-1`, `17-repo-mirror`, `milestone` (fully merged, zero commits ahead of main, no semantic reason to preserve)
- R12. Delete stale local branches: `explore/kg-o1-paper`, `feature/kestrel-evaluation-analysis` (or confirm they should be kept)

## Success Criteria

- `git status` on main is clean (no untracked files that shouldn't be there)
- `CLAUDE.md` contains the consolidated dev guidelines
- Dev API can be deployed to any branch via GitHub Actions manual trigger
- Production API on port 8001 is completely unaffected by dev deployments
- Both services can run simultaneously on the Lightsail instance
- Prod API latency check: capture p50/p95 on `/api/v1/health` for 5 min before dev service starts, then 5 min after; p95 delta should be within noise (<10%)

## Scope Boundaries

- No changes to the production deployment workflow or service
- No DNS/subdomain setup for the dev API (just port 8002 on the same host, localhost only)
- No Docker-based deployment — both services run bare-metal with uv + systemd
- No shared state between dev and prod (separate `results/`, `cache/`, `.env`, git checkout)
- `data/review/` and `notebooks/` are kept locally for later review, not deleted

## Key Decisions

- **Same server, different port**: Dev API runs alongside prod on port 8002. Chosen for simplicity and zero additional cost
- **Manual deploy only**: Dev API uses `workflow_dispatch` (not auto-deploy on branch push). Avoids noise from multiple contributors/branches
- **Separate git checkout**: `~/biomapper2-dev` is a full clone, not a worktree. Avoids complexity and allows independent branch state
- **Separate API key for dev**: Cheap blast-radius isolation even though the same key would work
- **Localhost binding for dev**: Dev API binds to `127.0.0.1:8002`, not exposed externally. External access is a separate decision requiring its own auth story
- **1 worker for dev**: Instance has 7.6 GB RAM with 6.2 GB available; prod uses ~280 MB at 2 workers. 1 worker for dev (~185 MB) is sufficient for testing and leaves ample margin for the other services on the box (streamlit, kraken-chatbot, etc.)

## Dependencies / Assumptions

- SSH access to the Lightsail instance is already configured in GitHub Actions secrets (`LIGHTSAIL_HOST`, `LIGHTSAIL_SSH_KEY`)
- Port 8002 is available on localhost (no firewall issues for loopback)
- Instance resources confirmed: 7.6 GB RAM (6.2 GB available), 2 vCPUs, 126 GB disk free — comfortably supports a second service

## Outstanding Questions

### Deferred to Planning

- [Affects R7][Technical] Does the dev `.env` need any different config values beyond a separate API key?

## Next Steps

-> `/ce:plan` for structured implementation planning
