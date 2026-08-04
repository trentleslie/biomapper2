"""KEGG compound -> pathway membership: pinned acquisition + offline loader.

The full map is fetched once from the KEGG REST API and committed to
data/kegg_compound_pathway.tsv (SHA pinned in the run manifest). Only 'map####'
pathways are kept (organism-agnostic reference pathways); 'ko####' / organism
variants are dropped so the vocabulary stays fixed (Mubeen 2019).
"""

from __future__ import annotations

import hashlib
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
MEMBERSHIP_TSV = DATA_DIR / "kegg_compound_pathway.tsv"
KEGG_LINK_URL = "https://rest.kegg.jp/link/pathway/compound"


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def fetch_compound_pathway_links(*, timeout: float = 60.0) -> bytes:
    import requests

    resp = requests.get(KEGG_LINK_URL, timeout=timeout)
    resp.raise_for_status()
    return resp.content


def parse_links(raw: bytes) -> dict[str, tuple[str, ...]]:
    acc: dict[str, set[str]] = {}
    for line in raw.decode("utf-8").splitlines():
        if "\t" not in line:
            continue
        cpd, path = line.split("\t", 1)
        cpd = cpd.replace("cpd:", "").strip()
        path = path.replace("path:", "").strip()
        if not path.startswith("map"):
            continue
        acc.setdefault(cpd, set()).add(path)
    return {c: tuple(sorted(v)) for c, v in acc.items()}


def load_membership(path: Path | None = None) -> dict[str, tuple[str, ...]]:
    p = path or MEMBERSHIP_TSV
    return parse_links(p.read_bytes())
