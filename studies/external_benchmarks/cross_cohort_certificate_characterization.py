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
    total_cells = (
        "TOTAL".ljust(widths[0]),
        _btd(tot["links_base"], tot["links_treat"]).rjust(widths[1]),
        _btd(tot["certified_base"], tot["certified_treat"]).rjust(widths[2]),
        _btd(tot["refuted_base"], tot["refuted_treat"]).rjust(widths[3]),
        _btd(tot["refused_base"], tot["refused_treat"]).rjust(widths[4]),
    )
    lines.append(" ".join(total_cells))
    return "\n".join(lines)


# --- LIVE, SUPERVISED (never in pytest) ------------------------------------------------------------


def _now_ts() -> str:  # pragma: no cover - trivial, live only
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def main() -> None:  # pragma: no cover - supervised live operator step; drives two dev APIs + PubChem
    import requests

    from studies.external_benchmarks.cross_cohort_run import COHORTS, load_panels
    from studies.external_benchmarks.scorers.independent_inchikey import PubChemInChIKeyResolver

    baseline_api = os.environ["BASELINE_API"]
    treatment_api = os.environ["TREATMENT_API"]
    key = Path("/tmp/.bmk").read_text().strip()
    ts = _now_ts()
    out = Path.home() / f"external_benchmark_runs/cross_cohort_characterization_{ts}"
    out.mkdir(parents=True, exist_ok=True)
    print(f"[run] {out}\n[arms] baseline={baseline_api}\n       treatment={treatment_api}", flush=True)

    def resolve_panel(arm: str, api: str, label: str, names: list[str]) -> dict[str, dict]:
        cache_path = out / f"{arm}__{label}_devapi.jsonl"
        cache: dict[str, dict] = {}
        if cache_path.exists():
            for line in cache_path.open():
                r = json.loads(line)
                cache[r["name"]] = r
        todo = [n for n in names if n not in cache]
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
                    rec = {
                        "name": r["name"],
                        "chosen_kg_id": r.get("chosen_kg_id"),
                        "kg_equivalent_ids": r.get("kg_equivalent_ids") or {},
                    }
                    cache[r["name"]] = rec
                    fh.write(json.dumps(rec) + "\n")
                fh.flush()
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
    rows: list[dict] = []
    for coh in COHORTS:
        b_coh = resolve_panel("baseline", baseline_api, coh, panels[coh])
        t_coh = resolve_panel("treatment", treatment_api, coh, panels[coh])
        b = arm_pair("baseline", baseline_api, necs_by_arm["baseline"], b_coh, resolver)
        t = arm_pair("treatment", treatment_api, necs_by_arm["treatment"], t_coh, resolver)
        rows.append(delta_row(f"necs↔{coh}", b, t))
        print(
            f"[pair] necs↔{coh}: links {b.n_links}->{t.n_links}  "
            f"certified {b.certified.certified}->{t.certified.certified}",
            flush=True,
        )

    (out / "characterization.json").write_text(
        json.dumps(
            {"run_timestamp": ts, "baseline_api": baseline_api, "treatment_api": treatment_api, "rows": rows},
            indent=2,
        )
    )
    table = render_table(rows)
    (out / "characterization_table.txt").write_text(table + "\n")
    print("\n=== Arm-M cross-cohort certificate characterization (baseline vs treatment) ===")
    print(table)
    print(
        "\n[note] CHARACTERIZATION, not a gate verdict; certified/refuted signal is "
        "small-molecule-dominated (lipids refused)."
    )
    print(f"[done] {out}/characterization.json", flush=True)


if __name__ == "__main__":  # pragma: no cover
    main()
