"""Derive every measured figure behind the category validator, from a pinned suite.

Motivation
----------
The category-validator change was halted three times in review for one recurring defect: prose
justified a decision with a live measurement that had drifted from -- or was never sourced by --
any artifact. This module is the single derivation those numbers come from. It reads a pinned
benchmark suite, asks Kestrel ``/get-nodes`` for the Biolink type of every committed node, and
re-derives everything from scratch into a committed artifact.

The companion rule is enforced by ``tests/test_no_measured_figures_in_prose.py``: comments and
docstrings NAME the artifact field carrying a number, and never restate its value. Add a
measurement here and reference the field; do not paste the result into prose.

What it measures
----------------
1. **Off-category rate.** A row is OFF-CATEGORY iff it has a non-null ``chosen_kg_id`` AND that
   node's ``categories`` has an empty intersection with ``descendants(biolink:ChemicalEntity)``.
   Empty/missing categories and the *pure* top-of-hierarchy sentinels
   (``biolink:NamedThing`` / ``biolink:Entity``) are treated as ON-category, mirroring the
   failure-open shape of the shipped validator
   (``core/annotators/kestrel_hybrid.py:_is_on_category``). The failure-open population is
   counted and reported rather than silently folded in.

2. **The refusal cost (the substantive measurement).** Off-category commits typed
   Protein / Gene / Polypeptide / GeneOrGeneProduct are the population of concern: peptide
   metabolites (glutathione, carnosine, anserine, ophthalmate) can be the RIGHT compound
   carrying a WRONG Biolink type, and the validator refuses them. Four hand-picked names do not
   answer "how often". So every such row is adjudicated against gold structure:
   gold InChIKey first block vs the SET of first blocks on the node's ``equivalent_ids``
   (set intersection, mirroring the shipped D2 semantics -- deliberately *not* ``keys[0]``),
   falling back to gold-database-identifier membership for datasets that ship no InChIKey gold.
   Each row lands in CORRECT_BUT_REFUSED / WRONG_AND_REFUSED / UNRESOLVABLE.

   Three things keep that number honest:
   - the same adjudication is also run over **all** off-category commits, not just Protein/Gene,
     so the validator's total cost is measured rather than extrapolated from one slice;
   - UNRESOLVABLE is split, so rows whose committed node carries no chemical identifier in any
     namespace are reported as provably-costless refusals rather than as unknowns; and
   - a **positive control** runs the unchanged adjudicator over the ON-category commits. A
     CORRECT_BUT_REFUSED count of zero only means something if the instrument can return a
     non-zero one, and the control demonstrates that it can.

Arms are never mixed: the metabolite arm (metlinkr, necs, refmet, srm1950, lmsd) is the headline
number; hgnc is a separately-reported gene-arm control, where a high off-category rate is the
expected, correct behavior (which is exactly why the gene path ships unfiltered).

Determinism / provenance
------------------------
The suite directory is read-only input. Suite provenance (kg_snapshot, git_sha, biolink_version)
is read *from the suite manifests*, never hardcoded, so an artifact generated from a different
suite self-describes correctly. The only network access is Kestrel ``/get-nodes``, cached to a
local JSON so reruns are free and offline-repeatable.

Usage::

    python studies/analysis/off_category_audit.py
    python studies/analysis/off_category_audit.py --suite-dir ~/benchmark-runs/suite_XXXX

Results are written by default (never behind a flag); ``--out`` is an override.
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
import socket
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests
import urllib3.util.connection

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT / "src") not in sys.path:  # allow running the file directly from a checkout
    sys.path.insert(0, str(REPO_ROOT / "src"))

from biomapper2.biolink_client import BiolinkClient  # noqa: E402

DEFAULT_SUITE_DIR = Path("~/benchmark-runs/suite_20260805T033340Z").expanduser()
DEFAULT_RESULTS_DIR = REPO_ROOT / "studies" / "analysis" / "results"
# Cache filename encodes the fetch shape. `truncate_long_fields` was briefly True, which caps
# equivalent_ids below what busy nodes actually carry; both node_has_chemical_identifier() and
# inchikey_blocks() read that field, so a truncated cache biases every verdict toward "no chemical
# identifier" -- i.e. toward flattering the change. Renaming the file on a shape change makes a stale
# cache impossible to silently reuse, and `audit()` asserts post-fetch (via `_is_truncated`, which
# compares against the node's own reported count rather than a hardcoded cap) that no adjudicated row
# came back truncated.
DEFAULT_CACHE_PATH = REPO_ROOT / "cache" / "off_category_audit_nodes_untruncated.json"

KESTREL_GET_NODES_URL = "https://kestrel.krakenkg.com/api/get-nodes"
GET_NODES_BATCH = 200
GET_NODES_TIMEOUT_S = 180

# Arms. Never summed together: the gene arm is a control, not part of the headline rate.
METABOLITE_DATASETS = ("metlinkr", "necs", "refmet", "srm1950", "lmsd")
CONTROL_DATASETS = ("hgnc",)

ACCEPTANCE_ROOT = "biolink:ChemicalEntity"
# Guard against a silent Biolink-version drift changing the acceptance set out from under the
# recorded numbers. Asserted, not assumed.
EXPECTED_ACCEPTANCE_SET = frozenset(
    {
        "biolink:ChemicalEntity",
        "biolink:ChemicalMixture",
        "biolink:ComplexMolecularMixture",
        "biolink:Drug",
        "biolink:EnvironmentalFoodContaminant",
        "biolink:Food",
        "biolink:FoodAdditive",
        "biolink:MolecularEntity",
        "biolink:MolecularMixture",
        "biolink:NucleicAcidEntity",
        "biolink:ProcessedMaterial",
        "biolink:SmallMolecule",
    }
)

# Mirrors kestrel_hybrid._TOP_OF_HIERARCHY_SENTINELS. A *pure* sentinel is a typing gap, not an
# off-category assertion, so it fails open.
TOP_OF_HIERARCHY_SENTINELS = frozenset({"biolink:NamedThing", "biolink:Entity"})

# The population whose refusal cost we actually measure (Deliverable 2).
PROTEIN_GENE_CATEGORIES = frozenset(
    {
        "biolink:Protein",
        "biolink:Gene",
        "biolink:Polypeptide",
        "biolink:GeneOrGeneProduct",
    }
)

# The input-name column differs per dataset; first match wins.
NAME_COLUMN_CANDIDATES = (
    "chemical_name",
    "metabolite_name",
    "refmet_name",
    "lipid_name",
    "symbol",
)

# Secondary gold axis. metlinkr carries no InChIKey gold at all, so an InChIKey-only adjudication
# would return UNRESOLVABLE for nearly the whole population and answer nothing. Where a dataset supplies
# a gold database identifier instead, membership of that CURIE in the committed node's
# equivalent_ids is the same question asked with a coarser instrument.
GOLD_ID_COLUMNS: dict[str, str] = {
    "gold_chebi": "CHEBI",
    "gold_hmdb": "HMDB",
    "gold_pubchem": "PUBCHEM.COMPOUND",
    "gold_kegg": "KEGG.COMPOUND",
    "gold_lipidmaps": "LIPIDMAPS",
    "curator_hmdb": "HMDB",
    "curator_pubchem": "PUBCHEM.COMPOUND",
}

# Prefixes that only ever appear on a chemical entity. A committed node bearing none of these AND
# no InChIKey is not a compound in any namespace, so the "right compound carrying a wrong Biolink
# type" hypothesis is structurally impossible for it -- a strictly stronger statement than
# "undecidable", and the one that actually settles whether the refusal cost anything.
CHEMICAL_IDENTIFIER_PREFIXES = frozenset(
    {
        "INCHIKEY",
        "CHEBI",
        "HMDB",
        "PUBCHEM.COMPOUND",
        "KEGG.COMPOUND",
        "KEGG.GLYCAN",
        "KEGG.DRUG",
        "UNII",
        "DRUGBANK",
        "CHEMBL.COMPOUND",
        "LIPIDMAPS",
        "RM",
        "CAS",
    }
)

MAX_EXAMPLES = 25

# Canonical metabolite namespaces -- mirrors CATEGORY_PREFERRED_NAMESPACES["biolink:SmallMolecule"]
# in config.py. Used ONLY to price the namespace-whitelist mis-implementation, never as a guard.
CANONICAL_NAMESPACES = frozenset({"CHEBI", "HMDB", "RM"})

# Annotator slug whose multi-node vote D4 makes deterministic. Mirrors core/resolver.REFMET_ANNOTATOR.
REFMET_ANNOTATOR = "metabolomics-workbench"

# Candidate-row scan (the failure-open measurement). Deterministic sample size and the production
# search limit, so the emitted counts are reproducible rather than an approximate recollection.
HYBRID_SCAN_NAMES = 120
HYBRID_SCAN_LIMIT = 20
KESTREL_HYBRID_SEARCH_URL = "https://kestrel.krakenkg.com/api/hybrid-search"
HYBRID_SEARCH_BATCH = 40
HYBRID_SCAN_CATEGORY = "biolink:SmallMolecule"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("off_category_audit")


# --------------------------------------------------------------------------------------
# Network (IPv4-forced; this host's IPv6 route to some public hosts is a black hole)
# --------------------------------------------------------------------------------------
def _force_ipv4() -> None:
    urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET


def fetch_nodes(curies: list[str], cache_path: Path, *, offline: bool = False) -> dict[str, dict]:
    """Return ``{curie: node}`` for ``curies``, hitting ``/get-nodes`` only for cache misses."""
    cache: dict[str, Any] = {}
    if cache_path.exists():
        cache = json.loads(cache_path.read_text())
        log.info("loaded %d cached nodes from %s", len(cache), cache_path)

    missing = sorted(c for c in curies if c not in cache)
    if missing and offline:
        raise RuntimeError(f"--offline set but {len(missing)} curies are not in {cache_path}")
    if missing:
        _force_ipv4()
        session = requests.Session()
        for start in range(0, len(missing), GET_NODES_BATCH):
            batch = missing[start : start + GET_NODES_BATCH]
            resp = session.post(
                KESTREL_GET_NODES_URL,
                # Must match production Linker.get_node_records (core/linker.py), which sends False.
                # Truncation caps equivalent_ids well below what busy nodes actually carry, and this reads
                # that field to decide both structural agreement and "carries no chemical identifier".
                json={"curies": batch, "slim": False, "truncate_long_fields": False},
                timeout=GET_NODES_TIMEOUT_S,
            )
            resp.raise_for_status()
            payload = resp.json()
            for curie in batch:
                # Record misses explicitly so they are cached rather than re-requested forever.
                cache[curie] = payload.get(curie) or {}
            log.info("fetched %d/%d", min(start + GET_NODES_BATCH, len(missing)), len(missing))
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(cache, sort_keys=True))
        log.info("cache now holds %d nodes", len(cache))

    return {c: cache.get(c) or {} for c in curies}


def fetch_hybrid_candidates(
    names: list[str], cache_path: Path, *, offline: bool = False, limit: int = HYBRID_SCAN_LIMIT
) -> list[dict]:
    """Return the flattened candidate rows /hybrid-search yields for ``names``.

    Cached beside the node cache under a key that encodes the limit and category, so changing
    either cannot silently reuse rows fetched under the old shape.
    """
    scan_cache_path = cache_path.with_name(cache_path.stem + f"_hybrid_l{limit}.json")
    cache: dict[str, Any] = {}
    if scan_cache_path.exists():
        cache = json.loads(scan_cache_path.read_text())

    missing = sorted(n for n in names if n not in cache)
    if missing and offline:
        raise RuntimeError(f"--offline set but {len(missing)} names are not in {scan_cache_path}")
    if missing:
        _force_ipv4()
        session = requests.Session()
        for start in range(0, len(missing), HYBRID_SEARCH_BATCH):
            batch = missing[start : start + HYBRID_SEARCH_BATCH]
            resp = session.post(
                KESTREL_HYBRID_SEARCH_URL,
                json={
                    "search_text": batch,
                    "limit": limit,
                    "category_filter": HYBRID_SCAN_CATEGORY,
                    "prefix_filter": None,
                },
                timeout=GET_NODES_TIMEOUT_S,
            )
            resp.raise_for_status()
            payload = resp.json()
            for name in batch:
                cache[name] = payload.get(name) or []
            log.info("hybrid-search %d/%d", min(start + HYBRID_SEARCH_BATCH, len(missing)), len(missing))
        scan_cache_path.parent.mkdir(parents=True, exist_ok=True)
        scan_cache_path.write_text(json.dumps(cache, sort_keys=True))

    return [row for name in names for row in (cache.get(name) or [])]


# --------------------------------------------------------------------------------------
# Suite reading
# --------------------------------------------------------------------------------------
def read_suite_pins(suite_dir: Path) -> dict[str, Any]:
    """Read provenance from the suite + per-dataset manifests. Nothing here is hardcoded."""
    suite_manifest = json.loads((suite_dir / "suite_manifest.json").read_text())
    pins = suite_manifest.get("pins", {})

    # Cross-check every per-dataset manifest agrees with the suite-level pins.
    per_dataset: dict[str, set[str]] = defaultdict(set)
    manifests = sorted(suite_dir.glob("*/*_manifest.json")) + sorted(suite_dir.glob("*/*/*_manifest.json"))
    for path in manifests:
        man = json.loads(path.read_text())
        for key, target in (
            ("kg_snapshot", "kg_snapshot"),
            ("biolink_version", "biolink_version"),
            ("biomapper2_commit", "git_sha"),
        ):
            if key in man:
                per_dataset[target].add(str(man[key]))

    return {
        "suite_dir": str(suite_dir),
        "suite_created": suite_manifest.get("created"),
        "kg_snapshot": pins.get("kg_snapshot"),
        "git_sha": pins.get("git_sha"),
        "biolink_version": pins.get("biolink_version"),
        "backend": pins.get("backend"),
        "chebi_node_count": pins.get("chebi_node_count"),
        "kg_stable_during_run": suite_manifest.get("kg_stable_during_run"),
        "n_manifests_checked": len(manifests),
        "manifest_agreement": {k: sorted(v) for k, v in sorted(per_dataset.items())},
    }


def load_dataset_frames(suite_dir: Path, dataset: str) -> list[tuple[str, pd.DataFrame]]:
    """Load every ``*_d_mapped.tsv`` for a dataset.

    A dataset with N target vocabularies contributes N files. They are all counted: a commit is
    a commit, and the config comment's population is per (row, target vocab). For metlinkr the
    five target files carry the same resolutions, so its commits are effectively 5x-weighted --
    recorded explicitly in the artifact rather than quietly corrected, so the number stays
    comparable to the one in config.py.
    """
    out = []
    for path in sorted((suite_dir / dataset).glob("*_d_mapped.tsv")):
        df = pd.read_csv(path, sep="\t", dtype=str, low_memory=False)
        out.append((path.name, df))
    if not out:
        raise FileNotFoundError(f"no *_d_mapped.tsv under {suite_dir / dataset}")
    return out


def pick_name_column(df: pd.DataFrame) -> str | None:
    for col in NAME_COLUMN_CANDIDATES:
        if col in df.columns:
            return col
    return None


# --------------------------------------------------------------------------------------
# Category / InChIKey helpers
# --------------------------------------------------------------------------------------
def node_categories(node: dict) -> list[str]:
    return list(node.get("categories") or [])


def is_off_category(node: dict, accepted: frozenset[str]) -> bool:
    """Exact complement of the shipped ``_is_on_category``, for a node that was committed."""
    categories = set(node_categories(node))
    if not categories or categories <= TOP_OF_HIERARCHY_SENTINELS:
        return False  # failure-open: an absent type assertion is not a wrong type assertion
    return not (categories & accepted)


def is_failure_open(node: dict) -> bool:
    categories = set(node_categories(node))
    return not categories or categories <= TOP_OF_HIERARCHY_SENTINELS


def inchikey_blocks(node: dict) -> set[str]:
    """First blocks (14-char connectivity layer) of every InChIKey on the node.

    ``equivalent_ids`` is a flat CURIE list on live Kestrel; older/other shapes use
    ``{PREFIX: [ids]}``. Both are handled so the script does not silently return an empty set
    (which would misclassify rows as UNRESOLVABLE) if the response shape changes.
    """
    equivalents = node.get("equivalent_ids") or []
    raw: list[str] = []
    if isinstance(equivalents, dict):
        for prefix, ids in equivalents.items():
            if str(prefix).upper() == "INCHIKEY":
                raw.extend(str(i) for i in (ids or []))
    else:
        for item in equivalents:
            text = str(item)
            if text.upper().startswith("INCHIKEY:"):
                raw.append(text.split(":", 1)[1])
    return {first_block(k) for k in raw if first_block(k)}


def _is_truncated(node: dict) -> bool:
    """True if the node's ``equivalent_ids`` was capped by ``truncate_long_fields``.

    Kestrel reports the true size in ``equivalent_ids_count``, so a shorter list than the count is
    a truncated record. Detecting it by count (rather than by a magic 50) survives a cap change.
    """
    equivalents = node.get("equivalent_ids")
    count = node.get("equivalent_ids_count")
    if not isinstance(equivalents, list) or not isinstance(count, int):
        return False
    return len(equivalents) < count


def node_equivalent_curies(node: dict) -> set[str]:
    """Normalized ``PREFIX:local`` set from ``equivalent_ids`` (list or ``{PREFIX: [ids]}``)."""
    equivalents = node.get("equivalent_ids") or []
    out: set[str] = set()
    if isinstance(equivalents, dict):
        for prefix, ids in equivalents.items():
            for local in ids or []:
                out.add(f"{str(prefix).upper()}:{normalize_local_id(str(prefix), str(local))}")
    else:
        for item in equivalents:
            text = str(item)
            if ":" not in text:
                continue
            prefix, local = text.split(":", 1)
            out.add(f"{prefix.upper()}:{normalize_local_id(prefix, local)}")
    return out


def normalize_local_id(prefix: str, local: str) -> str:
    """Strip the formatting differences that make a true match look like a miss."""
    text = str(local).strip()
    if text.upper().startswith(prefix.upper() + ":"):
        text = text.split(":", 1)[1]
    if text.endswith(".0"):  # pandas read a numeric gold column as float
        text = text[:-2]
    return text


def node_has_chemical_identifier(node: dict) -> bool:
    return any(curie.split(":", 1)[0] in CHEMICAL_IDENTIFIER_PREFIXES for curie in node_equivalent_curies(node))


def gold_curies(row: pd.Series, columns: set[str]) -> set[str]:
    """Gold database identifiers present on this row, as normalized CURIEs."""
    out: set[str] = set()
    for column, prefix in GOLD_ID_COLUMNS.items():
        if column not in columns:
            continue
        raw = row.get(column)
        if not isinstance(raw, str) or not raw.strip() or raw.strip().lower() == "nan":
            continue
        for piece in str(raw).replace(";", "|").replace(",", "|").split("|"):
            piece = piece.strip()
            if piece:
                out.add(f"{prefix}:{normalize_local_id(prefix, piece)}")
    return out


def first_block(inchikey: str | None) -> str | None:
    if inchikey is None:
        return None
    text = str(inchikey).strip()
    if not text or text.lower() == "nan":
        return None
    return text.split("-", 1)[0] or None


# --------------------------------------------------------------------------------------
# Core audit
# --------------------------------------------------------------------------------------
def namespace_composition(on_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """What a NAMESPACE whitelist would cost, at ONE explicitly stated scope.

    ``_is_on_category`` is a category check. The tempting mis-implementation is a namespace
    whitelist ("the committed node must be CHEBI/HMDB/RM"), which looks nearly identical in a diff.
    This measures the difference: on-category commits (i.e. ones the shipped guard KEEPS) whose
    namespace falls outside the canonical set, which a whitelist would additionally destroy.

    Scope is fixed and stated: **metabolite arm, on-category commits only**. An earlier comment
    itemized these counts while mixing the metabolite-arm scope with a 10-dataset scope, which is
    why its total reconciled against neither. Everything here derives from one population.
    """
    outside = [r for r in on_rows if r["namespace"].upper() not in CANONICAL_NAMESPACES]
    by_ns = Counter(r["namespace"] for r in outside)
    # LM and UMLS are called out separately because they dominate the tail and an earlier draft
    # excluded them without saying so; both variants are emitted so no reader has to guess.
    non_lm_umls = [r for r in outside if r["namespace"].upper() not in {"LM", "UMLS"}]
    return {
        "scope": "metabolite arm, ON-category commits only (the rows the shipped guard keeps)",
        "canonical_namespaces": sorted(CANONICAL_NAMESPACES),
        "n_on_category": len(on_rows),
        "whitelist_cost_all_namespaces": len(outside),
        "whitelist_cost_excluding_LM_and_UMLS": len(non_lm_umls),
        "by_namespace": dict(by_ns.most_common()),
        "headline": (
            f"a namespace whitelist would additionally destroy {len(outside)} on-category "
            f"metabolite-arm commits that the category check keeps"
        ),
    }


def candidate_category_scan(
    suite_dir: Path, cache_path: Path, *, offline: bool = False, limit: int = HYBRID_SCAN_LIMIT
) -> dict[str, Any]:
    """Measure the failure-open population over live hybrid-search CANDIDATE rows.

    Distinct from the rest of this module, which scans *committed* nodes. The failure-open clause in
    ``_is_on_category`` is justified by how often a candidate row arrives with no usable type, so it
    has to be measured on candidates. Sample is deterministic: the lexicographically-first
    ``HYBRID_SCAN_NAMES`` input names of the metabolite arm, queried at the production limit.
    """
    names: set[str] = set()
    for dataset in METABOLITE_DATASETS:
        for _, df in load_dataset_frames(suite_dir, dataset):
            col = pick_name_column(df)
            if col:
                names |= {str(x) for x in df[col].dropna().unique()}
    sample = sorted(names)[:HYBRID_SCAN_NAMES]

    rows = fetch_hybrid_candidates(sample, cache_path, offline=offline, limit=limit)
    empty = [r for r in rows if not node_categories(r)]
    pure_sentinel = [r for r in rows if node_categories(r) and set(node_categories(r)) <= TOP_OF_HIERARCHY_SENTINELS]
    return {
        "scope": (
            f"live /hybrid-search candidate rows for the {len(sample)} lexicographically-first "
            f"metabolite-arm input names, limit={limit}"
        ),
        "n_names_queried": len(sample),
        "n_candidate_rows": len(rows),
        "n_empty_or_missing_categories": len(empty),
        "n_pure_top_of_hierarchy_sentinel": len(pure_sentinel),
        "sentinel_examples": [
            {"id": r.get("id"), "name": r.get("name"), "categories": node_categories(r), "score": r.get("score")}
            for r in pure_sentinel[:MAX_EXAMPLES]
        ],
        "interpretation": (
            "the empty/missing clause is dead code if n_empty_or_missing_categories is 0; the "
            "pure-sentinel clause is what actually fires, and it is what keeps legitimately-typed-"
            "but-underspecified metabolite nodes from being refused"
        ),
    }


def refmet_multi_node_rate(suite_dir: Path) -> dict[str, Any]:
    """How often the RefMet annotator contributes >1 KG node (backs D4's determinism claim).

    ``Resolver._choose_best_kg_id`` sorts the RefMet nodes before picking, and tests the majority for
    *membership* rather than equality with the first. Both only matter when RefMet votes for more than
    one node. That rate is asserted in ``core/resolver.py`` and in
    ``tests/test_resolver_source_weighting.py``, so it is derived here rather than by a one-off shell
    command -- the same standard the off-category numbers are held to. No network access.
    """
    rows_with_vote = 0
    rows_multi = 0
    examples: list[dict[str, Any]] = []
    for dataset in METABOLITE_DATASETS:
        for filename, df in load_dataset_frames(suite_dir, dataset):
            if "kg_ids_assigned" not in df.columns:
                continue
            for _, row in df.iterrows():
                raw = row.get("kg_ids_assigned")
                if not isinstance(raw, str) or not raw.strip():
                    continue
                try:
                    assigned = ast.literal_eval(raw)
                except (ValueError, SyntaxError):
                    continue
                refmet = (assigned or {}).get(REFMET_ANNOTATOR) or {}
                if not refmet:
                    continue
                rows_with_vote += 1
                if len(refmet) > 1:
                    rows_multi += 1
                    if len(examples) < MAX_EXAMPLES:
                        examples.append({"dataset": dataset, "file": filename, "refmet_nodes": sorted(refmet)})
    return {
        "scope": f"metabolite arm, rows carrying a '{REFMET_ANNOTATOR}' vote",
        "n_rows_with_refmet_vote": rows_with_vote,
        "n_rows_refmet_contributed_multiple_nodes": rows_multi,
        "examples": examples,
        "interpretation": (
            "zero here means the deterministic sort and the membership agreement test are provable "
            "no-ops on this suite -- correctness hardening for a case that does not occur yet, which "
            "is why they cannot contaminate the A/B"
        ),
    }


def audit(suite_dir: Path, cache_path: Path, *, offline: bool = False) -> dict[str, Any]:
    client = BiolinkClient()
    accepted = frozenset(client.get_descendants(ACCEPTANCE_ROOT))
    if accepted != EXPECTED_ACCEPTANCE_SET:
        raise AssertionError(
            f"descendants({ACCEPTANCE_ROOT}) = {sorted(accepted)} "
            f"but expected the 12-member set {sorted(EXPECTED_ACCEPTANCE_SET)}; "
            "the Biolink schema in use does not match the pinned suite."
        )

    all_datasets = list(METABOLITE_DATASETS) + list(CONTROL_DATASETS)
    frames: dict[str, list[tuple[str, pd.DataFrame]]] = {ds: load_dataset_frames(suite_dir, ds) for ds in all_datasets}

    committed: set[str] = set()
    for dataset_frames in frames.values():
        for _, df in dataset_frames:
            committed |= set(df["chosen_kg_id"].dropna().unique())
    log.info("%d unique committed nodes across %d datasets", len(committed), len(all_datasets))
    nodes = fetch_nodes(sorted(committed), cache_path, offline=offline)

    per_dataset: dict[str, dict[str, Any]] = {}
    per_file: dict[str, dict[str, Any]] = {}
    composition_by_category: Counter[str] = Counter()
    composition_by_category_set: Counter[str] = Counter()
    off_rows: list[dict[str, Any]] = []
    on_rows: list[dict[str, Any]] = []
    nodes_missing_from_kg: Counter[str] = Counter()

    for dataset in all_datasets:
        is_metabolite = dataset in METABOLITE_DATASETS
        d_rows = d_off = d_open = 0
        for filename, df in frames[dataset]:
            name_col = pick_name_column(df)
            gold_col = "gold_inchikey" if "gold_inchikey" in df.columns else None
            f_rows = f_off = f_open = 0
            for _, row in df.iterrows():
                curie = row.get("chosen_kg_id")
                if not isinstance(curie, str) or not curie:
                    continue
                node = nodes.get(curie) or {}
                if not node:
                    nodes_missing_from_kg[curie] += 1
                f_rows += 1
                if is_failure_open(node):
                    f_open += 1
                if not is_off_category(node, accepted):
                    if is_metabolite:
                        on_rows.append(
                            build_adjudication_row(dataset, filename, row, name_col, gold_col, curie, node, df)
                        )
                    continue
                f_off += 1

                categories = node_categories(node)
                if is_metabolite:
                    composition_by_category.update(categories)
                    composition_by_category_set["|".join(sorted(categories))] += 1
                    off_rows.append(build_adjudication_row(dataset, filename, row, name_col, gold_col, curie, node, df))

            per_file[f"{dataset}/{filename}"] = {
                "n_rows_with_commit": f_rows,
                "n_off_category": f_off,
                "pct_off_category": round(100.0 * f_off / f_rows, 2) if f_rows else 0.0,
                "n_failure_open": f_open,
            }
            d_rows += f_rows
            d_off += f_off
            d_open += f_open

        per_dataset[dataset] = {
            "arm": "metabolite" if is_metabolite else "gene_control",
            "n_files": len(frames[dataset]),
            "n_rows_with_commit": d_rows,
            "n_off_category": d_off,
            "pct_off_category": round(100.0 * d_off / d_rows, 2) if d_rows else 0.0,
            "n_failure_open": d_open,
        }

    metab_rows = sum(per_dataset[d]["n_rows_with_commit"] for d in METABOLITE_DATASETS)
    metab_off = sum(per_dataset[d]["n_off_category"] for d in METABOLITE_DATASETS)
    metab_open = sum(per_dataset[d]["n_failure_open"] for d in METABOLITE_DATASETS)

    # Truncation guard. equivalent_ids is the basis for both structural agreement and the
    # "carries no chemical identifier" verdict, so a truncated record would bias every refusal
    # toward "provably costless". fetch_nodes now sends truncate_long_fields=False; assert the
    # records actually reflect that rather than trusting the flag round-tripped.
    truncated = sorted(
        {r["chosen_kg_id"] for r in (off_rows + on_rows) if _is_truncated(nodes.get(r["chosen_kg_id"]) or {})}
    )
    if truncated:
        raise AssertionError(
            f"{len(truncated)} adjudicated nodes have truncated equivalent_ids "
            f"(e.g. {truncated[:3]}); refetch with truncate_long_fields=False -- "
            "a truncated record silently flatters the refusal-cost verdict"
        )

    # Deduplicated cross-dataset rate: take a single representative file per dataset (the first by
    # name, deterministically) so replicated target-vocab files cannot multiply a dataset's weight.
    dedup_rows = dedup_off = 0
    dedup_files: dict[str, str] = {}
    for key, stats in sorted(per_file.items()):
        dataset = key.split("/", 1)[0]
        if dataset not in METABOLITE_DATASETS or dataset in dedup_files:
            continue
        dedup_files[dataset] = key
        dedup_rows += stats["n_rows_with_commit"]
        dedup_off += stats["n_off_category"]
    dedup_total = {
        "definition": (
            "one representative file per metabolite dataset (first by filename), so a dataset that "
            "ships several identical target-vocab files is counted once rather than once per file"
        ),
        "representative_files": dedup_files,
        "n_rows_with_commit": dedup_rows,
        "n_off_category": dedup_off,
        "pct_off_category": round(100.0 * dedup_off / dedup_rows, 2) if dedup_rows else 0.0,
    }

    pg_rows = [r for r in off_rows if set(r["categories"]) & PROTEIN_GENE_CATEGORIES]
    refusal_cost = adjudicate(pg_rows, "protein/gene-typed off-category commits")
    all_refusal_cost = adjudicate(off_rows, "all off-category commits, metabolite arm")
    # Positive control. A CORRECT_BUT_REFUSED count of zero is only informative if the same
    # adjudicator can produce that verdict at all -- so run it unchanged over the ON-category
    # commits, where correct answers are known to be plentiful. A healthy control turns "we found
    # none" into a measurement instead of a silent instrument failure.
    positive_control = adjudicate(on_rows, "ON-category commits, metabolite arm (positive control)")
    positive_control.pop("examples_correct_but_refused", None)
    positive_control["verdict_label_note"] = (
        "these rows were NOT refused; read CORRECT_BUT_REFUSED here as simply 'gold agrees with the "
        "committed node'. The point of this block is only that the adjudicator can return that verdict."
    )

    return {
        "analysis": "off_category_audit",
        "generated_utc": datetime.now(UTC).isoformat(),
        # Every file whose measured numbers this script backs. If a number appears in a comment
        # anywhere in the resolver-correctness change and is not derivable from this artifact, that
        # is the bug -- the first review round fixed only config.py and left kestrel_hybrid.py's
        # figures comment-only, which is the same defect one file over.
        "regenerates": [
            "src/biomapper2/config.py (CATEGORY_ACCEPTED_ROOTS docstring: off-category rate, "
            "composition, hgnc control)",
            "src/biomapper2/core/annotators/base.py (is_on_category docstring: "
            "namespace_whitelist_cost, failure_open_candidate_scan)",
            "tests/test_kestrel_hybrid_category.py (module and test docstrings)",
            "tests/test_annotation_engine_category.py (gene-arm control docstring)",
            "src/biomapper2/core/resolver.py + tests/test_resolver_source_weighting.py "
            "(RefMet multi-node rate behind the D4 determinism fix)",
        ],
        "pinned_input": read_suite_pins(suite_dir),
        "definition": {
            "off_category": (
                f"non-null chosen_kg_id AND node.categories has empty intersection with descendants({ACCEPTANCE_ROOT})"
            ),
            "failure_open": (
                "empty/missing categories, or a pure top-of-hierarchy sentinel "
                f"({sorted(TOP_OF_HIERARCHY_SENTINELS)}), counted as ON-category"
            ),
            "acceptance_root": ACCEPTANCE_ROOT,
            "acceptance_set": sorted(accepted),
            "acceptance_set_size": len(accepted),
            "biolink_toolkit_source": "biomapper2.biolink_client.BiolinkClient.get_descendants",
            "population_note": (
                "one row per (input row, target vocabulary); metlinkr contributes 5 target-vocab "
                "files carrying identical resolutions, so its commits are 5x-weighted"
            ),
        },
        # Prices the namespace-whitelist mis-implementation that _is_on_category warns against.
        "namespace_whitelist_cost": namespace_composition(on_rows),
        # Backs the failure-open clause's candidate-row counts.
        "failure_open_candidate_scan": candidate_category_scan(suite_dir, cache_path, offline=offline),
        # Backs D4's determinism claim in core/resolver.py and test_resolver_source_weighting.py.
        "refmet_multi_node_rate": refmet_multi_node_rate(suite_dir),
        # One file per dataset, so a dataset cannot enter the cross-dataset rate more than once.
        # metlinkr ships several target-vocab files carrying identical resolutions, which inflates
        # the file-weighted rate above; this is the figure to quote for "how often does the resolver
        # commit an off-category node", and the one that belongs in the preprint. It does NOT change
        # the per-dataset coverage decision, which is computed within a dataset and so is unaffected.
        "metabolite_total_deduplicated": dedup_total,
        "per_dataset": per_dataset,
        "per_file": per_file,
        "metabolite_total": {
            "datasets": list(METABOLITE_DATASETS),
            "n_rows_with_commit": metab_rows,
            "n_off_category": metab_off,
            "pct_off_category": round(100.0 * metab_off / metab_rows, 2) if metab_rows else 0.0,
            "n_failure_open": metab_open,
            # Two defensible readings of the same population, kept separate on purpose:
            # "refused" is what the shipped validator drops (failure-open rows survive);
            # "no_chemical_category" is the literal reading, which the config.py comment used.
            "n_off_category_refused_by_validator": metab_off,
            "n_no_chemical_category_incl_failure_open": metab_off + metab_open,
            "weighting_warning": (
                "file-weighted: a dataset shipping N target-vocab files with identical resolutions "
                "enters this total N times. See metabolite_total_deduplicated before quoting a "
                "cross-dataset rate."
            ),
            "pct_no_chemical_category_incl_failure_open": (
                round(100.0 * (metab_off + metab_open) / metab_rows, 2) if metab_rows else 0.0
            ),
        },
        "gene_control": {
            "datasets": list(CONTROL_DATASETS),
            **{
                k: sum(per_dataset[d][k] for d in CONTROL_DATASETS)
                for k in ("n_rows_with_commit", "n_off_category", "n_failure_open")
            },
        },
        "off_category_composition_by_category": dict(composition_by_category.most_common()),
        "off_category_composition_by_category_set": dict(composition_by_category_set.most_common()),
        "protein_gene_refusal_cost": refusal_cost,
        "all_off_category_refusal_cost": all_refusal_cost,
        "adjudicator_positive_control": positive_control,
        "nodes_absent_from_get_nodes": {
            "n_distinct": len(nodes_missing_from_kg),
            "curies": sorted(nodes_missing_from_kg)[:50],
        },
    }


def build_adjudication_row(
    dataset: str,
    filename: str,
    row: pd.Series,
    name_col: str | None,
    gold_col: str | None,
    curie: str,
    node: dict,
    df: pd.DataFrame,
) -> dict[str, Any]:
    return {
        "dataset": dataset,
        "file": filename,
        "input_name": (row.get(name_col) if name_col else None),
        "chosen_kg_id": curie,
        "namespace": curie.split(":", 1)[0],
        "node_name": node.get("name"),
        "categories": node_categories(node),
        "gold_inchikey": (row.get(gold_col) if gold_col else None),
        "node_inchikey_blocks": sorted(inchikey_blocks(node)),
        "gold_curies": sorted(gold_curies(row, set(df.columns))),
        "node_equivalent_curies": sorted(node_equivalent_curies(node)),
        "node_has_chemical_identifier": node_has_chemical_identifier(node),
    }


def adjudicate(rows: list[dict[str, Any]], population: str) -> dict[str, Any]:
    """Deliverable 2: how many of these refusals were the RIGHT compound?

    Primary evidence is structure: gold's InChIKey first block tested for membership in the SET of
    the node's first blocks (set intersection, matching the shipped D2 semantics -- deliberately
    not ``keys[0]``). Where a dataset carries no InChIKey gold, a gold database identifier is
    tested for membership in the node's ``equivalent_ids`` instead; ``gold_source`` records which
    instrument decided each row so the two are never silently conflated.

    UNRESOLVABLE is then split, because "we cannot tell" and "there is nothing to tell" are
    different answers. A committed node carrying no chemical identifier in any namespace cannot be
    the right compound under a wrong type -- it is not a compound -- so its refusal is provably
    costless even with no gold on the row.
    """
    verdicts: Counter[str] = Counter()
    per_category: dict[str, Counter[str]] = defaultdict(Counter)
    per_dataset: dict[str, Counter[str]] = defaultdict(Counter)
    gold_source_counts: Counter[str] = Counter()
    unresolvable_reason: Counter[str] = Counter()
    examples: list[dict[str, Any]] = []

    for row in rows:
        gold_block = first_block(row.get("gold_inchikey"))
        node_blocks = set(row.get("node_inchikey_blocks") or [])
        gold_ids = set(row.get("gold_curies") or [])
        node_ids = set(row.get("node_equivalent_curies") or [])

        if gold_block is not None and node_blocks:
            gold_source = "inchikey_first_block"
            verdict = "CORRECT_BUT_REFUSED" if gold_block in node_blocks else "WRONG_AND_REFUSED"
        elif gold_ids and node_ids:
            gold_source = "gold_database_id"
            verdict = "CORRECT_BUT_REFUSED" if (gold_ids & node_ids) else "WRONG_AND_REFUSED"
        else:
            gold_source = "none"
            verdict = "UNRESOLVABLE"
            has_gold = gold_block is not None or bool(gold_ids)
            if not row.get("node_has_chemical_identifier"):
                # Strongest available statement: the refusal cannot have destroyed a correct
                # compound answer, because the committed node is not a compound at all.
                unresolvable_reason["node_carries_no_chemical_identifier"] += 1
            elif not has_gold:
                unresolvable_reason["row_has_no_gold_structure_or_id"] += 1
            else:
                unresolvable_reason["gold_present_but_node_not_comparable"] += 1

        verdicts[verdict] += 1
        gold_source_counts[gold_source] += 1
        per_dataset[row["dataset"]][verdict] += 1
        for category in row["categories"]:
            per_category[category][verdict] += 1

        if verdict == "CORRECT_BUT_REFUSED" and len(examples) < MAX_EXAMPLES:
            examples.append(
                {
                    "dataset": row["dataset"],
                    "input_name": row["input_name"],
                    "chosen_kg_id": row["chosen_kg_id"],
                    "node_name": row["node_name"],
                    "categories": row["categories"],
                    "gold_source": gold_source,
                    "gold_inchikey_first_block": gold_block,
                    "gold_curies": sorted(gold_ids),
                }
            )

    total = sum(verdicts.values())
    adjudicable = verdicts["CORRECT_BUT_REFUSED"] + verdicts["WRONG_AND_REFUSED"]
    # CORRECT_BUT_REFUSED is the ONE verdict that is never costless -- it is precisely the outcome
    # this whole audit exists to detect (a right compound refused for wearing a wrong Biolink type).
    # Adding `adjudicable` here instead of WRONG_AND_REFUSED absorbed it into the safety number, which
    # made the claim self-confirming: the instrument could not report the failure it was built to find.
    # Masked on the refusal populations only because CORRECT_BUT_REFUSED happens to be zero there.
    provably_costless = verdicts["WRONG_AND_REFUSED"] + unresolvable_reason["node_carries_no_chemical_identifier"]
    return {
        "population": population,
        "definition": (
            "adjudicated by gold InChIKey first block IN the SET of the committed node's InChIKey "
            "first blocks, falling back to gold database identifier IN the node's equivalent_ids"
        ),
        "n_population": total,
        "counts": dict(verdicts),
        "pct_of_population": {k: (round(100.0 * v / total, 2) if total else 0.0) for k, v in verdicts.items()},
        "pct_of_adjudicable": {
            k: (round(100.0 * verdicts[k] / adjudicable, 2) if adjudicable else 0.0)
            for k in ("CORRECT_BUT_REFUSED", "WRONG_AND_REFUSED")
        },
        "n_adjudicable": adjudicable,
        "gold_source_counts": dict(gold_source_counts),
        "unresolvable_reasons": dict(unresolvable_reason),
        "refusal_provably_costless": {
            "n": provably_costless,
            "pct_of_population": round(100.0 * provably_costless / total, 2) if total else 0.0,
            "note": (
                "WRONG_AND_REFUSED plus rows whose committed node carries no chemical identifier "
                "in any namespace (so it cannot be the right compound under a wrong type)"
            ),
        },
        "by_category": {k: dict(v) for k, v in sorted(per_category.items())},
        "by_dataset": {k: dict(v) for k, v in sorted(per_dataset.items())},
        "examples_correct_but_refused": examples,
    }


# --------------------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------------------
def render_markdown(result: dict[str, Any]) -> str:
    pins = result["pinned_input"]
    total = result["metabolite_total"]
    control = result["gene_control"]
    cost = result["protein_gene_refusal_cost"]

    lines: list[str] = []
    lines.append("## Off-category commit audit")
    lines.append("")
    lines.append(f"- Pinned input: `{pins['suite_dir']}`")
    lines.append(f"- KG snapshot: `{pins['kg_snapshot']}` (kg_stable_during_run={pins['kg_stable_during_run']})")
    lines.append(f"- biomapper2 git_sha: `{pins['git_sha']}` | Biolink `{pins['biolink_version']}`")
    lines.append(
        f"- Acceptance set: {result['definition']['acceptance_set_size']} descendants of "
        f"`{result['definition']['acceptance_root']}`"
    )
    lines.append(f"- Generated: {result['generated_utc']}")
    lines.append("")
    lines.append("### Per dataset")
    lines.append("")
    lines.append("| dataset | arm | files | commits | off-category | % | failure-open |")
    lines.append("|---|---|---:|---:|---:|---:|---:|")
    for dataset, stats in result["per_dataset"].items():
        lines.append(
            f"| {dataset} | {stats['arm']} | {stats['n_files']} | {stats['n_rows_with_commit']:,} | "
            f"{stats['n_off_category']:,} | {stats['pct_off_category']}% | {stats['n_failure_open']:,} |"
        )
    lines.append(
        f"| **METABOLITE TOTAL** | metabolite | | **{total['n_rows_with_commit']:,}** | "
        f"**{total['n_off_category']:,}** | **{total['pct_off_category']}%** | "
        f"{total['n_failure_open']:,} |"
    )
    lines.append("")
    lines.append(
        f"The gene arm ({', '.join(control['datasets'])}, {control['n_rows_with_commit']:,} commits, "
        f"{round(100.0 * control['n_off_category'] / control['n_rows_with_commit'], 2)}% off-category) "
        "is a control and is deliberately excluded from the metabolite total: a gene commit is "
        "*supposed* to be off-category relative to a chemical root, which is why the gene path "
        "ships with the validator disabled."
    )
    lines.append("")
    lines.append(
        f"Counting the {total['n_failure_open']} failure-open rows as off-category (the literal "
        f'"carried no chemical category" reading) gives '
        f"{total['n_no_chemical_category_incl_failure_open']:,} / "
        f"{total['n_rows_with_commit']:,} = "
        f"{total['pct_no_chemical_category_incl_failure_open']}%. The validator itself refuses "
        f"only the {total['n_off_category']:,}."
    )
    lines.append("")
    lines.append("### Off-category composition (metabolite arm, by exact category set)")
    lines.append("")
    lines.append("| categories | rows |")
    lines.append("|---|---:|")
    for category_set, count in list(result["off_category_composition_by_category_set"].items())[:15]:
        # "|" is the JSON key's separator but a cell delimiter in markdown -- swap it.
        lines.append(f"| {category_set.replace('|', ' + ')} | {count:,} |")
    lines.append("")
    lines.append("### Refusal cost: how many refusals were the RIGHT compound?")
    for block in (
        cost,
        result["all_off_category_refusal_cost"],
        result["adjudicator_positive_control"],
    ):
        lines.extend(render_refusal_cost(block))
    return "\n".join(lines)


def render_refusal_cost(cost: dict[str, Any]) -> list[str]:
    lines = ["", f"#### Population: {cost['population']} (n={cost['n_population']:,})", ""]
    lines.append("| verdict | rows | % of population | % of adjudicable |")
    lines.append("|---|---:|---:|---:|")
    for verdict in ("CORRECT_BUT_REFUSED", "WRONG_AND_REFUSED", "UNRESOLVABLE"):
        count = cost["counts"].get(verdict, 0)
        pct_adj = cost["pct_of_adjudicable"].get(verdict)
        pct_adj_text = f"{pct_adj}%" if pct_adj is not None else "-"
        lines.append(f"| {verdict} | {count:,} | {cost['pct_of_population'].get(verdict, 0.0)}% | {pct_adj_text} |")
    lines.append("")
    lines.append(f"Gold instrument used: {cost['gold_source_counts']}")
    lines.append("")
    if cost["unresolvable_reasons"]:
        lines.append(f"Unresolvable breakdown: {cost['unresolvable_reasons']}")
        lines.append("")
    if "verdict_label_note" in cost:
        # The control rows were never refused, so a "costless refusal" figure would be nonsense.
        lines.append(f"_{cost['verdict_label_note']}_")
    else:
        costless = cost["refusal_provably_costless"]
        lines.append(
            f"**Refusal provably costless for {costless['n']:,} / {cost['n_population']:,} "
            f"({costless['pct_of_population']}%)** -- {costless['note']}."
        )
    lines.append("")
    lines.append("| category | CORRECT_BUT_REFUSED | WRONG_AND_REFUSED | UNRESOLVABLE |")
    lines.append("|---|---:|---:|---:|")
    for category, counts in cost["by_category"].items():
        lines.append(
            f"| `{category}` | {counts.get('CORRECT_BUT_REFUSED', 0):,} | "
            f"{counts.get('WRONG_AND_REFUSED', 0):,} | {counts.get('UNRESOLVABLE', 0):,} |"
        )
    lines.append("")
    if cost.get("examples_correct_but_refused"):
        lines.append(f"Examples of CORRECT_BUT_REFUSED (up to {MAX_EXAMPLES}):")
        lines.append("")
        lines.append("| dataset | input name | committed node | node name | categories |")
        lines.append("|---|---|---|---|---|")
        for example in cost["examples_correct_but_refused"]:
            lines.append(
                f"| {example['dataset']} | {example['input_name']} | `{example['chosen_kg_id']}` | "
                f"{example['node_name']} | {', '.join(example['categories'])} |"
            )
        lines.append("")
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--suite-dir",
        type=Path,
        default=DEFAULT_SUITE_DIR,
        help="pinned benchmark suite directory (read-only input)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help=f"JSON artifact path (default: {DEFAULT_RESULTS_DIR}/off_category_audit_<suite>.json)",
    )
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE_PATH, help="/get-nodes response cache")
    parser.add_argument(
        "--offline",
        action="store_true",
        help="fail instead of calling /get-nodes if the cache is incomplete",
    )
    args = parser.parse_args(argv)

    suite_dir = args.suite_dir.expanduser().resolve()
    out_path = args.out or (DEFAULT_RESULTS_DIR / f"off_category_audit_{suite_dir.name}.json")
    out_path = out_path.expanduser()

    result = audit(suite_dir, args.cache.expanduser(), offline=args.offline)

    # Saving is the default, not a flag: the compute (a full /get-nodes sweep of a pinned suite)
    # is the expensive part and must never be silently discarded.
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, sort_keys=False) + "\n")
    md_path = out_path.with_suffix(".md")
    md_path.write_text(render_markdown(result) + "\n")

    total = result["metabolite_total"]
    cost = result["protein_gene_refusal_cost"]
    log.info(
        "metabolite arm: %d/%d off-category (%.1f%%)",
        total["n_off_category"],
        total["n_rows_with_commit"],
        total["pct_off_category"],
    )
    log.info(
        "protein/gene refusals: n=%d correct_but_refused=%d wrong=%d unresolvable=%d",
        cost["n_population"],
        cost["counts"].get("CORRECT_BUT_REFUSED", 0),
        cost["counts"].get("WRONG_AND_REFUSED", 0),
        cost["counts"].get("UNRESOLVABLE", 0),
    )
    log.info("saved %s", out_path)
    log.info("saved %s", md_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
