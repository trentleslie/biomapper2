"""Comprehensive Arm-M characterization across NECS-anchored pairs, TWO arms, KG-independent certificate.

For each pair NECS↔{Arivale, Xu, LLFS, BLSA}, resolve both panels through a BASELINE dev API and a
TREATMENT dev API (e.g. re-resolution off vs on), form the Arm-M CURIE-intersection links per arm, and
adjudicate each link with the KG-INDEPENDENT certificate (PubChem-by-name oracle: connectivity-only,
never the KG node). Emits a per-pair table with baseline / treatment / delta for links + certified /
refuted / refused + certified-rate.

This is a CHARACTERIZATION, not the gated promotion verdict: it is single-shot per arm (no cold-cache
canary, no >=3-replicate noise floor, no positive-control plant). Numbers describe the arms; they do NOT
authorize a promotion — that is the conflation gate's job. Lipid (sum-composition) names PubChem cannot
structure are `refused`, so the certified/refuted signal is small-molecule-dominated (state this when
reporting).

SUPERVISED live operator step (two dev APIs via SSH tunnel; live PubChem). NEVER invoked from pytest;
the live loop is `# pragma: no cover`. Resumable per-arm/per-name caches on disk (R23). Config via env:
``BASELINE_API`` + ``TREATMENT_API`` (full /api/v1/map/batch URLs), key at ``/tmp/.bmk``.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from studies.external_benchmarks.scorers.cross_cohort_overlap import curie_set, link_by_intersection
from studies.external_benchmarks.scorers.independent_link_certificate_overlap import CertifiedOverlap, certify_links

_METRICS = ("certified", "refuted", "refused")


@dataclass(frozen=True)
class ArmPairResult:
    """One arm's Arm-M result for one pair: the overlap link count + the certificate counts."""

    n_links: int
    n_necs_linked: int
    n_cohort_linked: int
    certified: CertifiedOverlap


def delta_row(pair: str, base: ArmPairResult, treat: ArmPairResult) -> dict:
    """Per-pair baseline/treatment/delta row (pure). Raw counts AND rates, since the two arms may link
    different numbers of pairs — a certified-count change alone conflates coverage with correctness."""

    def _rate(c: CertifiedOverlap) -> float | None:
        return c.certified_rate

    row: dict[str, object] = {"pair": pair}
    row["links_base"] = base.n_links
    row["links_treat"] = treat.n_links
    row["links_delta"] = treat.n_links - base.n_links
    for m in _METRICS:
        b = getattr(base.certified, m)
        t = getattr(treat.certified, m)
        row[f"{m}_base"] = b
        row[f"{m}_treat"] = t
        row[f"{m}_delta"] = t - b
    rb, rt = _rate(base.certified), _rate(treat.certified)
    row["certrate_base"] = None if rb is None else round(rb, 4)
    row["certrate_treat"] = None if rt is None else round(rt, 4)
    row["certrate_delta"] = None if (rb is None or rt is None) else round(rt - rb, 4)
    return row


def _btd(base: int, treat: int) -> str:
    """A 'base/treat/+delta' cell."""
    return f"{base}/{treat}/{treat - base:+d}"


def _rate_cell(base: object, treat: object, delta: object) -> str:
    def r(v: object) -> str:
        return "-" if v is None else f"{float(v):.3f}"

    return f"{r(base)}/{r(treat)}/{r(delta)}"


def render_table(rows: list[dict]) -> str:
    """Fixed-width per-pair table + a TOTAL row (pure). Cells are base/treat/signed-delta; rates 3dp."""
    cols = ("pair", "links(b/t/d)", "certified(b/t/d)", "refuted(b/t/d)", "refused(b/t/d)", "cert-rate(b/t/d)")
    widths = (10, 16, 20, 18, 18, 22)
    header = " ".join(c.ljust(w) if i == 0 else c.rjust(w) for i, (c, w) in enumerate(zip(cols, widths)))
    lines = [header, "-" * len(header)]
    tot = {
        k: 0
        for k in ("links_base", "links_treat", "certified_base", "certified_treat",
                  "refuted_base", "refuted_treat", "refused_base", "refused_treat")
    }
    for r in rows:
        for k in tot:
            tot[k] += int(r[k])
        cells = (
            str(r["pair"]).ljust(widths[0]),
            _btd(int(r["links_base"]), int(r["links_treat"])).rjust(widths[1]),
            _btd(int(r["certified_base"]), int(r["certified_treat"])).rjust(widths[2]),
            _btd(int(r["refuted_base"]), int(r["refuted_treat"])).rjust(widths[3]),
            _btd(int(r["refused_base"]), int(r["refused_treat"])).rjust(widths[4]),
            _rate_cell(r["certrate_base"], r["certrate_treat"], r["certrate_delta"]).rjust(widths[5]),
        )
        lines.append(" ".join(cells))
    lines.append("-" * len(header))

    def _agg_rate(certified: int, refuted: int) -> float | None:
        adj = certified + refuted
        return certified / adj if adj else None

    rate_base = _agg_rate(tot["certified_base"], tot["refuted_base"])
    rate_treat = _agg_rate(tot["certified_treat"], tot["refuted_treat"])
    rate_delta = None if (rate_base is None or rate_treat is None) else round(rate_treat - rate_base, 4)
    total_cells = (
        "TOTAL".ljust(widths[0]),
        _btd(tot["links_base"], tot["links_treat"]).rjust(widths[1]),
        _btd(tot["certified_base"], tot["certified_treat"]).rjust(widths[2]),
        _btd(tot["refuted_base"], tot["refuted_treat"]).rjust(widths[3]),
        _btd(tot["refused_base"], tot["refused_treat"]).rjust(widths[4]),
        _rate_cell(
            None if rate_base is None else round(rate_base, 4),
            None if rate_treat is None else round(rate_treat, 4),
            rate_delta,
        ).rjust(widths[5]),
    )
    lines.append(" ".join(total_cells))
    return "\n".join(lines)


# --- LIVE, SUPERVISED (never in pytest) ------------------------------------------------------------


def _metagraph_fingerprint(payload: dict) -> str:
    """Pure: a stable short hash of a Kestrel ``/metagraph`` payload (the graph's own build account).

    Hashes the ENTIRE payload (identity, per-prefix counts, knowledge sources, category/triple lists),
    so any change the graph reports — including edge rewiring on a same-endpoint redeploy — moves the
    hash. Folded into the run_key so a resumed run cannot reuse another deployment's cached CURIEs.
    """
    return "mg:" + hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _kg_fingerprint() -> str:  # pragma: no cover - live network
    """Live KG build identity from Kestrel ``/metagraph`` when a Kestrel URL is set, else "".

    Returns "" when no Kestrel URL is configured (caller then requires CHARAC_KG_BUILD). A configured but
    unreachable URL aborts: keying the run on an unverified build is the stale-cache hole this closes.
    """
    import os as _os

    import requests

    url = (_os.environ.get("CHARAC_KESTREL_URL") or _os.environ.get("KESTREL_API_URL") or "").strip()
    if not url:
        return ""
    try:
        r = requests.get(f"{url.rstrip('/')}/metagraph", timeout=20)
        r.raise_for_status()
        return _metagraph_fingerprint(r.json())
    except Exception as exc:
        raise SystemExit(
            f"Kestrel /metagraph probe failed for {url} ({type(exc).__name__}: {exc}) — refuse to key the "
            "run on an unverified build; fix CHARAC_KESTREL_URL/KESTREL_API_URL or set CHARAC_KG_BUILD."
        ) from exc


def _now_ts() -> str:  # pragma: no cover - trivial, live only
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def main() -> None:  # pragma: no cover - supervised live operator step; drives two dev APIs + PubChem
    import requests

    from studies.external_benchmarks.cross_cohort_run import COHORTS, load_panels
    from studies.external_benchmarks.scorers.independent_inchikey import PubChemInChIKeyResolver

    baseline_api = os.environ["BASELINE_API"]
    treatment_api = os.environ["TREATMENT_API"]
    key = Path("/tmp/.bmk").read_text().strip()

    # Restart-resumable: key the output dir on the two endpoints AND the KG build identity, so a bare
    # re-run reuses a prior dir's caches only when the DEPLOYMENT matches — a same-endpoint KG/dev-API
    # redeploy changes the /metagraph fingerprint and forces a fresh run instead of silently combining
    # stale resolutions (Greptile #63). CHARAC_FRESH=1 forces a new dir; CHARAC_OUT pins one. The build
    # identity is the live /metagraph fingerprint (CHARAC_KESTREL_URL/KESTREL_API_URL) or a manual
    # CHARAC_KG_BUILD; one is required so the deployment is always pinned.
    # Combine BOTH the live /metagraph fingerprint AND a manual CHARAC_KG_BUILD (not `or`): if a KG
    # redeploy changes mapping behavior WITHOUT changing the metagraph JSON, the live fingerprint stays
    # the same, so a bumped CHARAC_KG_BUILD must still move the run_key rather than be discarded
    # (Greptile #63). At least one must be present so the deployment is always pinned.
    kg_build = "|".join(x for x in (_kg_fingerprint(), os.environ.get("CHARAC_KG_BUILD", "").strip()) if x)
    if not kg_build:
        raise SystemExit(
            "KG build identity required: set CHARAC_KESTREL_URL (or KESTREL_API_URL) for the live "
            "/metagraph fingerprint, and/or set CHARAC_KG_BUILD and bump it on every KG redeploy — "
            "else a same-endpoint redeploy would reuse stale caches."
        )
    # A KG fingerprint does NOT capture the MAPPING API's own deployment: a dev-API redeployed behind an
    # unchanged URL with different mapping code/config, while the KG metagraph is unchanged, would still
    # match run_key and reuse stale resolutions (Greptile #63). So pin each arm's operator-attested
    # dev-API build too (the deployer is the source of truth — a config change need not bump any probe-
    # able version). Bump these on any same-endpoint dev-API redeploy, or use CHARAC_FRESH=1.
    baseline_build = os.environ.get("CHARAC_BASELINE_BUILD", "").strip()
    treatment_build = os.environ.get("CHARAC_TREATMENT_BUILD", "").strip()
    if not (baseline_build and treatment_build):
        raise SystemExit(
            "Per-arm dev-API deployment identity required: set CHARAC_BASELINE_BUILD and "
            "CHARAC_TREATMENT_BUILD (each mapping API's attested build/config) and bump them on any "
            "same-endpoint redeploy — else a dev-API redeploy behind an unchanged URL+KG would reuse "
            "stale caches."
        )
    run_key = hashlib.sha256(
        f"{baseline_api}\n{treatment_api}\n{kg_build}\n{baseline_build}\n{treatment_build}".encode()
    ).hexdigest()[:16]
    runs_root = Path.home() / "external_benchmark_runs"
    out = None
    if os.environ.get("CHARAC_OUT"):
        out = Path(os.environ["CHARAC_OUT"]).expanduser()
        # A pinned dir must belong to THIS run: if it holds caches, its manifest run_key must match, else
        # we would load another endpoint/deployment's resolutions under a mismatched manifest (Greptile #63).
        if out.exists() and any(out.glob("*.jsonl")):
            mf = out / "manifest.json"
            if not mf.exists():
                raise SystemExit(f"CHARAC_OUT {out} holds caches but no manifest — refuse to reuse; set CHARAC_FRESH=1")
            try:
                cached_key = json.loads(mf.read_text()).get("run_key")
            except (ValueError, OSError) as exc:
                raise SystemExit(f"CHARAC_OUT {out} manifest unreadable ({exc}) — refuse to reuse") from exc
            if cached_key != run_key:
                raise SystemExit(f"CHARAC_OUT {out} run_key {cached_key} != current {run_key} — refuse to mix stale caches")
    elif not os.environ.get("CHARAC_FRESH"):
        for p in sorted(runs_root.glob("cross_cohort_characterization_*"), key=lambda p: p.name, reverse=True):
            mf = p / "manifest.json"
            try:
                if mf.exists() and json.loads(mf.read_text()).get("run_key") == run_key:
                    out = p
                    break
            except (ValueError, OSError):
                continue
    ts = _now_ts()
    if out is None:
        out = runs_root / f"cross_cohort_characterization_{ts}"
    out.mkdir(parents=True, exist_ok=True)
    manifest = out / "manifest.json"

    def _manifest_run_key(m: Path) -> str | None:
        try:
            return json.loads(m.read_text()).get("run_key")
        except (ValueError, OSError):
            return None

    # Rewrite a STALE manifest (run_key differs) as well as a missing one: a pinned dir whose caches were
    # cleared but whose manifest survived would otherwise keep describing another run. The CHARAC_OUT +
    # auto-resume paths above already refuse a dir whose CACHES mismatch, so reaching here with a stale
    # manifest means no protective caches remain — rewriting is safe.
    if not manifest.exists() or _manifest_run_key(manifest) != run_key:
        manifest.write_text(
            json.dumps(
                {"run_key": run_key, "baseline_api": baseline_api, "treatment_api": treatment_api,
                 "kg_build": kg_build, "baseline_build": baseline_build, "treatment_build": treatment_build,
                 "created": ts},
                indent=2,
            )
        )
    print(f"[run] {out}\n[arms] baseline={baseline_api}\n       treatment={treatment_api}", flush=True)
    errors: dict[str, int] = {}  # "arm:label" -> count of per-entity mapping errors surfaced

    def resolve_panel(arm: str, api: str, label: str, names: list[str]) -> dict[str, dict]:
        cache_path = out / f"{arm}__{label}_devapi.jsonl"
        cache: dict[str, dict] = {}
        if cache_path.exists():
            for line in cache_path.open():
                r = json.loads(line)
                cache[r["name"]] = r
        todo = [n for n in names if n not in cache]
        run_errors = 0
        print(f"[{arm}:{label}] {len(names)} names, {len(todo)} to fetch", flush=True)
        with cache_path.open("a") as fh:
            for i in range(0, len(todo), 25):
                body = {
                    "entities": [{"name": n, "entity_type": "metabolite"} for n in todo[i : i + 25]],
                    "options": {"annotation_mode": "all"},
                }
                resp = requests.post(api, headers={"X-API-Key": key}, json=body, timeout=300)
                resp.raise_for_status()
                for r in resp.json()["results"]:
                    if r.get("error"):
                        # A transient per-entity error is NOT a completed result: do NOT cache it, so a
                        # resumed run RETRIES the name instead of inheriting a permanent failure
                        # (Greptile #63). It is surfaced in the run count below, not silently dropped.
                        run_errors += 1
                        continue
                    rec = {
                        "name": r["name"],
                        "chosen_kg_id": r.get("chosen_kg_id"),
                        "kg_equivalent_ids": r.get("kg_equivalent_ids") or {},
                    }
                    cache[r["name"]] = rec
                    fh.write(json.dumps(rec) + "\n")
                fh.flush()
        # Errored names are NOT cached (so they retry on resume) and NOT linked this run. Surfacing the
        # count keeps a partial panel from being read as a clean arm result rather than silent.
        if run_errors:
            errors[f"{arm}:{label}"] = run_errors
            print(
                f"[{arm}:{label}] WARNING: {run_errors} names returned a transient mapping error "
                "(NOT cached; retried on resume; excluded from links this run)",
                flush=True,
            )
        return cache

    def independent(names: set[str], resolver: PubChemInChIKeyResolver) -> dict[str, str | None]:
        cache_path = out / "independent_by_name.jsonl"
        got: dict[str, str | None] = {}
        if cache_path.exists():
            for line in cache_path.open():
                r = json.loads(line)
                got[r["name"]] = r["block"]
        todo = sorted(n for n in names if n not in got)
        print(f"[oracle] {len(names)} unique linked names, {len(todo)} to fetch from PubChem", flush=True)
        with cache_path.open("a") as fh:
            for n in todo:
                got[n] = resolver.block_for_name(n)
                fh.write(json.dumps({"name": n, "block": got[n]}) + "\n")
            fh.flush()
        return got

    def arm_pair(arm: str, api: str, necs: dict, coh: dict, resolver: PubChemInChIKeyResolver) -> ArmPairResult:
        necs_curie = {n: curie_set(r["chosen_kg_id"], r["kg_equivalent_ids"]) for n, r in necs.items()}
        coh_curie = {n: curie_set(r["chosen_kg_id"], r["kg_equivalent_ids"]) for n, r in coh.items()}
        ov = link_by_intersection(necs_curie, coh_curie)
        names = {lk.a_name for lk in ov.links} | {lk.b_name for lk in ov.links}
        ind = independent(names, resolver)
        cert = certify_links(ov.links, ind, ind)
        return ArmPairResult(ov.n_links, ov.n_a_linked, ov.n_b_linked, cert)

    panels = load_panels()
    resolver = PubChemInChIKeyResolver()
    necs_by_arm = {
        "baseline": resolve_panel("baseline", baseline_api, "necs", panels["necs"]),
        "treatment": resolve_panel("treatment", treatment_api, "necs", panels["necs"]),
    }
    # Resolve ALL panels FIRST, then gate on completeness: a comparison must never be produced from a
    # partial population (Greptile #63).
    coh_panels: dict[str, dict[str, dict]] = {}
    for coh in COHORTS:
        coh_panels[coh] = {
            "baseline": resolve_panel("baseline", baseline_api, coh, panels[coh]),
            "treatment": resolve_panel("treatment", treatment_api, coh, panels[coh]),
        }
    # If any panel still has UNRESOLVED mapping errors, do NOT emit a characterization from an incomplete
    # population — abort so the operator re-runs (resume retries the errored names from the persisted
    # caches) until the panels are clean. This prevents a distorted partial comparison rather than merely
    # annotating one.
    if errors:
        raise SystemExit(
            f"{sum(errors.values())} mapping error(s) remain {dict(errors)} — panels incomplete; re-run to "
            f"resume and retry them (caches at {out}) before the comparison is produced"
        )
    rows: list[dict] = []
    for coh in COHORTS:
        b = arm_pair("baseline", baseline_api, necs_by_arm["baseline"], coh_panels[coh]["baseline"], resolver)
        t = arm_pair("treatment", treatment_api, necs_by_arm["treatment"], coh_panels[coh]["treatment"], resolver)
        rows.append(delta_row(f"necs↔{coh}", b, t))
        print(
            f"[pair] necs↔{coh}: links {b.n_links}->{t.n_links}  "
            f"certified {b.certified.certified}->{t.certified.certified}",
            flush=True,
        )

    (out / "characterization.json").write_text(
        json.dumps(
            {
                "run_timestamp": ts,
                "baseline_api": baseline_api,
                "treatment_api": treatment_api,
                "rows": rows,
                "mapping_errors": errors,  # arm:label -> count; non-empty means treat deltas with caution
            },
            indent=2,
        )
    )
    table = render_table(rows)
    (out / "characterization_table.txt").write_text(table + "\n")
    print("\n=== Arm-M cross-cohort certificate characterization (baseline vs treatment) ===")
    print(table)
    if errors:
        print(
            f"\n[caution] per-entity mapping errors (excluded from links): {errors} — "
            "deltas on affected pairs are partial."
        )
    print(
        "\n[note] CHARACTERIZATION, not a gate verdict; certified/refuted signal is "
        "small-molecule-dominated (lipids refused)."
    )
    print(f"[done] {out}/characterization.json", flush=True)


if __name__ == "__main__":  # pragma: no cover
    main()
