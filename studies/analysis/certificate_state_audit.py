"""Derive every measured figure behind the resolution certificate, from a pinned suite.

Motivation
----------
The preprint's central claim is that a name-input metabolite resolution carries a *structural
certificate*, and that the resolver refuses when one cannot be issued. This module was written
before the certificate existed, to measure what one would be worth so the design was chosen on
evidence rather than on the appeal of the idea. It now reads the certificate the pipeline emits and
falls back to deriving it, recording which of the two it used in ``per_dataset[].certificate_source``
so a reader never has to guess.

Back then the only thing that escaped resolution was ``chosen_kg_id_review``, a flag string with
three values whose ``None`` covered several distinct situations at once — which is the overloading
the certificate removes.

It is deliberately a **zero-network, offline** derivation. Every figure comes from the committed
``*_d_mapped.tsv`` files of a pinned suite run. The chosen node's InChIKey is already present in
those files, inside ``kg_equivalent_ids`` under the ``INCHIKEY`` prefix, so the Tier-A
self-certificate is measurable today without running the pipeline again.

The companion rule is enforced by ``tests/test_no_measured_figures_in_prose.py``: comments and
docstrings NAME the artifact field carrying a number and never restate its value. Add a
measurement here and reference the field; do not paste the result into prose.

What it measures
----------------
1. **Certificate-state distribution (Tier A).** Each row with a committed ``chosen_kg_id`` is
   ``structure_present`` when that node's ``kg_equivalent_ids`` carries at least one ``INCHIKEY``
   entry, and ``structure_absent`` otherwise. Field: ``per_dataset[].tier_a``.

2. **Precision within each certificate state, under TWO independent oracles.** Reporting one
   oracle would have shipped a confounded headline, so both run:

   - ``structure_oracle`` -- gold InChIKey first block is a member of the SET of first blocks on
     the committed node (set intersection, mirroring the shipped D2 semantics, deliberately not
     ``keys[0]``).
   - ``identifier_oracle`` -- the gold HMDB / KEGG / PubChem identifier is a member of the
     committed node's ``kg_equivalent_ids`` under the corresponding prefix. Touches no InChIKey at
     all, so it is structurally independent of the certificate state being tested.

3. **The sparsity control, and it is the point of this script.** ``structure_absent`` rows cannot
   be scored correct by ``structure_oracle`` *by construction* -- a node with no InChIKey can never
   match a gold InChIKey -- so whatever precision is reported there is tautological and means
   nothing. The ``identifier_oracle`` was added to escape that, and it does not: the control asks how many
   ``structure_absent`` rows carry ANY of HMDB / KEGG / PubChem, i.e. how many rows the identifier
   oracle *could* have fired on. Field: ``per_dataset[].sparsity_control``, whose
   ``n_absent_oracle_could_fire`` is the number that decides whether any precision claim about the
   ``structure_absent`` bucket is admissible.

   The honest reading this control forces: ``structure_absent`` does not identify *wrong* answers,
   it identifies **unverifiable** ones -- nodes carrying no cross-reference into any structure
   vocabulary, which no available oracle can confirm or refute. That is the ``unavailable``
   certificate state, not the ``contradicted`` one, and conflating the two would have been a
   confidently-wrong headline.

4. **Discrimination of the existing review flag.** ``chosen_kg_id_review`` crossed with correctness
   under both oracles, and crossed with the Tier-A state to show how much of each flag is simply
   the ``structure_absent`` population under another name. Fields:
   ``per_dataset[].review_flag_x_correctness`` and ``per_dataset[].review_flag_x_tier_a``.

5. **The two panels behind the published figure.** Field: ``per_dataset[].figure5``.

   - ``panel_a_abstention`` -- ``unavailable`` reported as a declared abstention RATE, a coverage
     statistic. It carries no precision claim, by construction and by test.
   - ``panel_b_precision_coverage`` -- precision-coverage drawn ONLY within the verifiable
     population (rows an oracle can actually adjudicate), stratified by ``independent_source``.

   The constraint that fixes this shape: a precision delta plotted *across* the ``unavailable``
   boundary asserts that refusing those rows buys precision. That is the claim the sparsity control
   in (3) exists to rule out, rendered as a line, in the one artifact that travels without its
   caveat. Two panels rather than one because an abstention-rate panel shows the refusal happening
   without implying the refused answers were wrong, which a single blended curve tends to blur.

   ``curve_publishable`` is False whenever the input carries no certificate columns or Tier B's own
   resolution rate is below ``TIER_B_MIN_RESOLUTION_RATE`` — the endpoints are exact-name lookups
   while the annotator matches fuzzily, so a starved rate means the verdicts were computed on a
   biased easy subset of query names.

**No sweep is fired from here.** The single Tier-B sweep that supplies the second half of the figure
is an operator-run, supervised step; this module only reads its committed artifact, referenced by the
fixed name ``TIER_B_SWEEP_FILENAME``, and says plainly when there isn't one.

To produce that sweep, an operator re-runs the pinned suite with ``BIOMAPPER2_TIER_B_ENABLED=1``.
The mapped TSVs then carry ``certificate_*`` columns and this script reads them directly. Nothing in
the library, the test suite, or this module turns that flag on.

Arms are never mixed. The metabolite arm (necs, refmet, srm1950, lmsd, metlinkr) is the headline;
datasets shipping no structural gold are reported with a null oracle rather than dropped, so a
reader can see coverage of the measurement itself. hgnc is a gene-arm dataset and carries no
metabolite certificate -- it is skipped, not scored.

Determinism / provenance
------------------------
The suite directory is read-only input and the only input. Suite provenance (kg_snapshot, git_sha,
biolink_version) is read *from the suite manifest*, never hardcoded, so an artifact generated from
a different suite self-describes correctly. There is no network access and therefore no HTTP cache
confound: rerunning this script on the same suite is bit-identical.
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SUITE_DIR = Path("~/benchmark-runs/suite_20260805T033340Z")
DEFAULT_RESULTS_DIR = PROJECT_ROOT / "studies" / "analysis" / "results"

# Datasets on the metabolite arm. hgnc is the gene arm and carries no metabolite certificate.
METABOLITE_DATASETS = ("necs", "refmet", "srm1950", "lmsd", "metlinkr", "metabench", "metaboliteannotator")

# Gold columns holding a structural key, in preference order.
GOLD_INCHIKEY_COLUMNS = ("gold_inchikey", "inchikey", "gold_inchi_key")

# Gold identifier column -> the kg_equivalent_ids prefix it must be compared against. These are the
# only namespaces used by identifier_oracle, chosen because they are structure-bearing compound
# registries: a match means the KG node and the gold refer to the same catalogued compound.
GOLD_ID_COLUMNS: dict[str, str] = {
    "gold_hmdb": "HMDB",
    "gold_kegg": "KEGG.COMPOUND",
    "gold_pubchem": "PUBCHEM.COMPOUND",
}

INCHIKEY_PREFIX = "INCHIKEY"
CHOSEN_COL = "chosen_kg_id"
REVIEW_COL = "chosen_kg_id_review"
EQUIV_COL = "kg_equivalent_ids"

# Columns the pipeline emits once the resolution certificate ships. The pinned baseline predates
# them, so their absence is a supported input shape rather than an error -- the audit falls back to
# deriving Tier A from kg_equivalent_ids and records which source it used.
CERT_STATE_COL = "certificate_state"
CERT_STRUCTURE_COL = "certificate_structure_status"
CERT_SOURCE_COL = "certificate_independent_source"
CERT_TIER_B_OUTCOME_COL = "certificate_tier_b_outcome"
CERT_INDEPENDENT_COL = "certificate_independent_of_selection"

# The Tier-B sweep artifact, referenced by a FIXED name rather than a timestamp. A caption cannot
# cite a timestamped path, and the pinned suite carries no certificate columns, so without a fixed
# committed name the Tier-B half of the figure has no reproducible provenance.
TIER_B_SWEEP_FILENAME = "tier_b_sweep.json"

# States that are refusals, not answers. A refusal is reported as a RATE in panel A and is excluded
# from the precision-coverage curve in panel B -- see the module docstring for why crossing that
# boundary with a precision delta is the forbidden claim.
ABSTENTION_STATES = ("unavailable",)
OUT_OF_SCOPE_STATES = ("not_applicable",)

# Floor on Tier B's own resolution rate below which the curve is refused rather than published.
# Mirrors ``biomapper2.config.TIER_B_MIN_RESOLUTION_RATE``; duplicated as a plain constant so this
# study module stays importable without the package installed.
TIER_B_MIN_RESOLUTION_RATE = 0.5

# Label used in cross-tabs for a row the resolver did not flag. The whole point of the certificate
# work is that this label is currently overloaded, so it is named explicitly rather than left NaN.
NO_FLAG = "no_flag"


def _parse_mapping(raw: Any) -> dict[str, list[str]]:
    """Parse a ``kg_equivalent_ids`` cell (a repr'd dict in the TSV) into a mapping.

    Returns an empty mapping for anything unparseable, so a malformed cell degrades to
    "carries no identifiers" rather than raising mid-audit.
    """
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return {}
    try:
        parsed = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _first_block(inchikey: Any) -> str | None:
    """InChIKey first block (the 2-D connectivity skeleton), or None."""
    if not isinstance(inchikey, str) or not inchikey.strip():
        return None
    return inchikey.split("-")[0]


def _node_blocks(equiv: dict[str, list[str]]) -> set[str]:
    """Every InChIKey first block asserted on the committed node.

    Set-valued on purpose: a KG node's INCHIKEY list is multi-valued (neutral parent, conjugate
    anion, salt, stereoisomers) and its order is arbitrary, so testing membership rather than
    equality against one arbitrary representation is what the shipped D2 semantics do.
    """
    return {b for b in (_first_block(k) for k in equiv.get(INCHIKEY_PREFIX, []) or []) if b}


def _local_ids(values: Any) -> set[str]:
    """Normalize a gold identifier cell or an equivalent-ids list to bare local ids, upper-cased.

    Gold cells are free-text and may be comma- or semicolon-delimited and may or may not carry a
    CURIE prefix; equivalent-ids entries are already bare local ids. Both are reduced to the same
    shape so membership is a fair test.
    """
    if isinstance(values, (list, tuple, set)):
        items = [str(v) for v in values]
    elif isinstance(values, str) and values.strip():
        items = [p for p in values.replace(";", ",").split(",")]
    else:
        return set()
    return {p.strip().split(":")[-1].upper() for p in items if p and p.strip()}


def _quarantined_id_columns(df: pd.DataFrame) -> dict[str, str]:
    """Gold identifier columns that are row indices wearing an accession's clothes.

    A gold column that is fully unique across rows AND strictly monotonically increasing is a
    counter, not a curated annotation -- a real gold mapping has no reason to sort with the file.
    Scoring against one produces a near-zero precision that reads as a catastrophic resolver
    failure and is actually a defect in the benchmark input. Detected generically and reported in
    the artifact field ``quarantined_gold_columns`` rather than special-cased per dataset, so the
    same trap is caught in any future dataset. Quarantined columns are excluded from
    ``identifier_oracle`` and never silently scored.
    """
    quarantined: dict[str, str] = {}
    for gold_col in GOLD_ID_COLUMNS:
        if gold_col not in df.columns:
            continue
        values = df[gold_col].dropna()
        if len(values) < 2:
            continue
        if values.nunique() == len(values) and values.is_monotonic_increasing:
            quarantined[gold_col] = "strictly monotonic and fully unique across rows -- a row index, not an accession"
    return quarantined


def _gold_inchikey_column(df: pd.DataFrame) -> str | None:
    lowered = {c.lower(): c for c in df.columns}
    for candidate in GOLD_INCHIKEY_COLUMNS:
        if candidate in lowered:
            return lowered[candidate]
    return None


def _structure_oracle(gold_block: Any, node_blocks: set[str]) -> bool | None:
    """Correct iff the gold connectivity block is among the node's blocks. None when unscorable.

    The missing-value test is ``not isinstance(str)`` rather than ``is None`` deliberately. pandas
    infers a ``str`` dtype for the gold column, which silently converts a returned ``None`` into
    ``pd.NA``; ``pd.NA is None`` is False, so an identity guard admits every unscorable row into the
    denominator as an incorrect answer and depresses the reported precision. Regression-tested by
    ``tests/test_certificate_state_audit.py::test_unscorable_rows_leave_the_denominator``.
    """
    if not isinstance(gold_block, str) or not gold_block:
        return None
    return gold_block in node_blocks


def _identifier_oracle(row: pd.Series, equiv: dict[str, list[str]], usable_columns: dict[str, str]) -> bool | None:
    """Correct iff a gold compound-registry identifier is among the node's equivalent ids.

    Returns None when the row ships no gold identifier in any usable column -- unscorable is kept
    distinct from incorrect throughout this module.
    """
    scorable = False
    for gold_col, prefix in usable_columns.items():
        gold = _local_ids(row.get(gold_col))
        if not gold:
            continue
        scorable = True
        if gold & _local_ids(equiv.get(prefix)):
            return True
    return False if scorable else None


def _oracle_summary(frame: pd.DataFrame, oracle_col: str, state_col: str) -> dict[str, Any]:
    """Precision within each certificate state under one oracle, plus the blended number.

    Rows the oracle cannot score (None) are excluded from the denominator rather than counted as
    incorrect, so the reported precision is over the population the oracle can actually adjudicate.
    """
    scored = frame[frame[oracle_col].notna()]
    if scored.empty:
        return {"n_scored": 0, "blended_precision": None, "by_state": {}}
    by_state = {}
    for state, sub in scored.groupby(state_col):
        by_state[str(state)] = {
            "n": int(len(sub)),
            "share_of_scored": round(len(sub) / len(scored), 4),
            "n_correct": int(sub[oracle_col].sum()),
            "precision": round(float(sub[oracle_col].mean()), 4),
        }
    return {
        "n_scored": int(len(scored)),
        "blended_precision": round(float(scored[oracle_col].mean()), 4),
        "by_state": by_state,
    }


def _crosstab(frame: pd.DataFrame, index_col: str, value_col: str) -> dict[str, dict[str, int]]:
    """Plain nested-dict cross-tab, JSON-serializable and stable in key order."""
    out: dict[str, dict[str, int]] = {}
    for idx, sub in frame.groupby(index_col):
        counts = Counter(str(v) for v in sub[value_col] if v is not None and not pd.isna(v))
        out[str(idx)] = dict(sorted(counts.items()))
    return dict(sorted(out.items()))


def _figure5(df: pd.DataFrame, sparsity_control: dict[str, Any], has_certificate: bool) -> dict[str, Any]:
    """The numbers behind Figure 5's two panels. Rendering lives with the figure, not here.

    Panel A is a declared abstention RATE. Panel B is precision-coverage over the verifiable
    population only, stratified by independent source.

    Two panels rather than one because the difference is what makes the constraint legible: an
    abstention-rate panel shows refusal happening WITHOUT implying the refused answers were wrong,
    which a single precision-coverage panel tends to blur. A precision delta plotted across the
    abstention boundary would be the claim the sparsity control exists to rule out.
    """
    n_rows = int(len(df))
    abstained = df[df["_state"].isin(ABSTENTION_STATES)]
    out_of_scope = df[df["_state"].isin(OUT_OF_SCOPE_STATES)]

    panel_a = {
        "n_rows": n_rows,
        "n_unavailable": int(len(abstained)),
        "n_not_applicable": int(len(out_of_scope)),
        "abstention_rate": round(len(abstained) / n_rows, 4) if n_rows else None,
        "note": "declared abstention; a refused row is unverifiable, not wrong",
    }

    # The verifiable population: rows that are neither an abstention nor out of scope, AND that an
    # oracle can actually adjudicate. Everything else is excluded from the curve by construction.
    verifiable = df[~df["_state"].isin(ABSTENTION_STATES + OUT_OF_SCOPE_STATES) & df["_structure_oracle"].notna()]
    strata: dict[str, Any] = {}
    for source, sub in verifiable.groupby(verifiable["_independent_source"].fillna("none")):
        points = []
        for state, state_rows in sub.groupby("_state"):
            points.append(
                {
                    "certificate_state": str(state),
                    "n": int(len(state_rows)),
                    "coverage": round(len(state_rows) / n_rows, 4) if n_rows else None,
                    "precision": round(float(state_rows["_structure_oracle"].mean()), 4),
                }
            )
        independence = sub["_independent_of_selection"].dropna().unique().tolist()
        strata[str(source)] = {
            "n_verifiable": int(len(sub)),
            # None when the stratum mixes both, which is itself a reason not to average it.
            "independent_of_selection": bool(independence[0]) if len(independence) == 1 else None,
            "points": sorted(points, key=lambda p: p["certificate_state"]),
        }

    tier_b = _tier_b_stats(df)
    publishable, reason = _curve_publishable(has_certificate, tier_b)
    return {
        "panel_a_abstention": panel_a,
        "panel_b_precision_coverage": {"n_verifiable": int(len(verifiable)), "strata": strata},
        "tier_b": tier_b,
        "sparsity_control": sparsity_control,
        "curve_publishable": publishable,
        "curve_not_publishable_reason": reason,
    }


def _tier_b_stats(df: pd.DataFrame) -> dict[str, Any]:
    """Tier B's resolution rate over the audited rows, emitted beside every operating point.

    Without it a reader cannot see that corroboration was computed on whichever names the exact-name
    endpoints happened to know.

    Counted PER ROW, not per unique query name: a mapped TSV is the population the figure describes,
    and a name appearing twice contributes two operating-point rows. ``IndependentStructureLookup.
    stats()`` counts unique names instead, because there the quantity of interest is how many lookups
    were made. The two are deliberately different and are named so they cannot be confused.
    """
    outcomes = Counter(str(v) for v in df["_tier_b_outcome"])
    n_rows = int(len(df))
    n_resolved = int(outcomes.get("resolved", 0))
    return {
        "n_rows_with_tier_b_outcome": n_rows,
        "n_tier_b_resolved": n_resolved,
        "n_tier_b_lookup_failed": int(outcomes.get("lookup_failed", 0)),
        "resolution_rate": round(n_resolved / n_rows, 4) if n_rows else None,
        "outcomes": dict(sorted(outcomes.items())),
        "min_resolution_rate_floor": TIER_B_MIN_RESOLUTION_RATE,
    }


def _curve_publishable(has_certificate: bool, tier_b: dict[str, Any]) -> tuple[bool, str | None]:
    if not has_certificate:
        return False, "input carries no certificate_* columns; Tier A was derived, Tier B never ran"
    rate = tier_b["resolution_rate"]
    if rate is None or rate < TIER_B_MIN_RESOLUTION_RATE:
        return False, (
            "Tier B resolution rate is below the stated floor, so corroboration was computed on a "
            "biased easy subset of query names"
        )
    return True, None


def audit_dataset(name: str, mapped_tsv: Path) -> dict[str, Any]:
    """Derive the full certificate-state picture for one dataset's mapped rows."""
    # Read EVERY row. The committed-only filter is applied later and ONLY to oracle scoring.
    #
    # Filtering here instead would under-report abstention, because the certificate labels a
    # no-commit row ``unavailable`` -- an uncommitted row IS an abstention, and dropping it before
    # ``panel_a_abstention`` and ``certificate_state_counts`` removes exactly the rows those two
    # figures exist to count. This is latent on the current suite only because every arm in it is
    # fully committed; PR #47's category validator moves a large population to unmapped, so the next
    # suite WILL carry uncommitted rows and Panel A of Figure 5 would silently under-report. Pinned
    # by ``tests/test_certificate_state_audit.py::test_abstention_counts_uncommitted_rows``.
    df = pd.read_csv(mapped_tsv, sep="\t", low_memory=False)
    committed_mask = df[CHOSEN_COL].notna()

    df["_equiv"] = df[EQUIV_COL].map(_parse_mapping) if EQUIV_COL in df.columns else [{}] * len(df)
    df["_node_blocks"] = df["_equiv"].map(_node_blocks)

    # Tier A: the self-certificate state, computable from what the pipeline already emits.
    df["_tier_a"] = df["_node_blocks"].map(lambda b: "structure_present" if b else "structure_absent")

    # Prefer the certificate the pipeline committed; fall back to deriving it. The fallback is not a
    # silent equivalence -- a derived Tier A knows nothing about Tier B, so the artifact records
    # which source was used and the curve refuses to publish off the derivation.
    has_certificate = CERT_STATE_COL in df.columns
    if has_certificate:
        df["_state"] = df[CERT_STATE_COL].fillna("unavailable").astype(str)
        df["_independent_source"] = (
            df[CERT_SOURCE_COL].astype("object").where(df[CERT_SOURCE_COL].notna(), None)
            if CERT_SOURCE_COL in df.columns
            else None
        )
        df["_tier_b_outcome"] = df[CERT_TIER_B_OUTCOME_COL].fillna("off") if CERT_TIER_B_OUTCOME_COL in df else "off"
        df["_independent_of_selection"] = df[CERT_INDEPENDENT_COL] if CERT_INDEPENDENT_COL in df else None
    else:
        df["_state"] = df["_tier_a"].map({"structure_present": "uncorroborated", "structure_absent": "unavailable"})
        df["_independent_source"] = None
        df["_tier_b_outcome"] = "off"
        df["_independent_of_selection"] = None

    gold_col = _gold_inchikey_column(df)
    df["_gold_block"] = df[gold_col].map(_first_block) if gold_col else None
    df["_structure_oracle"] = [
        _structure_oracle(gb, nb) for gb, nb in zip(df["_gold_block"], df["_node_blocks"], strict=True)
    ]
    quarantined = _quarantined_id_columns(df)
    usable_id_columns = {c: p for c, p in GOLD_ID_COLUMNS.items() if c not in quarantined}
    df["_identifier_oracle"] = [_identifier_oracle(row, row["_equiv"], usable_id_columns) for _, row in df.iterrows()]
    df["_review"] = df[REVIEW_COL].fillna(NO_FLAG) if REVIEW_COL in df.columns else NO_FLAG

    # ``scored`` is the committed subset: an uncommitted row has no answer to adjudicate, so it
    # cannot enter a precision denominator. ``df`` stays whole for the state/abstention accounting.
    scored = df[committed_mask].copy()

    # The sparsity control. Restricted to rows the identifier oracle would score at all, then asks
    # how many structure_absent rows carry a comparable namespace. When that count is zero the
    # identifier oracle never had a chance to fire on the absent bucket, and NO precision claim
    # about that bucket is admissible under either oracle.
    id_scorable = scored[scored["_identifier_oracle"].notna()]
    absent_scorable = id_scorable[id_scorable["_tier_a"] == "structure_absent"]
    could_fire = absent_scorable["_equiv"].map(lambda e: any(e.get(p) for p in usable_id_columns.values()))

    sparsity_control = {
        "n_absent_identifier_scorable": int(len(absent_scorable)),
        "n_absent_oracle_could_fire": int(could_fire.sum()) if len(absent_scorable) else 0,
        "comparable_namespaces": sorted(GOLD_ID_COLUMNS.values()),
    }

    # Tier A describes the committed answer, so its denominator is the committed subset. The
    # certificate-state counts and Panel A use the FULL frame -- see the read comment above.
    tier_a_counts = Counter(scored["_tier_a"])
    return {
        "dataset": name,
        "source_file": str(mapped_tsv),
        "certificate_source": "certificate_columns" if has_certificate else "derived_from_kg_equivalent_ids",
        "n_rows": int(len(df)),
        "n_rows_with_commit": int(len(scored)),
        "n_rows_uncommitted": int(len(df) - len(scored)),
        "gold_inchikey_column": gold_col,
        "quarantined_gold_columns": quarantined,
        "identifier_oracle_columns": sorted(usable_id_columns),
        "tier_a": {
            "counts": dict(sorted(tier_a_counts.items())),
            "structure_absent_share": (
                round(tier_a_counts["structure_absent"] / len(scored), 4) if len(scored) else None
            ),
        },
        "structure_oracle": _oracle_summary(scored, "_structure_oracle", "_tier_a"),
        "identifier_oracle": _oracle_summary(scored, "_identifier_oracle", "_tier_a"),
        "sparsity_control": sparsity_control,
        "certificate_state_counts": dict(sorted(Counter(str(s) for s in df["_state"]).items())),
        "figure5": _figure5(df, sparsity_control, has_certificate),
        "review_flag_x_tier_a": _crosstab(scored, "_review", "_tier_a"),
        "review_flag_x_correctness": {
            "structure_oracle": _crosstab(scored[scored["_structure_oracle"].notna()], "_review", "_structure_oracle"),
            "identifier_oracle": _crosstab(
                scored[scored["_identifier_oracle"].notna()], "_review", "_identifier_oracle"
            ),
        },
    }


def _suite_provenance(suite_dir: Path) -> dict[str, Any]:
    """Read provenance from the suite manifest. Never hardcoded, so artifacts self-describe."""
    manifest = suite_dir / "suite_manifest.json"
    if not manifest.exists():
        return {"suite_manifest": None}
    data = json.loads(manifest.read_text())
    keys = ("kg_snapshot", "kg_stable_during_run", "git_sha", "biolink_version", "backend", "started_at")
    return {"suite_manifest": str(manifest), **{k: data.get(k) for k in keys if k in data}}


def audit(suite_dir: Path) -> dict[str, Any]:
    """Audit every metabolite-arm dataset in a pinned suite directory."""
    per_dataset = []
    for name in METABOLITE_DATASETS:
        matches = sorted((suite_dir / name).glob("*_d_mapped.tsv")) if (suite_dir / name).is_dir() else []
        if not matches:
            log.info("skipping %s: no *_d_mapped.tsv", name)
            continue
        for match in matches:
            # A dataset can ship several mapped files, one per target vocabulary arm (metlinkr runs
            # CHEBI/HMDB/KEGG/PUBCHEM/REFMET over the same inputs). They are separate populations,
            # never averaged, so the label carries the arm rather than collapsing to the dataset name.
            arm = match.name.split("_MAPPED_")[0]
            label = name if len(matches) == 1 else f"{name}:{arm.rsplit('_', 1)[-1]}"
            per_dataset.append(audit_dataset(label, match))
    return {
        "suite_dir": str(suite_dir),
        "provenance": _suite_provenance(suite_dir),
        "tier_b_sweep": _tier_b_sweep_provenance(suite_dir),
        "arm": "metabolite",
        "per_dataset": per_dataset,
    }


def _tier_b_sweep_provenance(suite_dir: Path) -> dict[str, Any]:
    """Locate the committed Tier-B sweep INSIDE the suite, or say plainly that there isn't one.

    Resolved relative to ``suite_dir`` rather than to the repo's results directory, so ``audit()``
    stays a pure function of its single input. Reading a repo path here would mean a sweep landing
    later silently changes the artifact for an unchanged suite -- breaking both the bit-identical
    contract and test hermeticity.

    The sweep is the only network-touching step in this line of work and is fired by an operator,
    never by a test or by this script. Until it lands, the Tier-B half of the figure has no
    reproducible provenance and the curve is refused rather than drawn from whatever a local run
    happened to produce.
    """
    path = suite_dir / TIER_B_SWEEP_FILENAME
    if not path.exists():
        return {"path": str(path), "present": False, "note": "no committed Tier B sweep; Tier B half unavailable"}
    data = json.loads(path.read_text())
    return {
        "path": str(path),
        "present": True,
        **{k: data.get(k) for k in ("suite_dir", "started_at", "git_sha", "cache_state", "tier_b") if k in data},
    }


def render_markdown(result: dict[str, Any]) -> str:
    """Human-readable rendering. Numbers come from the result dict, never from prose."""
    lines = [
        "# Certificate-state audit",
        "",
        f"Suite: `{result['suite_dir']}`",
        f"Provenance: `{json.dumps(result['provenance'], sort_keys=True)}`",
        "",
        "## Tier A certificate state and precision by state",
        "",
        "| dataset | rows | structure_absent share | struct-oracle blended | struct-oracle present "
        "| id-oracle blended | id-oracle present | absent rows id-oracle COULD score |",
        "|---|---|---|---|---|---|---|---|",
    ]

    def _fmt(value: Any) -> str:
        return "-" if value is None else (f"{value:.1%}" if isinstance(value, float) else str(value))

    for d in result["per_dataset"]:
        so, io = d["structure_oracle"], d["identifier_oracle"]
        lines.append(
            "| {} | {} | {} | {} | {} | {} | {} | {} |".format(
                d["dataset"],
                d["n_rows_with_commit"],
                _fmt(d["tier_a"]["structure_absent_share"]),
                _fmt(so["blended_precision"]),
                _fmt((so["by_state"].get("structure_present") or {}).get("precision")),
                _fmt(io["blended_precision"]),
                _fmt((io["by_state"].get("structure_present") or {}).get("precision")),
                d["sparsity_control"]["n_absent_oracle_could_fire"],
            )
        )
    lines += [
        "",
        "The last column is the admissibility test for any precision claim about the",
        "`structure_absent` bucket: when it is zero, neither oracle can adjudicate that bucket and",
        "the honest certificate state is `unavailable`, not `contradicted`.",
        "",
        "## Figure 5 — panel A: declared abstention rate",
        "",
        "Abstention is a coverage statistic, NOT an operating point. A precision delta plotted across",
        "the `unavailable` boundary would assert that refusing those rows buys precision, which no",
        "oracle here can support; this panel shows the refusal happening without implying the refused",
        "answers were wrong.",
        "",
        "| dataset | rows | unavailable | not_applicable | abstention rate | certificate source |",
        "|---|---|---|---|---|---|",
    ]
    for d in result["per_dataset"]:
        panel_a = d["figure5"]["panel_a_abstention"]
        lines.append(
            "| {} | {} | {} | {} | {} | {} |".format(
                d["dataset"],
                panel_a["n_rows"],
                panel_a["n_unavailable"],
                panel_a["n_not_applicable"],
                _fmt(panel_a["abstention_rate"]),
                d["certificate_source"],
            )
        )

    lines += [
        "",
        "## Figure 5 — panel B: precision-coverage within the verifiable population",
        "",
        "Stratified by independent source, never averaged: a verdict from the same registry that",
        "supplied the committed node is not independent evidence of it.",
        "",
    ]
    for d in result["per_dataset"]:
        figure5 = d["figure5"]
        lines += [
            f"### {d['dataset']}",
            "",
            f"Publishable: `{figure5['curve_publishable']}`"
            + (f" — {figure5['curve_not_publishable_reason']}" if figure5["curve_not_publishable_reason"] else ""),
            "",
            "```json",
            json.dumps(
                {"panel_b": figure5["panel_b_precision_coverage"], "tier_b": figure5["tier_b"]},
                indent=2,
            ),
            "```",
            "",
        ]

    lines += [
        "## Review flag vs Tier A state",
        "",
    ]
    for d in result["per_dataset"]:
        lines += [f"### {d['dataset']}", "", "```json", json.dumps(d["review_flag_x_tier_a"], indent=2), "```", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--suite-dir", type=Path, default=DEFAULT_SUITE_DIR, help="pinned suite dir (read-only)")
    parser.add_argument(
        "--out", type=Path, default=None, help="JSON artifact path (override, not the only way to save)"
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    suite_dir = args.suite_dir.expanduser().resolve()
    result = audit(suite_dir)

    # Saving is the default, not a flag.
    out_path = (args.out or (DEFAULT_RESULTS_DIR / f"certificate_state_audit_{suite_dir.name}.json")).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2) + "\n")
    out_path.with_suffix(".md").write_text(render_markdown(result) + "\n")
    log.info("wrote %s and %s", out_path, out_path.with_suffix(".md"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
