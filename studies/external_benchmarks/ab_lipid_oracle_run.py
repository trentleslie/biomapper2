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
                 lipids refuse) vs ``block_for_provided`` from the curator ids (oracle-on).

Independence (KD3): each side is resolved from ITS OWN curator cross-reference — the NECS side from the
Metabolon gold tsv, the cohort side from the cohort's OWN vendor ids (Arivale's HMDB/PubChem columns;
Xu, which publishes none, from the Metabolon-name join to the same gold tsv). The two sides therefore
carry DISTINCT provided-id maps — never one map reused for both — and neither is the Kraken KG. The
reported number ABORTS if any block feeding it is untagged (the certify_links_tagged canary).

Resume/provenance: the run dir is keyed by a ``run_key`` over the two API endpoints + the KG-build tag;
a bare restart auto-resumes ONLY a prior dir whose manifest records the same key (else it starts fresh),
and ``AB_FRESH=1`` forces a new run. Persist-by-default (R23); the API key (from /tmp/.bmk) is header-only
and never written to any artifact; internal endpoints are recorded for reproduction and must be scrubbed
before any external publication.

Env: BASELINE_API, TREATMENT_API (full /api/v1/map/batch URLs); NECS_GOLD_TSV (Metabolon provided-id tsv);
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
from dataclasses import replace  # noqa: E402

from studies.external_benchmarks.ab_transition_matrix import BASE, BOTH, FILTER_ONLY, ORACLE_ONLY, build_report  # noqa: E402
from studies.external_benchmarks.cross_cohort_run import ARIVALE_XLSX, load_panels  # noqa: E402
from studies.external_benchmarks.scorers.cross_cohort_overlap import curie_set, link_by_intersection  # noqa: E402
from studies.external_benchmarks.scorers.independent_inchikey import ProvidedBlock, PubChemInChIKeyResolver  # noqa: E402
from studies.external_benchmarks.scorers.independent_link_certificate_overlap import certify_links_tagged  # noqa: E402

PAIRS = ("arivale", "xuetal")  # the two viable pairs (Unit 0)
CHUNK = 25
_PREFIX = "ab_lipid_oracle_"


def _now_ts() -> str:  # pragma: no cover
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _gold_source() -> dict[str, dict[str, str]]:  # pragma: no cover
    """name.lower() -> {gold_inchikey, gold_hmdb, gold_pubchem} from the Metabolon curator tsv.

    Used for the NECS side and for the Xu side (Metabolon-name join; Xu publishes no vendor ids)."""
    path = Path(os.environ["NECS_GOLD_TSV"]).expanduser()
    out: dict[str, dict[str, str]] = {}
    with path.open() as fh:
        for row in csv.DictReader(fh, delimiter="\t"):
            out[row["chemical_name"].strip().lower()] = row
    return out


def _arivale_source() -> dict[str, dict[str, str]]:  # pragma: no cover
    """name.lower() -> its OWN HMDB/PubChem vendor ids, from the Arivale supplement (not NECS gold)."""
    import pandas as pd

    df = pd.read_excel(ARIVALE_XLSX, sheet_name="Arivale_Metabolomics", dtype=str).fillna("")
    out: dict[str, dict[str, str]] = {}
    for _, r in df.iterrows():
        out[str(r.get("BiochemicalName", "")).strip().lower()] = {
            "gold_hmdb": str(r.get("HMDB_ID", "")),
            "gold_pubchem": str(r.get("PubChem_ID", "")),
            "gold_inchikey": "",
        }
    return out


def _run_key(baseline_api: str, treatment_api: str, panels: dict[str, list[str]], gold_path: Path) -> str:  # pragma: no cover
    """Identity of THIS run: endpoints + build tag + the exact panels + the provided-id source file.

    Changing a panel (added/removed analytes) or the gold tsv changes the key, so a resumed run can never
    silently mix caches built from different benchmark inputs.
    """
    h = hashlib.sha256()
    for a in (baseline_api, treatment_api, os.environ.get("AB_KG_BUILD", "")):
        h.update((a + "\n").encode())
    for label in ("necs", "arivale", "xuetal"):
        h.update(f"\n[{label}]\n".encode())
        h.update("\n".join(sorted(panels.get(label, []))).encode())
    h.update(b"\n[gold]\n")
    h.update(hashlib.sha256(gold_path.read_bytes()).hexdigest().encode())
    return h.hexdigest()[:16]


def _resolve_out_dir(run_key: str) -> Path:  # pragma: no cover
    """Stable run dir: AB_OUT pins it; else auto-resume the newest prior dir whose manifest run_key
    matches (identical endpoints + build tag), never a mismatched/manifest-less one; AB_FRESH forces new."""
    if os.environ.get("AB_OUT"):
        p = Path(os.environ["AB_OUT"]).expanduser()
        if p.exists() and any(p.glob("*.jsonl")):
            manifest = p / "manifest.json"
            if not manifest.exists():
                raise SystemExit(f"AB_OUT {p} holds caches but no manifest — refuse to reuse; set AB_FRESH=1")
            try:
                cached_key = json.loads(manifest.read_text()).get("run_key")
            except (ValueError, OSError) as exc:
                raise SystemExit(f"AB_OUT {p} manifest unreadable ({exc}) — refuse to reuse") from exc
            if cached_key != run_key:
                raise SystemExit(f"AB_OUT {p} run_key {cached_key} != current {run_key} — refuse to mix stale caches")
        return p
    runs_root = Path.home() / "external_benchmark_runs"
    if not os.environ.get("AB_FRESH"):
        prior = sorted(
            (p for p in runs_root.glob(f"{_PREFIX}*") if p.is_dir() and any(p.glob("*.jsonl"))),
            key=lambda p: p.name,
            reverse=True,
        )
        for p in prior:
            manifest = p / "manifest.json"
            try:
                if manifest.exists() and json.loads(manifest.read_text()).get("run_key") == run_key:
                    return p
            except (ValueError, OSError):
                continue
    return runs_root / f"{_PREFIX}{_now_ts()}"


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


def _oracle_provided(names: set[str], src: dict[str, dict[str, str]], resolver: PubChemInChIKeyResolver, out_dir: Path, tag: str, src_tag: str) -> dict[str, ProvidedBlock]:  # pragma: no cover
    """oracle-ON map for ONE side: block_for_provided from THAT side's curator ids (name fallback), cached.

    ``src_tag`` names the source FILE ("gold" | "arivale") so record_id = "{src_tag}:{name}"; two sides
    sharing a record_id are the same curator record and the certificate refuses that self-comparison."""
    cache_path = out_dir / f"oracle_provided_{tag}.jsonl"
    out: dict[str, ProvidedBlock] = {}
    if cache_path.exists():
        for line in cache_path.open():
            r = json.loads(line)
            out[r["name"]] = ProvidedBlock(r["block"], r["source"], r["status"], r.get("record_id"))
    with cache_path.open("a") as fh:
        for n in sorted(names):
            if n in out:
                continue
            kw = provided_id_kwargs(src.get(n.strip().lower(), {}))
            pb = replace(resolver.block_for_provided(name=n, **kw), record_id=f"{src_tag}:{n.strip().lower()}")
            out[n] = pb
            fh.write(json.dumps({"name": n, "block": pb.block, "source": pb.source, "status": pb.status, "record_id": pb.record_id}) + "\n")
        fh.flush()
    return out


def _oracle_name_only(names: set[str], resolver: PubChemInChIKeyResolver, out_dir: Path, tag: str) -> dict[str, ProvidedBlock]:  # pragma: no cover
    """oracle-OFF map: PubChem-by-name only (current refused-heavy behavior), tagged. Name-keyed, so one
    map legitimately serves both sides (a_name/b_name each resolve by their own name)."""
    cache_path = out_dir / f"oracle_name_{tag}.jsonl"
    out: dict[str, ProvidedBlock] = {}
    if cache_path.exists():
        for line in cache_path.open():
            r = json.loads(line)
            out[r["name"]] = ProvidedBlock(r["block"], r["source"], r["status"], r.get("record_id"))
    with cache_path.open("a") as fh:
        for n in sorted(names):
            if n in out:
                continue
            blk = resolver.block_for_name(n)
            pb = ProvidedBlock(blk, "pubchem-name" if blk else "none", "success" if blk else "clean_miss",
                               f"pubchem-name:{n.strip().lower()}")
            out[n] = pb
            fh.write(json.dumps({"name": n, "block": pb.block, "source": pb.source, "status": pb.status, "record_id": pb.record_id}) + "\n")
        fh.flush()
    return out


def _cell_verdicts(links, a_map, b_map, all_keys: set[str]) -> tuple[dict[str, str], int]:  # pragma: no cover
    """Per-link verdicts for one cell. A lookup_failed on either side -> 'lookup_failed'; a link absent
    from THIS cell's link set -> 'filter_eliminated'. Returns (verdicts, untagged_canary)."""
    overlap, untagged = certify_links_tagged(links, a_map, b_map)
    verdicts: dict[str, str] = {}
    present: set[str] = set()
    for a, b, v in overlap.per_link:
        klk = f"{a}||{b}"
        present.add(klk)
        a_pb, b_pb = a_map.get(a), b_map.get(b)
        if (a_pb and a_pb.status == "lookup_failed") or (b_pb and b_pb.status == "lookup_failed"):
            verdicts[klk] = "lookup_failed"
        else:
            verdicts[klk] = v
    for klk in all_keys - present:
        verdicts[klk] = "filter_eliminated"
    return verdicts, untagged


def main() -> None:  # pragma: no cover
    baseline_api = os.environ["BASELINE_API"]
    treatment_api = os.environ["TREATMENT_API"]
    key = Path("/tmp/.bmk").read_text().strip()
    gold_src = _gold_source()
    arivale_src = _arivale_source()
    panels = load_panels()

    run_key = _run_key(baseline_api, treatment_api, panels, Path(os.environ["NECS_GOLD_TSV"]).expanduser())
    out_dir = _resolve_out_dir(run_key)
    out_dir.mkdir(parents=True, exist_ok=True)
    resuming = any(out_dir.glob("*.jsonl"))
    print(f"[run] {out_dir} ({'RESUMING matching run_key' if resuming else 'fresh run'}); AB_FRESH forces new", flush=True)
    manifest = out_dir / "manifest.json"
    if not manifest.exists():
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
                    "note": "provided-id oracle 2x2; api key NOT recorded; scrub internal endpoints before publish",
                },
                indent=2,
            )
        )

    resolver = PubChemInChIKeyResolver()
    reports: dict[str, dict] = {}
    for cohort in PAIRS:
        coh_src = arivale_src if cohort == "arivale" else gold_src  # each side from ITS OWN curator ids
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
        necs_names = {lk.a_name for arm in links_by_arm for lk in links_by_arm[arm]}
        coh_names = {lk.b_name for arm in links_by_arm for lk in links_by_arm[arm]}

        # DISTINCT per-side maps: NECS side from gold, cohort side from its OWN ids (never one map for both).
        prov_necs = _oracle_provided(necs_names, gold_src, resolver, out_dir, f"{cohort}_necs", "gold")
        prov_coh = _oracle_provided(coh_names, coh_src, resolver, out_dir, f"{cohort}_coh", "arivale" if cohort == "arivale" else "gold")
        name_map = _oracle_name_only(necs_names | coh_names, resolver, out_dir, cohort)

        cells: dict = {}
        canary = 0
        for cell, arm, a_map, b_map in (
            (BASE, "baseline", name_map, name_map),
            (FILTER_ONLY, "treatment", name_map, name_map),
            (ORACLE_ONLY, "baseline", prov_necs, prov_coh),
            (BOTH, "treatment", prov_necs, prov_coh),
        ):
            verdicts, untagged = _cell_verdicts(links_by_arm[arm], a_map, b_map, all_keys)
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
