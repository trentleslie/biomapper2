"""Full per-name certificate re-adjudication (Units 1-5 of the Xu/Arivale re-adjudication plan).

This is a DETERMINISTIC re-adjudication of an EXISTING pinned ab_lipid_oracle run. It performs no
benchmark run, no backend/Kestrel call, and no resolver/KG change. It:

  Unit 1  re-emits EVERY per-name certificate record (name, group, verdict, necs_block, partner,
          partner_block) for both cohort pairs, reusing ``certificate_adjudication``'s helpers and the
          exact grouping/verdict rule, and gates on cell-for-cell reconciliation with the shipped
          ``certificate_adjudication.json`` counts.
  Unit 2  selects the re-adjudication target population: overlap-refuted + monti_only-certified +
          biomapper_only-certified, both pairs, dropping species-level lipids.
  Unit 3  resolves BOTH the NECS name and the partner name independently via PubChem PUG-REST
          (cached, block-shape-guarded, polite, no auto-pick on multi-CID).
  Unit 4  classifies each target row (first block + molecular formula) per its bucket.
  Unit 5  writes the per-name table and (via ``make_extended_sheet``) refreshes the extended sheet,
          with endpoint-leak assertions and a provenance header.

The certificate structures are the gold-id-resolved blocks (``nblk``/``cblk``); BioMapper's treatment
structure is used only for grouping, exactly as the generator does. The independent arbiter is a fresh
PubChem lookup on the names, distinct from both. # pragma: no cover on the __main__ path.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

from studies.external_benchmarks import certificate_adjudication as ca

PAIRS = ("arivale", "xuetal")
BLOCK_RE = re.compile(r"^[A-Z]{14}$")  # InChIKey first block shape guard (ledger L2/L3)

# Target (group, verdict) sets that carry the 3.7 claims.
TARGET_SETS = (("overlap", "refuted"), ("monti_only", "certified"), ("biomapper_only", "certified"))

PUBCHEM_CACHE = Path(__file__).with_name(".pubchem_cache.json")
_PUG = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"

# Pinned inputs that reconcile cell-for-cell with the run's certificate_adjudication.json (Unit 1 gate).
# REFMET_CACHE is the 2-column `input<TAB>refmet` convert cache (the plan named a 12-col freeze by
# mistake; the 2-col cache is what the generator's `_refmet` consumes and what the prior extended
# sheet recorded as refmet_source). The gold TSV only feeds the sheet's provenance columns; the refmet
# cache alone determines the grouping, so any of the Aug-04 golds reconciles -- we pin the "both" gold.
PINNED_RUN_DIR = Path("~/external_benchmark_runs/ab_lipid_oracle_20260907T235106Z").expanduser()
PINNED_REFMET_CACHE = Path("~/external_benchmark_runs/cohort_panels_20260804/necs_refmet_convert_cache.tsv").expanduser()
PINNED_GOLD_TSV = Path("~/external_benchmark_runs/necs_hybrid_both_20260804/input_df_with_provided.tsv").expanduser()


# --------------------------------------------------------------------------------------------------
# Unit 1: full per-name emit (reuse the generator's helpers + exact grouping/verdict rule)
# --------------------------------------------------------------------------------------------------
def build_full(run_dir, refmet_cache, gold_tsv):
    """Re-run the certificate grouping/verdict logic (verbatim from ``certificate_adjudication.main``)
    but capture EVERY per-name record with its group + verdict + blocks, for both pairs.

    Returns ``{cohort: {group: {verdict: [record, ...]}}}`` where each record is
    ``{name, group, verdict, necs_block, partner, partner_block}``.
    """
    os.environ["AB_RUN_DIR"] = str(Path(run_dir).expanduser())
    os.environ["REFMET_CACHE"] = str(Path(refmet_cache).expanduser())
    os.environ["NECS_GOLD_TSV"] = str(Path(gold_tsv).expanduser())
    ca.RUN = Path(run_dir).expanduser()  # rebind the generator's module-global run dir

    refmet = ca._refmet()
    full = {}
    for cohort in PAIRS:
        nc, cc = ca._res("necs"), ca._res(cohort)
        nblk, cblk = ca._blk(f"{cohort}_necs"), ca._blk(f"{cohort}_coh")
        coh_by_curie, coh_by_refmet, coh_by_name, coh_by_block = (defaultdict(set) for _ in range(4))
        for c in cc:
            for cu in cc[c]:
                coh_by_curie[cu].add(c)
            rm = refmet.get(c.strip().lower(), "")
            if rm:
                coh_by_refmet[rm].add(c)
            coh_by_name[c.strip().lower()].add(c)
            if cblk.get(c):
                coh_by_block[cblk[c]].add(c)

        groups = {g: {"certified": [], "refuted": [], "refused": []} for g in ("overlap", "biomapper_only", "monti_only")}
        for n in nc:
            nn, gb = n.strip().lower(), nblk.get(n)
            if not (coh_by_name.get(nn) or (gb and coh_by_block.get(gb))):
                continue
            bm = {c for cu in nc[n] for c in coh_by_curie.get(cu, set())}
            rm = refmet.get(nn, "")
            mo = coh_by_refmet.get(rm, set()) if rm else set()
            if bm and mo:
                grp, part = "overlap", bm | mo
            elif bm:
                grp, part = "biomapper_only", bm
            elif mo:
                grp, part = "monti_only", mo
            else:
                continue
            pblocks = [(p, cblk.get(p)) for p in part if cblk.get(p)]
            if not gb or not pblocks:
                rec = {"name": n, "group": grp, "verdict": "refused",
                       "necs_block": gb, "partner": None, "partner_block": None}
            elif any(gb == b for _, b in pblocks):
                mp = next(p for p, b in pblocks if b == gb)
                rec = {"name": n, "group": grp, "verdict": "certified",
                       "necs_block": gb, "partner": mp, "partner_block": gb}
            else:
                p0, b0 = pblocks[0]
                rec = {"name": n, "group": grp, "verdict": "refuted",
                       "necs_block": gb, "partner": p0, "partner_block": b0}
            groups[grp][rec["verdict"]].append(rec)
        full[cohort] = groups
    return full


def emit_full(run_dir, refmet_cache, gold_tsv, out_path=None):
    """Build the full per-name emit and write it to ``<run>/certificate_full.json``."""
    full = build_full(run_dir, refmet_cache, gold_tsv)
    out = Path(out_path) if out_path else Path(run_dir).expanduser() / "certificate_full.json"
    out.write_text(json.dumps(full, indent=2))
    return full, out


def reconcile(full, artifact):
    """Compare the full-emit per (pair, group, verdict) counts + refused_species_lipid against the
    shipped artifact. Returns ``(ok: bool, table: list[dict])`` with one row per cell and a mismatch flag.
    """
    table, ok = [], True
    for cohort in PAIRS:
        art_counts = artifact[cohort]["counts"]
        art_lipid = artifact[cohort]["refused_species_lipid"]
        for g in ("overlap", "biomapper_only", "monti_only"):
            for v in ("certified", "refuted", "refused"):
                got, exp = len(full[cohort][g][v]), art_counts[g][v]
                cell_ok = got == exp
                ok = ok and cell_ok
                table.append({"pair": cohort, "group": g, "verdict": v, "full": got, "artifact": exp, "match": cell_ok})
            # refused_species_lipid recomputed from the full refused list
            got_lip = sum(1 for e in full[cohort][g]["refused"] if ca.is_species_level_lipid(e["name"]))
            exp_lip = art_lipid[g]
            lip_ok = got_lip == exp_lip
            ok = ok and lip_ok
            table.append({"pair": cohort, "group": g, "verdict": "refused_species_lipid",
                          "full": got_lip, "artifact": exp_lip, "match": lip_ok})
    return ok, table


# --------------------------------------------------------------------------------------------------
# Unit 2: target-population selection
# --------------------------------------------------------------------------------------------------
def select_targets(full):
    """Select overlap-refuted + monti_only-certified + biomapper_only-certified, both pairs,
    dropping species-level lipids. Returns ``(rows, dropped_lipids)``. Every row carries a
    ``necs_block`` and a ``partner_block`` by construction (certified/refuted both have blocks)."""
    rows, dropped = [], []
    for cohort in PAIRS:
        for grp, verdict in TARGET_SETS:
            for rec in full[cohort][grp][verdict]:
                if ca.is_species_level_lipid(rec["name"]):
                    dropped.append({"pair": cohort, **rec})
                    continue
                rows.append({"pair": cohort, "group": grp, "verdict": verdict,
                             "necs_name": rec["name"], "partner_name": rec["partner"],
                             "necs_block": rec["necs_block"], "partner_block": rec["partner_block"]})
    return rows, dropped


# --------------------------------------------------------------------------------------------------
# Unit 3: independent PubChem resolution (cached, block-guarded, polite, no auto-pick)
# --------------------------------------------------------------------------------------------------
def normalize_name(name):
    return (name or "").strip().lower()


def is_valid_block(block):
    """True only for a canonical 14-char InChIKey first block; e.g. ``4000`` is non-comparable."""
    return bool(block) and bool(BLOCK_RE.match(block))


_LAST_FETCH = [0.0]  # module-level throttle state (politeness: <=5 req/s to PUG-REST)


def _pug_get(url, timeout=20):
    dt = time.monotonic() - _LAST_FETCH[0]
    if dt < 0.22:  # >=220ms between live calls -> under 5 req/s
        time.sleep(0.22 - dt)
    req = urllib.request.Request(url, headers={"User-Agent": "biomapper2-readjudication/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:  # 404/503/5xx: return the code so retry/backoff can act
        return e.code, (e.read().decode("utf-8", "replace") if e.fp else "")
    finally:
        _LAST_FETCH[0] = time.monotonic()


def pubchem_lookup(name, cache, fetch=None, max_retries=4):
    """Resolve ``name`` to a PubChem first-block InChIKey + MolecularFormula via exact-name PUG-REST.

    - single exact CID  -> {"status":"resolved","block":<14>,"formula":...,"cid":...}
    - multiple CIDs     -> {"status":"multi", candidates:[...], "review":True}  (NO auto-pick)
    - no match / error  -> {"status":"unresolvable","review":True}
    Cached by normalized name; a warm cache makes reruns offline + byte-identical.
    """
    key = normalize_name(name)
    if key in cache:
        return cache[key]
    fetch = fetch or _pug_get
    enc = urllib.parse.quote(name, safe="")
    url = f"{_PUG}/compound/name/{enc}/property/InChIKey,MolecularFormula/JSON"
    result = None
    for attempt in range(max_retries):
        try:
            status, body = fetch(url)
        except Exception as e:  # noqa: BLE001 - any transport error -> unresolvable
            result = {"status": "unresolvable", "review": True, "error": f"{type(e).__name__}"}
            break
        if status == 503:  # PUG-REST throttling; back off and retry
            time.sleep(0.6 * (attempt + 1))
            continue
        if status == 404:
            result = {"status": "unresolvable", "review": True, "error": "no exact-name match"}
            break
        if status != 200:
            result = {"status": "unresolvable", "review": True, "error": f"http {status}"}
            break
        try:
            props = json.loads(body)["PropertyTable"]["Properties"]
        except Exception:  # noqa: BLE001
            result = {"status": "unresolvable", "review": True, "error": "unparseable"}
            break
        cands = []
        for p in props:
            ik = (p.get("InChIKey") or "").strip()
            blk = ik.split("-")[0] if ik else ""
            cands.append({"cid": p.get("CID"), "block": blk, "formula": (p.get("MolecularFormula") or "").strip()})
        if not cands:
            result = {"status": "unresolvable", "review": True, "error": "empty property table"}
        elif len({c["block"] for c in cands}) == 1 and len(cands) == 1:
            c = cands[0]
            result = {"status": "resolved", "block": c["block"], "formula": c["formula"], "cid": c["cid"],
                      "review": not is_valid_block(c["block"])}
        elif len({c["block"] for c in cands}) == 1:
            # multiple CIDs but a single unambiguous first block (salts/stereo of one skeleton) -> resolve, flag
            c = cands[0]
            result = {"status": "resolved", "block": c["block"], "formula": c["formula"], "cid": c["cid"],
                      "review": True, "candidates": cands}
        else:
            result = {"status": "multi", "review": True, "candidates": cands}
        break
    if result is None:  # exhausted retries on 503
        result = {"status": "unresolvable", "review": True, "error": "throttled (503) after retries"}
    cache[key] = result
    return result


def load_cache(path=PUBCHEM_CACHE):
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else {}


def save_cache(cache, path=PUBCHEM_CACHE):
    Path(path).write_text(json.dumps(cache, indent=2, sort_keys=True))


# --------------------------------------------------------------------------------------------------
# Unit 4: classification
# --------------------------------------------------------------------------------------------------
def classify(verdict, pc_necs, pc_partner):
    """Classify one target row against the two independent PubChem hits.

    Returns ``(classification, review_flag)``. The ledger-L3 guard is universal: a first-block match
    with a DIFFERING molecular formula routes to review, never auto-agreement.
    """
    n_ok = pc_necs.get("status") == "resolved" and is_valid_block(pc_necs.get("block"))
    p_ok = pc_partner.get("status") == "resolved" and is_valid_block(pc_partner.get("block"))
    if not (n_ok and p_ok):
        return "unresolvable", True

    nb, pb = pc_necs["block"], pc_partner["block"]
    nf, pf = (pc_necs.get("formula") or ""), (pc_partner.get("formula") or "")
    same_block = nb == pb
    same_formula = bool(nf) and bool(pf) and nf == pf
    review = bool(pc_necs.get("review") or pc_partner.get("review"))

    if same_block and not same_formula:
        # L3 guard: block agrees but formula disagrees (tautomer/charge) -> never auto-agree
        return "review-l3-formula-mismatch", True

    if verdict == "refuted":  # overlap-refuted bucket
        if same_block:
            return "false-refutation", review           # PubChem says same structure -> gold defect
        if same_formula:
            return "convention-difference", review       # same formula, different block (acid/anion, anomer)
        return "real-disagreement", review               # genuinely different structures
    # certified bucket (monti_only / biomapper_only)
    if same_block:
        return "confirmed-genuine", review               # both names -> same PubChem structure
    if same_formula:
        return "convention-difference", True             # certified on equal formula but PubChem differs -> review
    return "spurious-certification", review              # gold blocks matched but PubChem disagrees


# --------------------------------------------------------------------------------------------------
# Unit 3+4 driver + Unit 5 outputs
# --------------------------------------------------------------------------------------------------
TABLE_COLUMNS = ["pair", "group", "verdict", "necs_name", "partner_name", "necs_block", "partner_block",
                 "pubchem_necs_block", "pubchem_partner_block", "formula_necs", "formula_partner",
                 "classification", "review_flag"]


def adjudicate(rows, cache, fetch=None):
    """Resolve + classify every target row. Mutates ``cache``. Returns table rows (list of dicts)."""
    out = []
    for r in rows:
        pc_n = pubchem_lookup(r["necs_name"], cache, fetch=fetch)
        pc_p = pubchem_lookup(r["partner_name"], cache, fetch=fetch)
        # Block-shape guard on the GOLD blocks too: a non-InChIKey gold token (e.g. "4000") is
        # non-comparable and forces review regardless of PubChem.
        gold_nonstandard = not is_valid_block(r["necs_block"]) or not is_valid_block(r["partner_block"])
        classification, review = classify(r["verdict"], pc_n, pc_p)
        if gold_nonstandard:
            review = True
            if classification not in ("unresolvable",):
                classification = "review-nonstandard-gold-block"
        out.append({
            "pair": r["pair"], "group": r["group"], "verdict": r["verdict"],
            "necs_name": r["necs_name"], "partner_name": r["partner_name"],
            "necs_block": r["necs_block"], "partner_block": r["partner_block"],
            "pubchem_necs_block": pc_n.get("block", ""), "pubchem_partner_block": pc_p.get("block", ""),
            "formula_necs": pc_n.get("formula", ""), "formula_partner": pc_p.get("formula", ""),
            "classification": classification, "review_flag": bool(review),
        })
    return out


_ENDPOINT_RE = re.compile(r"127\.0\.0\.1|(?:baseline|treatment)_api")


def assert_no_endpoint_leak(text):
    """Pre-write guard: no output may carry an internal endpoint or a manifest ``*_api`` URL."""
    m = _ENDPOINT_RE.search(text or "")
    if m:
        raise AssertionError(f"endpoint leak in output: {m.group(0)!r}")


def write_table(table_rows, path):
    """Write the per-name re-adjudication table as CSV (endpoint-leak guarded)."""
    import csv
    import io
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=TABLE_COLUMNS, extrasaction="ignore")
    w.writeheader()
    for r in table_rows:
        w.writerow(r)
    text = buf.getvalue()
    assert_no_endpoint_leak(text)
    Path(path).write_text(text)
    return path


def summarize(table_rows):
    """Per-pair classification counts for overlap-refuted and the certified buckets."""
    summary = {}
    for cohort in PAIRS:
        summary[cohort] = {"overlap_refuted": defaultdict(int), "certified": defaultdict(int)}
    for r in table_rows:
        bucket = "overlap_refuted" if r["verdict"] == "refuted" else "certified"
        summary[r["pair"]][bucket][r["classification"]] += 1
    return {c: {b: dict(d) for b, d in v.items()} for c, v in summary.items()}


PROVENANCE = {
    "analysis": "Independent PubChem re-adjudication of the cross-cohort certificate (overlap-refuted + certified misses)",
    "run_id": "ab_lipid_oracle_20260907T235106Z",
    "kg_build": "mg:d7dddb3e5b51be69",
    "rdkit": "2025.09.3",
    "date": "2026-09-14",
    "arbiter": "PubChem PUG-REST compound/name/<name>/property/InChIKey,MolecularFormula (independent of KG and of gold)",
    "note": "clean run covers arivale + xuetal only; the superseded ~/arm-m-report/ set also had blsa + llfs, NOT in this run.",
}


def main():  # pragma: no cover
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", default=os.environ.get("AB_RUN_DIR") or str(PINNED_RUN_DIR))
    ap.add_argument("--refmet-cache", default=os.environ.get("REFMET_CACHE") or str(PINNED_REFMET_CACHE))
    ap.add_argument("--gold-tsv", default=os.environ.get("NECS_GOLD_TSV") or str(PINNED_GOLD_TSV))
    ap.add_argument("--offline", action="store_true", help="warm-cache only; never hit the network")
    args = ap.parse_args()
    run_dir = Path(args.run_dir).expanduser()

    full, full_path = emit_full(run_dir, args.refmet_cache, args.gold_tsv)
    artifact = json.loads((run_dir / "certificate_adjudication.json").read_text())
    ok, table = reconcile(full, artifact)
    print("[reconcile] " + ("PASS" if ok else "FAIL"))
    for row in table:
        if not row["match"]:
            print(f"  MISMATCH {row}")
    if not ok:
        raise SystemExit("reconciliation failed - env inputs are wrong; not proceeding")
    print(f"[full] {full_path}")

    rows, dropped = select_targets(full)
    print(f"[select] {len(rows)} target rows; dropped {len(dropped)} species-lipids")

    cache = load_cache()
    fetch = (lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline"))) if args.offline else None
    table_rows = adjudicate(rows, cache, fetch=fetch)
    save_cache(cache)

    here = Path(__file__).parent
    csv_path = write_table(table_rows, here / "readjudication_table.csv")
    print(f"[table] {csv_path}")

    summary = summarize(table_rows)
    prov = {**PROVENANCE, "summary": summary,
            "unresolvable": sum(1 for r in table_rows if r["classification"] == "unresolvable"),
            "n_rows": len(table_rows)}
    assert_no_endpoint_leak(json.dumps(prov))
    (here / "readjudication_summary.json").write_text(json.dumps(prov, indent=2))
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
