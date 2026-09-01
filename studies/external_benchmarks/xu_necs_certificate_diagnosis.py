"""Unit E — Xu↔NECS lipid false-positive diagnosis via the KG-INDEPENDENT certificate (supervised live).

Sizes the suspected Xu inflation: resolve both panels through the dev API (default arm), form CURIE
links, then adjudicate EACH link with structures resolved INDEPENDENTLY of the KG node — here by the
PubChem name index (block_for_name), since both spreadsheet panels are name-only. Splits links into:

  certified  — independent structures agree at connectivity (genuine same-molecule link)
  refuted    — independent structures DISAGREE at connectivity (wrong-molecule / shared-generic-node
               false positive — the resolver-bug candidate)
  refused    — a side has no independent structure (name not in PubChem, e.g. sum-composition lipid —
               inherent, counts-only, NOT a resolver bug)

Uses the default annotator pipeline, so it is independent of the (opt-in) text/vector fix. Resumable:
per-name dev-API + oracle caches on disk. Persist-by-default (R23). This is a SUPERVISED operator run
(dev API on localhost:8003 via SSH tunnel; live PubChem). NOT invoked from pytest.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests

from studies.external_benchmarks.cross_cohort_run import load_panels
from studies.external_benchmarks.scorers.cross_cohort_overlap import curie_set, link_by_intersection
from studies.external_benchmarks.scorers.independent_inchikey import PubChemInChIKeyResolver
from studies.external_benchmarks.scorers.independent_link_certificate_overlap import certify_links

API_BATCH = "http://localhost:8003/api/v1/map/batch"
KEY = Path("/tmp/.bmk").read_text().strip()
CHUNK = 25
_PREFIX = "xu_necs_certificate_diagnosis_"


def _now_ts() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _run_key(panels: dict[str, list[str]]) -> str:
    """Stable identity of THIS diagnosis run: the dev-API endpoint + the exact panels being resolved.

    A resumed run may only reuse caches produced by an identical run. Keying on the sorted NECS + Xu
    name lists and the API base means that changing a panel (added/removed analytes) or pointing at a
    different dev API yields a different key, so stale caches from a prior, different run are never
    silently adopted as the current diagnosis.
    """
    h = hashlib.sha256()
    h.update(API_BATCH.encode())
    for label in ("necs", "xuetal"):
        h.update(f"\n[{label}]\n".encode())
        h.update("\n".join(sorted(panels.get(label, []))).encode())
    return h.hexdigest()[:16]


def _resolve_out_dir(run_key: str) -> Path:
    """Resolve the run/output directory — STABLE across restarts so a resumed run finds its caches.

    A fresh timestamp on every process start would point both cache readers at an empty directory,
    silently re-issuing every (paid, rate-limited) dev-API + PubChem request an interrupted run had
    already completed. So a bare restart AUTO-RESUMES: it reuses the most recent prior run directory
    whose ``manifest.json`` records the SAME ``run_key`` (identical endpoint + panels). A prior dir with
    no manifest or a mismatched key is skipped — never adopted — so a changed panel or endpoint starts
    fresh instead of resuming stale mappings as if current. ``XU_NECS_FRESH=1`` forces a new run;
    ``XU_NECS_OUT`` pins an exact directory (operator-trusted, provenance not re-checked).
    """
    override = os.environ.get("XU_NECS_OUT")
    if override:
        return Path(override).expanduser()
    runs_root = Path.home() / "external_benchmark_runs"
    if not os.environ.get("XU_NECS_FRESH"):
        prior = sorted(
            (p for p in runs_root.glob(f"{_PREFIX}*") if p.is_dir() and any(p.glob("*.jsonl"))),
            key=lambda p: p.name,  # timestamp names sort lexicographically == chronologically
            reverse=True,
        )
        for p in prior:
            manifest = p / "manifest.json"
            try:
                if manifest.exists() and json.loads(manifest.read_text()).get("run_key") == run_key:
                    return p  # same endpoint + panels -> safe to resume
            except (ValueError, OSError):
                continue  # unreadable/corrupt manifest -> treat as non-matching
    return runs_root / f"{_PREFIX}{_now_ts()}"


# Set in main() once the panels (and thus the run_key) are known — resolving at import would have no
# panels to key provenance on, and would side-effect a mkdir on mere import.
OUT: Path = Path.home() / "external_benchmark_runs"
TS: str = ""


def _resolve_panel(label: str, names: list[str]) -> dict[str, dict]:
    cache_path = OUT / f"{label}_devapi.jsonl"
    cache: dict[str, dict] = {}
    if cache_path.exists():
        for line in cache_path.open():
            r = json.loads(line)
            cache[r["name"]] = r
    todo = [n for n in names if n not in cache]
    print(f"[devapi] {label}: {len(names)} names, {len(todo)} to fetch", flush=True)
    with cache_path.open("a") as fh:
        for i in range(0, len(todo), CHUNK):
            body = {
                "entities": [{"name": n, "entity_type": "metabolite"} for n in todo[i : i + CHUNK]],
                "options": {"annotation_mode": "all"},
            }
            resp = requests.post(API_BATCH, headers={"X-API-Key": KEY}, json=body, timeout=300)
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
            if (i // CHUNK) % 8 == 0:
                print(f"[devapi] {label}: {min(i + CHUNK, len(todo))}/{len(todo)}", flush=True)
    return cache


def _independent_by_name(names: set[str], resolver: PubChemInChIKeyResolver) -> dict[str, str | None]:
    cache_path = OUT / "independent_by_name.jsonl"
    out: dict[str, str | None] = {}
    if cache_path.exists():
        for line in cache_path.open():
            r = json.loads(line)
            out[r["name"]] = r["block"]
    todo = sorted(n for n in names if n not in out)
    print(f"[oracle] {len(names)} unique linked names, {len(todo)} to fetch from PubChem", flush=True)
    with cache_path.open("a") as fh:
        for i, n in enumerate(todo):
            block = resolver.block_for_name(n)
            out[n] = block
            fh.write(json.dumps({"name": n, "block": block}) + "\n")
            if i % 50 == 0:
                fh.flush()
                print(f"[oracle] {i}/{len(todo)}", flush=True)
        fh.flush()
    return out


def main() -> None:
    global OUT, TS
    panels = load_panels()
    run_key = _run_key(panels)
    OUT = _resolve_out_dir(run_key)
    OUT.mkdir(parents=True, exist_ok=True)
    TS = OUT.name[len(_PREFIX):] if OUT.name.startswith(_PREFIX) else _now_ts()
    manifest = OUT / "manifest.json"
    if not manifest.exists():  # stamp provenance on a fresh dir; a resumed dir already carries its own
        manifest.write_text(
            json.dumps(
                {"run_key": run_key, "api_batch": API_BATCH, "necs_n": len(panels["necs"]),
                 "xu_n": len(panels["xuetal"]), "created": TS},
                indent=2,
            )
        )
    resuming = any(OUT.glob("*.jsonl"))
    print(f"[run] {OUT} ({'RESUMING — reusing on-disk caches' if resuming else 'fresh run'})", flush=True)
    if not os.environ.get("XU_NECS_OUT"):
        print("[run] re-running this script auto-resumes the matching cached run; "
              "XU_NECS_FRESH=1 forces a new run, XU_NECS_OUT pins a specific one", flush=True)
    necs = _resolve_panel("necs", panels["necs"])
    xu = _resolve_panel("xuetal", panels["xuetal"])

    necs_curie = {n: curie_set(r["chosen_kg_id"], r["kg_equivalent_ids"]) for n, r in necs.items()}
    xu_curie = {n: curie_set(r["chosen_kg_id"], r["kg_equivalent_ids"]) for n, r in xu.items()}
    ov = link_by_intersection(necs_curie, xu_curie)
    print(f"[curie] Xu↔NECS CURIE links={ov.n_links} necs_linked={ov.n_a_linked} xu_linked={ov.n_b_linked}", flush=True)

    linked_names = {lk.a_name for lk in ov.links} | {lk.b_name for lk in ov.links}
    resolver = PubChemInChIKeyResolver()
    ind = _independent_by_name(linked_names, resolver)

    certified = certify_links(ov.links, ind, ind)
    # classify refused links: a refused link is inherent (no independent structure) — separate lipids
    refused_pairs = [(a, b) for (a, b, v) in certified.per_link if v == "refused"]
    refuted_pairs = [(a, b) for (a, b, v) in certified.per_link if v == "refuted"]

    result = {
        "pair": "Xu<->NECS",
        "run_timestamp": TS,
        "curie_links": ov.n_links,
        "certified": certified.certified,
        "refuted": certified.refuted,  # wrong-molecule / shared-generic-node false positives
        "refused": certified.refused,  # no independent structure (inherent — sum-composition lipids etc.)
        "certified_rate_of_adjudicable": certified.certified_rate,
        "adjudicable": certified.adjudicable,
    }
    (OUT / "xu_diagnosis.json").write_text(json.dumps(result, indent=2))
    (OUT / "refuted_pairs.json").write_text(json.dumps(refuted_pairs, indent=2))
    (OUT / "refused_pairs.json").write_text(json.dumps(refused_pairs[:200], indent=2))

    print("\n=== Xu↔NECS independent-certificate diagnosis ===", flush=True)
    for k, v in result.items():
        print(f"  {k}: {v}", flush=True)
    print(f"\n  refuted (false-positive candidates) examples: {refuted_pairs[:8]}", flush=True)
    print(f"[done] {OUT}/xu_diagnosis.json", flush=True)


if __name__ == "__main__":
    main()
