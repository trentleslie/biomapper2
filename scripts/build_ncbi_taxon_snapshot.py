#!/usr/bin/env python3
"""Build the pinned NCBI prokaryote taxonomy snapshot used by the 16S taxon annotator.

Usage::

    # From a downloaded taxdump (https://ftp.ncbi.nlm.nih.gov/pub/taxonomy/taxdump.tar.gz)
    uv run python scripts/build_ncbi_taxon_snapshot.py --taxdump /path/to/taxdump.tar.gz

    # Download it first (about 80 MB)
    uv run python scripts/build_ncbi_taxon_snapshot.py --download

    # Also cross-check a sample against TaxonKit (downloads the pinned MIT release binary to a temp dir)
    uv run python scripts/build_ncbi_taxon_snapshot.py --taxdump taxdump.tar.gz --verify-with-taxonkit

    # Write the small test fixture subset instead of the packaged snapshot
    uv run python scripts/build_ncbi_taxon_snapshot.py --taxdump taxdump.tar.gz \\
        --out-dir tests/fixtures/ncbi_taxonomy --subset-taxids 1263,572511,1239,...

What it writes into ``--out-dir`` (default ``src/biomapper2/data/ncbi_taxonomy``), ``<date>`` being the
taxdump's own build date:

* ``prokaryote_taxa_<date>.tsv`` (``taxid parent_taxid rank name name_class``): every Bacteria (2) and
  Archaea (2157) node from domain down to genus, plus every ancestor on each path whatever its rank
  (clade, no rank), so a parent pointer always resolves inside the snapshot. The domain nodes carry an
  empty parent. Name classes kept: scientific name, synonym, equivalent name, includes, and genbank
  common name at phylum rank only (it carries the legacy phylum names, e.g. "firmicutes" on Bacillota
  1239; R6). A synonym written with its author citation ("Actinobacteria Stackebrandt et al. 1997") also
  yields its bare Latin name under class ``synonym (authority stripped)``.
* ``merged_<date>.tsv`` (``old_taxid new_taxid``): merged ids whose current id is in the snapshot.
* ``homonyms_<date>.tsv`` (``name prokaryote_taxids nonprokaryote_taxids``): prokaryote names at genus
  level and above that also name a non-prokaryote node (Bacillus -> 55087, Proteus -> 210425). Ids are
  ``|``-joined.
* ``prokaryote_taxa_<date>.tsv.version``: first line is the version stamp the loader reports; later lines
  record the taxdump sha256/md5 and, when run, the TaxonKit version and cross-check result.

Rebuild cadence: NCBI renames and merges taxa continuously. Rebuild when the KG build changes, or at
least quarterly, and keep the old files until the new one is benchmarked.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import random
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

TAXDUMP_URL = "https://ftp.ncbi.nlm.nih.gov/pub/taxonomy/taxdump.tar.gz"
TAXONKIT_VERSION = "v0.20.0"
TAXONKIT_URL = (
    f"https://github.com/shenwei356/taxonkit/releases/download/{TAXONKIT_VERSION}/taxonkit_linux_amd64.tar.gz"
)
PROKARYOTE_ROOTS = (2, 2157)
# Every rank from domain down to genus. Both "superkingdom" (pre-2025) and "domain" spellings are kept.
KEPT_RANKS = frozenset(
    {
        "superkingdom",
        "domain",
        "realm",
        "kingdom",
        "subkingdom",
        "superphylum",
        "phylum",
        "subphylum",
        "superclass",
        "class",
        "subclass",
        "infraclass",
        "cohort",
        "subcohort",
        "superorder",
        "order",
        "suborder",
        "infraorder",
        "parvorder",
        "superfamily",
        "family",
        "subfamily",
        "tribe",
        "subtribe",
        "genus",
    }
)
NAME_CLASSES = ("scientific name", "synonym", "equivalent name", "includes")
PHYLUM_ONLY_CLASS = "genbank common name"
STRIPPED_CLASS = "synonym (authority stripped)"
HOMONYM_SOURCE_CLASSES = frozenset(NAME_CLASSES)
_AUTHORITY = re.compile(r"^((?:Candidatus )?[A-Z][a-z]+)\s+(?:corrig\.\s+)?[\"(]?[A-Z].*\b(?:1[789]\d\d|20\d\d)\b")


def _dmp_rows(handle: io.TextIOBase):
    for line in handle:
        yield [field.strip() for field in line.rstrip("\n").rstrip("|").split("\t|\t")]


def _open_member(tar: tarfile.TarFile, name: str) -> io.TextIOWrapper:
    member = tar.extractfile(name)
    if member is None:
        raise SystemExit(f"taxdump has no {name}")
    return io.TextIOWrapper(member, encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _md5(path: Path) -> str:
    digest = hashlib.md5()  # noqa: S324 - matches NCBI's published .md5, not used for security
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(taxdump: Path, subset: set[int] | None = None) -> dict:
    """Read the taxdump and return the snapshot tables (pure apart from reading the archive)."""
    with tarfile.open(taxdump, "r:gz") as tar:
        dump_date = datetime.fromtimestamp(tar.getmember("nodes.dmp").mtime, tz=timezone.utc).date().isoformat()
        parent: dict[int, int] = {}
        rank: dict[int, str] = {}
        for row in _dmp_rows(_open_member(tar, "nodes.dmp")):
            tid = int(row[0])
            parent[tid] = int(row[1])
            rank[tid] = row[2]

        # Prokaryote membership by walking up once per node (memoized).
        domain_of: dict[int, int | None] = {root: root for root in PROKARYOTE_ROOTS}

        def _domain(tid: int) -> int | None:
            path = []
            node = tid
            while node not in domain_of:
                path.append(node)
                up = parent.get(node)
                if up is None or up == node:
                    domain_of[node] = None
                    break
                node = up
            result = domain_of[node]
            for visited in path:
                domain_of[visited] = result
            return result

        kept: set[int] = set()
        for tid, node_rank in rank.items():
            if node_rank in KEPT_RANKS and _domain(tid) is not None:
                kept.add(tid)
        # Every ancestor on each path, whatever its rank, up to the domain node.
        for tid in list(kept):
            node = tid
            while node not in PROKARYOTE_ROOTS:
                node = parent[node]
                kept.add(node)
        if subset is not None:
            closed: set[int] = set()
            for tid in subset:
                if tid not in kept:
                    raise SystemExit(f"subset taxid {tid} is not a kept prokaryote node")
                node = tid
                closed.add(node)
                while node not in PROKARYOTE_ROOTS:
                    node = parent[node]
                    closed.add(node)
            kept = closed

        names: list[tuple[int, str, str]] = []
        prok_names_cf: dict[str, set[int]] = defaultdict(set)
        nonprok_by_name_cf: dict[str, set[int]] = defaultdict(set)
        for row in _dmp_rows(_open_member(tar, "names.dmp")):
            tid, name, name_class = int(row[0]), row[1], row[3]
            if tid in kept:
                if name_class in NAME_CLASSES or (name_class == PHYLUM_ONLY_CLASS and rank[tid] == "phylum"):
                    names.append((tid, name, name_class))
                    if name_class in HOMONYM_SOURCE_CLASSES:
                        prok_names_cf[name.casefold()].add(tid)
                if name_class in ("synonym", "equivalent name"):
                    stripped = _AUTHORITY.match(name)
                    if stripped and stripped.group(1) != name:
                        names.append((tid, stripped.group(1), STRIPPED_CLASS))
        for row in _dmp_rows(_open_member(tar, "names.dmp")):  # second pass: the non-prokaryote side
            tid, name, name_class = int(row[0]), row[1], row[3]
            if name_class in HOMONYM_SOURCE_CLASSES and _domain(tid) is None:
                key = name.casefold()
                if key in prok_names_cf:
                    nonprok_by_name_cf[key].add(tid)

        merged: list[tuple[int, int]] = []
        for row in _dmp_rows(_open_member(tar, "merged.dmp")):
            old, new = int(row[0]), int(row[1])
            if new in kept:
                merged.append((old, new))

    # A stripped synonym that only repeats a name the node already carries adds nothing.
    plain = {(tid, name) for tid, name, cls in names if cls != STRIPPED_CLASS}
    names = [(tid, name, cls) for tid, name, cls in names if cls != STRIPPED_CLASS or (tid, name) not in plain]
    names = sorted(set(names), key=lambda r: (r[0], r[2] != "scientific name", r[2], r[1]))
    display: dict[str, str] = {}
    for tid, name, name_class in names:
        if name.casefold() in nonprok_by_name_cf and name_class in HOMONYM_SOURCE_CLASSES:
            display.setdefault(name.casefold(), name)
    homonyms = sorted(
        (display[key], sorted(prok_names_cf[key]), sorted(nonprok))
        for key, nonprok in nonprok_by_name_cf.items()
        if key in display
    )
    nodes = sorted((tid, parent[tid] if tid not in PROKARYOTE_ROOTS else None, rank[tid]) for tid in kept)
    return {
        "date": dump_date,
        "nodes": nodes,
        "names": names,
        "merged": sorted(merged),
        "homonyms": homonyms,
        "rank": rank,
        "parent": parent,
    }


def write(tables: dict, out_dir: Path, version_lines: list[str]) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    date = tables["date"]
    node_info = {tid: (par, rk) for tid, par, rk in tables["nodes"]}
    named = {tid for tid, _, _ in tables["names"]}
    missing = sorted(set(node_info) - named)
    if missing:
        raise SystemExit(f"{len(missing)} kept nodes have no kept name (e.g. {missing[:5]})")
    paths = {
        "taxa": out_dir / f"prokaryote_taxa_{date}.tsv",
        "merged": out_dir / f"merged_{date}.tsv",
        "homonyms": out_dir / f"homonyms_{date}.tsv",
    }
    with paths["taxa"].open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("taxid\tparent_taxid\trank\tname\tname_class\n")
        for tid, name, name_class in tables["names"]:
            par, rk = node_info[tid]
            fh.write(f"{tid}\t{'' if par is None else par}\t{rk}\t{name}\t{name_class}\n")
    with paths["merged"].open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("old_taxid\tnew_taxid\n")
        for old, new in tables["merged"]:
            fh.write(f"{old}\t{new}\n")
    with paths["homonyms"].open("w", encoding="utf-8", newline="\n") as fh:
        fh.write("name\tprokaryote_taxids\tnonprokaryote_taxids\n")
        for name, prok, nonprok in tables["homonyms"]:
            fh.write(f"{name}\t{'|'.join(map(str, prok))}\t{'|'.join(map(str, nonprok))}\n")
    version_path = paths["taxa"].with_name(paths["taxa"].name + ".version")
    version_path.write_text("\n".join(version_lines) + "\n", encoding="utf-8")
    paths["version"] = version_path
    return paths


# ------------------------------------------------------------------------------------- TaxonKit check


def _taxonkit_binary(workdir: Path) -> tuple[Path, str]:
    archive = workdir / "taxonkit.tar.gz"
    urllib.request.urlretrieve(TAXONKIT_URL, archive)  # noqa: S310 - pinned https release URL
    with tarfile.open(archive, "r:gz") as tar:
        tar.extract("taxonkit", workdir, filter="data")
    binary = workdir / "taxonkit"
    binary.chmod(0o755)
    version = subprocess.run([binary, "version"], capture_output=True, text=True, check=True).stdout.strip()
    return binary, version


def verify_with_taxonkit(taxdump: Path, tables: dict, sample: int = 400, seed: int = 20261119) -> list[str]:
    """Cross-check a seeded sample of scientific names and lineages against TaxonKit. Raises on disagreement."""
    rng = random.Random(seed)
    scientific = [(tid, name) for tid, name, cls in tables["names"] if cls == "scientific name"]
    picked = rng.sample(scientific, min(sample, len(scientific)))
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        data = work / "data"
        data.mkdir()
        with tarfile.open(taxdump, "r:gz") as tar:
            for member in ("names.dmp", "nodes.dmp", "merged.dmp", "delnodes.dmp"):
                tar.extract(member, data, filter="data")
        binary, version = _taxonkit_binary(work)
        env = {**os.environ, "TAXONKIT_DB": str(data)}
        name_input = "\n".join(name for _, name in picked) + "\n"
        out = subprocess.run(
            [binary, "name2taxid", "--data-dir", str(data), "--show-rank"],
            input=name_input,
            capture_output=True,
            text=True,
            check=True,
            env=env,
        ).stdout
        by_name: dict[str, set[int]] = defaultdict(set)
        for line in out.splitlines():
            fields = line.split("\t")
            if len(fields) >= 2 and fields[1]:
                by_name[fields[0]].add(int(fields[1]))
        errors = [
            f"name2taxid {name!r}: {tid} not in {sorted(by_name[name])}"
            for tid, name in picked
            if tid not in by_name[name]
        ]
        lineage_out = subprocess.run(
            [binary, "lineage", "--data-dir", str(data), "--show-lineage-taxids"],
            input="\n".join(str(tid) for tid, _ in picked) + "\n",
            capture_output=True,
            text=True,
            check=True,
            env=env,
        ).stdout
        parent = tables["parent"]
        for line in lineage_out.splitlines():
            fields = line.split("\t")
            tid = int(fields[0])
            tk_path = [int(x) for x in fields[2].split(";") if x]
            ours = [tid]
            while ours[-1] not in (1,) and parent.get(ours[-1]) not in (None, ours[-1]):
                ours.append(parent[ours[-1]])
            ours = [x for x in reversed(ours) if x != 1]
            if tk_path != ours:
                errors.append(f"lineage {tid}: taxonkit {tk_path} != snapshot {ours}")
    if errors:
        raise SystemExit("TaxonKit cross-check FAILED:\n" + "\n".join(errors[:50]))
    return [f"taxonkit: {version}", f"taxonkit_check: {len(picked)} names + lineages agree (seed {seed})"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--taxdump", type=Path, help="path to taxdump.tar.gz")
    src.add_argument("--download", action="store_true", help=f"download {TAXDUMP_URL} to a temp dir first")
    parser.add_argument("--out-dir", type=Path, default=Path("src/biomapper2/data/ncbi_taxonomy"))
    parser.add_argument("--subset-taxids", help="comma-separated taxids: write only these plus their ancestors")
    parser.add_argument("--verify-with-taxonkit", action="store_true")
    args = parser.parse_args(argv)

    tmp_dir: tempfile.TemporaryDirectory | None = None
    taxdump = args.taxdump
    if args.download:
        tmp_dir = tempfile.TemporaryDirectory()
        taxdump = Path(tmp_dir.name) / "taxdump.tar.gz"
        print(f"downloading {TAXDUMP_URL} ...", file=sys.stderr)
        urllib.request.urlretrieve(TAXDUMP_URL, taxdump)  # noqa: S310 - pinned https URL
    assert taxdump is not None
    try:
        subset = {int(x) for x in args.subset_taxids.split(",")} if args.subset_taxids else None
        tables = build(taxdump, subset)
        sha = _sha256(taxdump)
        built = datetime.now(timezone.utc).date().isoformat()
        lines = [
            f"ncbi-taxdump/{tables['date']}/sha256:{sha[:12]}/built:{built}",
            f"taxdump_date: {tables['date']}",
            f"taxdump_sha256: {sha}",
            f"taxdump_md5: {_md5(taxdump)}",
            f"subset: {'yes' if subset else 'no'}",
            f"nodes: {len(tables['nodes'])}",
            f"names: {len(tables['names'])}",
            f"merged: {len(tables['merged'])}",
            f"homonyms: {len(tables['homonyms'])}",
        ]
        if args.verify_with_taxonkit:
            lines += verify_with_taxonkit(taxdump, tables)
        paths = write(tables, args.out_dir, lines)
        total = sum(p.stat().st_size for p in paths.values())
        for key, path in paths.items():
            print(f"{key:9s} {path} ({path.stat().st_size:,} bytes)")
        print(f"total     {total:,} bytes")
        print("\n".join(lines))
    finally:
        if tmp_dir is not None:
            tmp_dir.cleanup()
    shutil.rmtree(args.out_dir / "__pycache__", ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
