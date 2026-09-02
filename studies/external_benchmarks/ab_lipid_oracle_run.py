"""Unit 4 (operator) — the live 2x2 A/B that produces the sprint number. SUPERVISED; ``# pragma: no cover``.

The falsifiable logic (transition matrix, provenance guard, oracle) is unit-tested in the pure modules;
this driver wires them to the live dev APIs and is never run in pytest (only ``provided_id_kwargs`` is
tested).

2x2 = {Kestrel fix off/on} x {provided-id oracle off/on}, over the two viable pairs (necs<->arivale,
necs<->xuetal; llfs/blsa are coverage-limited, Unit 0). Two axes, nothing else changes:

  - fix axis   : which biomapper instance resolves the NAME-only panels — BASELINE_API (unpatched) vs
                 TREATMENT_API (Unit-3-patched). Run name-only (Arm M), never fed the HMDB/PubChem ids
                 the oracle uses (KD3). Different resolutions -> different CURIE link sets; a link present
                 under baseline but absent under treatment is ``filter_eliminated`` (kept in the
                 denominator, never an improvement).
  - oracle axis: how each side's INDEPENDENT structure is built — ``block_for_name`` only (oracle-off;
                 lipids refuse) vs ``block_for_provided`` from the curator ids (oracle-on). Structure is
                 name/id-based, so the oracle maps are shared across both APIs.

Independence: the provided-id source is the Metabolon curator cross-reference (gold InChIKey / HMDB /
PubChem), independent of the Kraken KG (biomapper commits via name/RM/CHEBI). The reported number ABORTS
if any block feeding it is untagged (the certify_links_tagged canary). Persist-by-default (R23) to
~/external_benchmark_runs/ab_lipid_oracle_<ts>/ with a version-pinned manifest; the API key (from
/tmp/.bmk) is header-only and never written to any artifact.

Env: BASELINE_API, TREATMENT_API (full /api/v1/map/batch URLs); NECS_GOLD_TSV (provided-id source tsv);
AB_KG_BUILD (build tag folded into the run key); AB_OUT / AB_FRESH (pin / force a run dir).
"""

from __future__ import annotations


def provided_id_kwargs(gold_row: dict[str, str]) -> dict[str, str | None]:
    """Pure: map a cohort/NECS source row to the ``block_for_provided`` kwargs (KD1 order).

    Prefers the offline gold InChIKey, then HMDB, then PubChem CID. Empty/absent columns -> None so the
    resolver falls through. This is the only piece the tests exercise; the resolution + live loop are
    operator-gated below.
    """

    def _clean(v: str | None) -> str | None:
        s = (v or "").strip()
        return s or None

    return {
        "inchikey": _clean(gold_row.get("gold_inchikey")),
        "hmdb": _clean(gold_row.get("gold_hmdb") or gold_row.get("HMDB_ID")),
        "pubchem": _clean(gold_row.get("gold_pubchem") or gold_row.get("PubChem_ID")),
    }


# --- Everything below is the supervised live loop: # pragma: no cover throughout. ---

import csv  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import requests  # noqa: E402

from studies.external_benchmarks.ab_transition_matrix import BASE, BOTH, FILTER_ONLY, ORACLE_ONLY, build_report  # noqa: E402
from studies.external_benchmarks.cross_cohort_run import load_panels  # noqa: E402
from studies.external_benchmarks.scorers.cross_cohort_overlap import curie_set, link_by_intersection  # noqa: E402
from studies.external_benchmarks.scorers.independent_inchikey import ProvidedBlock, PubChemInChIKeyResolver  # noqa: E402
from studies.external_benchmarks.scorers.independent_link_certificate_overlap import certify_links_tagged  # noqa: E402

PAIRS = ("arivale", "xuetal")  # the two viable pairs (Unit 0)
CHUNK = 25
_PREFIX = "ab_lipid_oracle_"


def _now_ts() -> str:  # pragma: no cover
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _load_provided_source() -> dict[str, dict[str, str]]:  # pragma: no cover
    """name.lower() -> {gold_inchikey, gold_hmdb, gold_pubchem} from the Metabolon curator tsv."""
    path = Path(os.environ["NECS_GOLD_TSV"]).expanduser()
    out: dict[str, dict[str, str]] = {}
    with path.open() as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            out[row["chemical_name"].strip().lower()] = row
    return out


def _resolve_panel(api: str, key: str, out_dir: Path, arm: str, label: str, names: list[str]) -> dict[str, dict]:  # pragma: no cover
    """Resolve a panel through one biomapper API (name-only, Arm M); cache per (arm, label)."""
    cache_path = out_dir / f"{arm}__{label}_devapi.jsonl"
    cache: dict[str, dict] = {}
    if cache_path.exists():
        for line in cache_path.open():
            r = json.loads(line)
            cache[r["name"]] = r
    todo = [n for n in names if n not in cache]
    print(f"[devapi {arm}] {label}: {len(names)} names, {len(todo)} to fetch", flush=True)
    with cache_path.open("a") as fh:
        for i in range(0, len(todo), CHUNK):
            body = {
                "entities": [{"name": n, "entity_type": "metabolite"} for n in todo[i : i + CHUNK]],
                "options": {"annotation_mode": "all"},
            }
            resp = requests.post(api, headers={"X-API-Key": key}, json=body, timeout=300)
            resp.raise_for_status()
            for r in resp.json()["results"]:
                rec = {"name": r["name"], "chosen_kg_id": r.get("chosen_kg_id"), "kg_equivalent_ids": r.get("kg_equivalent_ids") or {}}
                cache[r["name"]] = rec
                fh.write(json.dumps(rec) + "\n")
            fh.flush()
    return cache


def _oracle_provided(names: set[str], src: dict[str, dict[str, str]], resolver: PubChemInChIKeyResolver, out_dir: Path) -> dict[str, ProvidedBlock]:  # pragma: no cover
    """oracle-ON map: block_for_provided from the curator ids (falls back to name), tagged + cached."""
    cache_path = out_dir / "oracle_provided.jsonl"
    out: dict[str, ProvidedBlock] = {}
    if cache_path.exists():
        for line in cache_path.open():
            r = json.loads(line)
            out[r["name"]] = ProvidedBlock(r["block"], r["source"], r["status"])
    with cache_path.open("a") as fh:
        for n in sorted(names):
            if n in out:
                continue
            kw = provided_id_kwargs(src.get(n.strip().lower(), {}))
            pb = resolver.block_for_provided(name=n, **kw)
            out[n] = pb
            fh.write(json.dumps({"name": n, "block": pb.block, "source": pb.source, "status": pb.status}) + "\n")
        fh.flush()
    return out


def _oracle_name_only(names: set[str], resolver: PubChemInChIKeyResolver, out_dir: Path) -> dict[str, ProvidedBlock]:  # pragma: no cover
    """oracle-OFF map: PubChem-by-name only (current refused-heavy behavior), tagged."""
    cache_path = out_dir / "oracle_name_only.jsonl"
    out: dict[str, ProvidedBlock] = {}
    if cache_path.exists():
        for line in cache_path.open():
            r = json.loads(line)
            out[r["name"]] = ProvidedBlock(r["block"], r["source"], r["status"])
    with cache_path.open("a") as fh:
        for n in sorted(names):
            if n in out:
                continue
            blk = resolver.block_for_name(n)
            pb = ProvidedBlock(blk, "pubchem-name" if blk else "none", "success" if blk else "clean_miss")
            out[n] = pb
            fh.write(json.dumps({"name": n, "block": pb.block, "source": pb.source, "status": pb.status}) + "\n")
        fh.flush()
    return out


def _cell_verdicts(links, a_map, b_map, all_keys: set[str]) -> tuple[dict[str, str], int]:  # pragma: no cover
    """Per-link verdicts for one cell. A lookup_failed on either side -> 'lookup_failed'; a link absent
    from THIS cell's link set -> 'filter_eliminated'. Returns (verdicts, untagged_canary)."""
    overlap, untagged = certify_links_tagged(links, a_map, b_map)
    verdicts: dict[str, str] = {}
    present: set[str] = set()
    for a, b, v in overlap.per_link:
        key = f"{a}||{b}"
        present.add(key)
        a_pb, b_pb = a_map.get(a), b_map.get(b)
        if (a_pb and a_pb.status == "lookup_failed") or (b_pb and b_pb.status == "lookup_failed"):
            verdicts[key] = "lookup_failed"
        else:
            verdicts[key] = v
    for key in all_keys - present:
        verdicts[key] = "filter_eliminated"
    return verdicts, untagged


def main() -> None:  # pragma: no cover
    baseline_api = os.environ["BASELINE_API"]
    treatment_api = os.environ["TREATMENT_API"]
    key = Path("/tmp/.bmk").read_text().strip()
    src = _load_provided_source()
    panels = load_panels()

    h = hashlib.sha256()
    for a in (baseline_api, treatment_api, os.environ.get("AB_KG_BUILD", "")):
        h.update((a + "\n").encode())
    run_key = h.hexdigest()[:16]
    runs_root = Path.home() / "external_benchmark_runs"
    out_dir = Path(os.environ["AB_OUT"]).expanduser() if os.environ.get("AB_OUT") else runs_root / f"{_PREFIX}{_now_ts()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = out_dir / "manifest.json"
    if not manifest.exists():
        import pygoslin  # noqa: F401
        import rdkit

        manifest.write_text(
            json.dumps(
                {
                    "run_key": run_key,
                    "baseline_api": baseline_api,
                    "treatment_api": treatment_api,
                    "kg_build": os.environ.get("AB_KG_BUILD", ""),
                    "rdkit": rdkit.__version__,
                    "created": _now_ts(),
                    "note": "provided-id oracle 2x2; api key NOT recorded; internal endpoints scrub before publish",
                },
                indent=2,
            )
        )

    resolver = PubChemInChIKeyResolver()
    reports: dict[str, dict] = {}
    for cohort in PAIRS:
        # Resolve necs + cohort through BOTH apis (name-only).
        res = {
            "baseline": (
                _resolve_panel(baseline_api, key, out_dir, "baseline", "necs", panels["necs"]),
                _resolve_panel(baseline_api, key, out_dir, "baseline", cohort, panels[cohort]),
            ),
            "treatment": (
                _resolve_panel(treatment_api, key, out_dir, "treatment", "necs", panels["necs"]),
                _resolve_panel(treatment_api, key, out_dir, "treatment", cohort, panels[cohort]),
            ),
        }
        links_by_arm = {}
        for arm, (necs, coh) in res.items():
            nc = {n: curie_set(r["chosen_kg_id"], r["kg_equivalent_ids"]) for n, r in necs.items()}
            cc = {n: curie_set(r["chosen_kg_id"], r["kg_equivalent_ids"]) for n, r in coh.items()}
            links_by_arm[arm] = link_by_intersection(nc, cc).links
        all_keys = {f"{lk.a_name}||{lk.b_name}" for arm in links_by_arm for lk in links_by_arm[arm]}
        linked_names = {lk.a_name for arm in links_by_arm for lk in links_by_arm[arm]} | {
            lk.b_name for arm in links_by_arm for lk in links_by_arm[arm]
        }
        provided = _oracle_provided(linked_names, src, resolver, out_dir)
        name_only = _oracle_name_only(linked_names, resolver, out_dir)

        cells: dict = {}
        canary = 0
        for cell, arm, omap in (
            (BASE, "baseline", name_only),
            (FILTER_ONLY, "treatment", name_only),
            (ORACLE_ONLY, "baseline", provided),
            (BOTH, "treatment", provided),
        ):
            verdicts, untagged = _cell_verdicts(links_by_arm[arm], omap, omap, all_keys)
            cells[cell] = verdicts
            canary += untagged
        if canary:
            raise SystemExit(f"ABORT: {canary} untagged blocks fed the metric for {cohort} — number not trustworthy")
        rep = build_report(cells)
        reports[f"necs<->{cohort}"] = {
            "cells": {k: vars(v) for k, v in rep.cells.items()},
            "improvements": rep.improvements,
            "regressions": rep.regressions,
            "attribution": rep.attribution,
            "certified_not_dropped": rep.certified_not_dropped,
        }
        print(f"[pair necs<->{cohort}] improvements={rep.improvements} regressions={rep.regressions} "
              f"certified_not_dropped={rep.certified_not_dropped}", flush=True)

    (out_dir / "ab_transition_report.json").write_text(json.dumps(reports, indent=2))
    print(f"[done] {out_dir}/ab_transition_report.json", flush=True)


if __name__ == "__main__":  # pragma: no cover
    main()
