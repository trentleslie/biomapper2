"""Re-adjudicate the 16S panel's no-node truth rows through an independent path (16S plan U4, R19).

The baseline panel (vault ``16s_probe/datasets/run_20261118T182527Z``) built its truth with NCBI
E-utilities, but its name lookup used the raw label token, so names written ``Candidatus_X`` (or glued
``CandidatusX``) never matched and those rows were recorded as "no NCBI node" (cat ``c``). The abstention
baseline rests on those rows, so no number is quoted until they are fixed.

For every cat ``c`` row this script:

1. takes the deepest named level with its own minimal grammar (deliberately NOT ``core/taxon_label.py``,
   the system under test), and normalizes only spelling: ``Candidatus_`` and glued ``CandidatusX`` to
   ``Candidatus X``, underscores to spaces;
2. looks the name up in live NCBI E-utilities (scientific name, then all name classes, prokaryote subtree,
   at the label's rank): path 1, independent of the snapshot;
3. looks the same name up in the pinned snapshot (``core/ncbi_taxonomy.py``): path 2;
4. moves the row to cat ``a`` only when both paths name the same taxid. A disagreement, a single-path hit,
   or a hit that needs bracket stripping goes to the HUMAN list (``decision=human``) and the row stays
   cat ``c``. Every row is logged with its evidence in ``truth_fix_log.tsv``.

It also adds the bare-name control rows (prokaryote genera plus "Homo sapiens", "E. coli", "mouse",
"Saccharomyces cerevisiae"), each verified live against E-utilities.

Usage::

    uv run python -m studies.analysis.taxon_16s_truth_fix --vault-run <run_dir>

Writes into ``studies/analysis/data/taxon_16s/``: ``labels.tsv``, ``truth.json`` (corrected),
``truth_original.json`` (the vault truth, unchanged), ``truth_fix_log.tsv``, ``sources.json``,
``baseline_corrected.json`` (the vault's throwaway-cleaner scores re-tallied on the corrected truth) and
``SHA256SUMS``.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import time
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any

import requests

from biomapper2.config import get_cache_dir
from biomapper2.core import ncbi_taxonomy

DATA_DIR = Path(__file__).parent / "data" / "taxon_16s"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
PROK = "(txid2[Subtree] OR txid2157[Subtree])"
OK_CATEGORIES = {"CORRECT", "CORRECT-PARENT", "CORRECT-STALE-ID"}

_PFX = {"k": "kingdom", "sk": "domain", "d": "domain", "p": "phylum", "c": "class", "o": "order", "f": "family"}
_PFX["g"] = "genus"
_SILVA = {0: "domain", 1: "phylum", 2: "class", 3: "order", 4: "family", 5: "genus"}
_PLACEHOLDER = re.compile(
    r"^(uncultured|incertae sedis|unidentified|unclassified|unknown|ambiguous_taxa|metagenome)$", re.I
)

# Bare-name controls: label -> (expected NCBI taxid, rank). Each is verified live before it is written.
BARE_CONTROLS: dict[str, tuple[str, str]] = {
    "Bacteroides": ("816", "genus"),
    "Faecalibacterium": ("216851", "genus"),
    "Akkermansia": ("239934", "genus"),
    "Prevotella": ("838", "genus"),
    "Escherichia": ("561", "genus"),
    "Bacillus": ("1386", "genus"),
    "Proteus": ("583", "genus"),
    "Homo sapiens": ("9606", "species"),
    "E. coli": ("562", "species"),
    "mouse": ("10090", "species"),
    "Saccharomyces cerevisiae": ("4932", "species"),
}


# ------------------------------------------------------------------------------------------- E-utilities


class Eutils:
    """Cached, rate-limited (<= 3 req/s) NCBI E-utilities client. Failures raise; nothing caches an error."""

    def __init__(self, cache_path: Path | None = None):
        self.cache_path = cache_path or (get_cache_dir() / "ncbi_eutils_taxon_16s.json")
        self.cache: dict[str, Any] = json.loads(self.cache_path.read_text()) if self.cache_path.exists() else {}
        self._last = 0.0
        self.calls = 0

    def save(self) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.cache))
        tmp.replace(self.cache_path)

    def _get(self, path: str, params: dict[str, str], as_json: bool = True) -> Any:
        key = path + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        if key in self.cache:
            return self.cache[key]
        last_exc: Exception | None = None
        for attempt in range(5):
            wait = 0.36 - (time.time() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.time()
            try:
                self.calls += 1
                resp = requests.get(EUTILS + path, params=params, timeout=60, headers={"User-Agent": "taxon-16s/1"})
                resp.raise_for_status()
                out = resp.json() if as_json else resp.text
                self.cache[key] = out
                return out
            except Exception as exc:  # noqa: BLE001 - retried, then re-raised
                last_exc = exc
                time.sleep(2 + 2 * attempt)
        raise RuntimeError(f"E-utilities failed for {key}: {last_exc}")

    def esearch(self, term: str, retmax: int = 20) -> list[str]:
        out = self._get("/esearch.fcgi", {"db": "taxonomy", "retmode": "json", "retmax": str(retmax), "term": term})
        return list(out["esearchresult"].get("idlist", []))

    def esummary(self, ids: list[str]) -> dict[str, dict]:
        result: dict[str, dict] = {}
        for i in range(0, len(ids), 150):
            chunk = ids[i : i + 150]
            out = self._get("/esummary.fcgi", {"db": "taxonomy", "retmode": "json", "id": ",".join(chunk)})
            for uid in out["result"].get("uids", []):
                result[uid] = out["result"][uid]
        return result

    def lineage(self, ids: list[str]) -> dict[str, dict]:
        """taxid -> {taxid (current), name, rank, lineage (root..parent)}; merged aliases map to the current."""
        result: dict[str, dict] = {}
        ids = sorted({str(i) for i in ids if i})
        for i in range(0, len(ids), 150):
            chunk = ids[i : i + 150]
            xml = self._get("/efetch.fcgi", {"db": "taxonomy", "retmode": "xml", "id": ",".join(chunk)}, as_json=False)
            for taxon in ET.fromstring(xml).findall("Taxon"):
                tid = taxon.findtext("TaxId") or ""
                rec = {
                    "taxid": tid,
                    "name": taxon.findtext("ScientificName"),
                    "rank": taxon.findtext("Rank"),
                    "lineage": [x.findtext("TaxId") for x in taxon.findall("LineageEx/Taxon")],
                }
                result[tid] = rec
                for aka in taxon.findall("AkaTaxIds/TaxId"):
                    if aka.text:
                        result[aka.text] = rec
        return result

    def lookup(self, name: str, rank: str, prokaryote_only: bool = True) -> tuple[list[str], str]:
        """Taxids at ``rank`` named ``name`` (scientific name first, then all names). how = exact|synonym|''."""
        q = name.replace('"', "")
        scope = f" AND {PROK}" if prokaryote_only else ""
        for field, how in (("Scientific Name", "exact"), ("All Names", "synonym")):
            ids = self.esearch(f'"{q}"[{field}]{scope}')
            if ids:
                summary = self.esummary(ids)
                hits = sorted(i for i in ids if summary.get(i, {}).get("rank") == rank)
                if hits:
                    return hits, how
        return [], ""


# ------------------------------------------------------------------------------------------------ fixing


def _levels(label: str) -> list[tuple[str | None, str]]:
    out: list[tuple[str | None, str]] = []
    for part in [x.strip() for x in label.split(";")]:
        if part in ("Root", ""):
            continue
        m = re.match(r"^(sk|[kdpcofg])__(.*)$", part)
        if m:
            out.append((_PFX[m.group(1)], m.group(2).strip()))
            continue
        m = re.match(r"^D_(\d)__(.*)$", part)
        if m:
            out.append((_SILVA.get(int(m.group(1))), m.group(2).strip()))
            continue
        out.append((None, part))
    return out


def normalize_spelling(name: str) -> str:
    """Spelling-only normalization: Candidatus_X / CandidatusX -> Candidatus X; underscores -> spaces."""
    name = re.sub(r"^Candidatus_?(?=[A-Z])", "Candidatus ", name.strip())
    return " ".join(name.replace("_", " ").split())


def adjudicate_row(label: str, eutils: Eutils) -> dict[str, Any]:
    """Evidence and decision for one cat-c row (decision: move | human | keep)."""
    named = [(rk, n) for rk, n in _levels(label) if n and not _PLACEHOLDER.match(n)]
    if not named:
        return {"decision": "keep", "reason": "no named level"}
    rank, raw = named[-1]
    if rank is None:
        return {"decision": "keep", "reason": "deepest level has no rank", "name": raw}
    name = normalize_spelling(raw)
    evidence: dict[str, Any] = {"name": name, "rank": rank, "raw": raw}
    stripped = name.replace("[", "").replace("]", "").strip()
    eu_ids, eu_how = eutils.lookup(name, rank)
    snap_ids = [str(t) for t in ncbi_taxonomy.lookup(name, rank=rank)]
    evidence.update(eutils_ids=eu_ids, eutils_how=eu_how, snapshot_ids=snap_ids)
    if not eu_ids and stripped != name:
        alt_ids, alt_how = eutils.lookup(stripped, rank)
        evidence.update(bracket_stripped_eutils_ids=alt_ids, bracket_stripped_how=alt_how)
        if alt_ids:
            return {**evidence, "decision": "human", "reason": "resolves only with brackets stripped"}
    if eu_ids and snap_ids and sorted(eu_ids) == sorted(snap_ids):
        return {**evidence, "decision": "move", "reason": "both paths agree", "targets": eu_ids}
    if eu_ids or snap_ids:
        return {**evidence, "decision": "human", "reason": "paths disagree"}
    return {**evidence, "decision": "keep", "reason": "no NCBI node on either path"}


def fix_truth(rows: list[dict], truth: dict[str, dict], eutils: Eutils) -> tuple[dict[str, dict], list[dict]]:
    fixed = json.loads(json.dumps(truth))
    log: list[dict] = []
    for row in rows:
        rec = truth[row["id"]]
        if rec["cat"] != "c":
            continue
        result = adjudicate_row(row["label"], eutils)
        if result["decision"] == "move":
            fixed[row["id"]].update(
                cat="a",
                rule="A-fix" if result["eutils_how"] == "exact" else "A'-fix",
                targets=result["targets"],
                target_rank=result["rank"],
                fixed_by="taxon_16s_truth_fix",
            )
        log.append(
            {
                "id": row["id"],
                "source": row["source"],
                "label": row["label"],
                "old_cat": rec["cat"],
                "old_rule": rec.get("rule"),
                "new_cat": fixed[row["id"]]["cat"],
                "decision": result["decision"],
                "reason": result.get("reason", ""),
                "name": result.get("name", ""),
                "rank": result.get("rank", ""),
                "eutils_ids": "|".join(result.get("eutils_ids", [])),
                "eutils_how": result.get("eutils_how", ""),
                "snapshot_ids": "|".join(result.get("snapshot_ids", [])),
                "bracket_stripped_eutils_ids": "|".join(result.get("bracket_stripped_eutils_ids", [])),
            }
        )
    return fixed, log


def bare_control_rows(eutils: Eutils) -> tuple[list[dict], dict[str, dict], list[dict]]:
    rows, truth, problems = [], {}, []
    for i, (label, (taxid, rank)) in enumerate(BARE_CONTROLS.items()):
        rid = f"bare_controls:{i:03d}"
        ids = eutils.esearch(f'"{label}"[All Names]')
        if taxid not in ids:
            problems.append({"label": label, "expected": taxid, "eutils_ids": ids})
        rows.append({"id": rid, "source": "bare_controls", "label": label, "n_units": "1", "reads": "0.0"})
        truth[rid] = {
            "id": rid,
            "source": "bare_controls",
            "label": label,
            "cat": "a",
            "rule": "A-control",
            "targets": [taxid],
            "target_rank": rank,
            "deepest": rank,
            "euk": taxid in {"9606", "10090", "4932"},
            "organelle": False,
        }
    return rows, truth, problems


# ------------------------------------------------------------------------------- corrected baseline


def _ncbi_of_hit(hit: str) -> str | None:
    curie = (hit or "").split(" ", 1)[0]
    return curie.split(":", 1)[1] if curie.startswith("NCBITaxon:") else None


def corrected_baseline(scored_rows: list[dict], fixed: dict[str, dict], eutils: Eutils) -> dict[str, Any]:
    """Re-tally the vault's hybrid-clean top-1 categories (the throwaway cleaner) on the corrected truth.

    Rows whose truth did not change keep the vault's category. Moved rows are re-scored: their old
    ``NO-HIT`` (formerly a correct abstention) is now a miss, and a hit is CORRECT only when its taxid,
    or its merge target per live NCBI, is a new target.
    """
    moved = {rid for rid, rec in fixed.items() if rec.get("fixed_by")}
    hit_ids = [t for r in scored_rows if r["id"] in moved and (t := _ncbi_of_hit(r["hybrid_clean_hit"]))]
    lineage = eutils.lineage(hit_ids)
    per_source: dict[str, Counter] = {}
    for r in scored_rows:
        rec = fixed[r["id"]]
        category = r["hybrid_clean_top1"]
        if r["id"] in moved:
            t = _ncbi_of_hit(r["hybrid_clean_hit"])
            if category == "NO-HIT" or t is None:
                pass  # a non-NCBI hit stays DUP/NON-NCBI; an abstention is now a miss (cat a)
            elif t in rec["targets"]:
                category = "CORRECT"
            elif (lineage.get(t) or {}).get("taxid") in rec["targets"]:
                category = "CORRECT-STALE-ID"
            else:
                category = "WRONG-TAXON-or-RANK"
        ok = category in OK_CATEGORIES or (rec["cat"] == "c" and category == "NO-HIT")
        for key in (r["source"], "ALL"):
            c = per_source.setdefault(key, Counter())
            if rec["cat"] == "x":
                continue
            c["n_scored"] += 1
            c["acceptable"] += int(ok)
            c["units"] += int(r["n_units"])
            c["acceptable_units"] += int(r["n_units"]) * int(ok)
            if rec["cat"] == "c":
                c["no_node_rows"] += 1
                c["no_node_abstained"] += int(category == "NO-HIT")
    out: dict[str, Any] = {}
    for key, c in per_source.items():
        out[key] = {
            **dict(c),
            "acceptable_rate": round(c["acceptable"] / c["n_scored"], 4) if c["n_scored"] else None,
            "acceptable_unit_wt": round(c["acceptable_units"] / c["units"], 4) if c["units"] else None,
        }
    return out


# ----------------------------------------------------------------------------------------------- main


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(vault_run: Path, out_dir: Path = DATA_DIR) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = list(csv.DictReader((vault_run / "labels.tsv").open(), delimiter="\t"))
    truth = json.loads((vault_run / "truth.json").read_text())
    scored = list(csv.DictReader((vault_run / "scored.tsv").open(), delimiter="\t"))
    eutils = Eutils()
    try:
        fixed, log = fix_truth(rows, truth, eutils)
        bare_rows, bare_truth, problems = bare_control_rows(eutils)
        baseline = corrected_baseline(scored, fixed, eutils)
    finally:
        eutils.save()
    if problems:
        raise SystemExit(f"bare-control verification failed: {problems}")

    fields = ["id", "source", "label", "n_units", "reads"]
    with (out_dir / "labels.tsv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows([{k: r[k] for k in fields} for r in rows + bare_rows])
    (out_dir / "truth.json").write_text(json.dumps({**fixed, **bare_truth}, indent=1) + "\n")
    shutil.copy(vault_run / "truth.json", out_dir / "truth_original.json")
    sources = json.loads((vault_run / "sources.json").read_text())
    sources["sources"]["bare_controls"] = {
        "host": "none (bare-name controls)",
        "reference": "hand-picked; each verified against live NCBI E-utilities by taxon_16s_truth_fix.py",
        "n_sampled": len(bare_rows),
    }
    (out_dir / "sources.json").write_text(json.dumps(sources, indent=1) + "\n")
    with (out_dir / "truth_fix_log.tsv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(log[0]), delimiter="\t", lineterminator="\n")
        writer.writeheader()
        writer.writerows(log)
    summary = {
        "vault_run": vault_run.name,
        "vault_inputs_sha256": {n: _sha256(vault_run / n) for n in ("labels.tsv", "truth.json", "scored.tsv")},
        "snapshot_version": ncbi_taxonomy.version(),
        "eutils_calls_uncached": eutils.calls,
        "no_node_rows_before": sum(1 for r in truth.values() if r["cat"] == "c"),
        "decisions": dict(Counter(x["decision"] for x in log)),
        "no_node_rows_after": sum(1 for r in fixed.values() if r["cat"] == "c"),
        "human_list": [x["id"] for x in log if x["decision"] == "human"],
        "baseline_hybrid_clean_top1_on_corrected_truth": baseline,
    }
    (out_dir / "baseline_corrected.json").write_text(json.dumps(summary, indent=1) + "\n")
    names = sorted(p.name for p in out_dir.iterdir() if p.is_file() and p.name != "SHA256SUMS")
    (out_dir / "SHA256SUMS").write_text("".join(f"{_sha256(out_dir / n)}  {n}\n" for n in names))
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--vault-run", type=Path, required=True, help="the baseline run dir (labels/truth/scored)")
    parser.add_argument("--out-dir", type=Path, default=DATA_DIR)
    args = parser.parse_args(argv)
    summary = run(args.vault_run, args.out_dir)
    print(json.dumps({k: v for k, v in summary.items() if k != "baseline_hybrid_clean_top1_on_corrected_truth"}, indent=1))
    print("ALL:", summary["baseline_hybrid_clean_top1_on_corrected_truth"].get("ALL"))
    print(f"wrote {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
