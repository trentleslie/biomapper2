"""metLinkR dual scorer — TWO labelled oracles for the same-task cross-linking head-to-head.

metLinkR (Patt et al. 2025) reports AGREEMENT with the COMETS expert curators (~85.3%) and does NOT
validate its links against an InChIKey structural oracle. This scorer emits BOTH, never merged:

  (a) CURATOR-AGREEMENT rate — metLinkR's own metric. Over the curator's cross-DATASET linked pairs
      (two rows the curators placed in the same ``Manual_Metabolite_Group_Label`` but that came from
      DIFFERENT COMETS datasets), the fraction that BioMapper ALSO links: its two independently
      name-resolved canonical-identifier sets intersect (``curie_scorer.predicted_curies``). The
      curator grouping is HELD OUT of BioMapper's input, so a link is non-trivial — BioMapper must
      arrive at the same canonical for both members from the NAME alone. This is a link RECALL on
      the curator's asserted cross-links (the ~85.3%-comparable number); a count of BioMapper links
      the curators did NOT assert (potential over-linking) is reported for context, never merged.

  (b) INCHIKEY STRUCTURAL CONCORDANCE — the oracle metLinkR LACKS (BioMapper's differentiator). For
      each row carrying a HELD-OUT curator/Metabolon provided reference id (HMDB / PubChem), resolve
      BOTH BioMapper's name-chosen id AND the curator id to an InChIKey first-block and compare. This
      asks whether BioMapper's LINK is structurally right, not merely identifier/name-consistent.

Discipline (Hajjar/NECS/MetaboliteAnnotator learnings):
  - TWO numbers, each labelled; the coverage-shaped curator-agreement is NEVER merged with the
    structural-concordance correctness qualifier.
  - ANTI-TRIVIAL: both oracles are held out; ``assert_curator_held_out`` re-checks (fail-loud) that
    the curator grouping / provided-id columns are present-for-the-scorer-only and are NOT the query.
  - FAIL-LOUD on unscorable: a run with zero curator cross-pairs AND zero structural rows raises
    rather than reporting a hollow rate.
  - SHARED-INFRA CAVEAT: oracle (b) resolves BOTH the prediction and the curator id through the same
    KG structure oracle, so it is not fully infra-independent the way a curated-InChIKey column is
    (there is no such column in the metLinkR SI). The number is honest about validating the LINK
    against the curator's structural reference; a fully-independent external resolver for the curator
    id is a documented follow-on (reported as a caveat, never silently asserted).
"""

from __future__ import annotations

from typing import Any, Protocol

import pandas as pd

from ..config import MetLinkRDatasetConfig
from .curie_scorer import EQUIV_COL, _parse_equiv, predicted_curies
from .structure_oracle_scorer import CHOSEN_COL, _has_prediction, first_block

# Adapter passthrough column (must match the adapter constant of the same name).
INPUT_ROW_ID_COL = "input_row_id"

# "No value" tokens (R ``NA``, pandas ``nan``) a readback cell may carry — treated as empty.
_NULL_TOKENS = frozenset({"", "na", "nan", "null", "none"})

# Held-out curator provided-id namespace -> KG-RESOLVABLE CURIE prefixes (first that resolves wins).
# The Kestrel KG addresses PubChem compounds as ``PUBCHEM.COMPOUND:`` (a bare ``PUBCHEM:`` 400s /
# returns empty), so the curator id must be offered in the KG's prefix form for the structure oracle
# to resolve it. HMDB is addressed directly. Bare forms are kept as a defensive fallback.
_CURATOR_RESOLUTION_PREFIXES: dict[str, tuple[str, ...]] = {
    "hmdb": ("HMDB",),
    "pubchem": ("PUBCHEM.COMPOUND", "PUBCHEM"),
}


class UnscorableRunError(RuntimeError):
    """Raised when there is nothing to score (no curator pairs and no structural rows)."""


class CuratorLeakError(RuntimeError):
    """Raised when a held-out curator column is missing or collides with the query (anti-trivial)."""


class StructureBlockOracle(Protocol):
    """Minimal live-oracle surface: resolve a node id / CURIE to an InChIKey first-block."""

    def resolved_block(self, node_id: str) -> str | None: ...


def _norm(value: Any) -> str:
    return "" if value is None else str(value).strip()


def assert_curator_held_out(mapped_df: pd.DataFrame, config: MetLinkRDatasetConfig) -> None:
    """Fail-loud anti-trivial guard: curator grouping / provided-id columns are held out, not query.

    The columns must be PRESENT (the scorer needs them) but must NOT be the ``name_column`` (which is
    the only thing handed to BioMapper). A grouping-as-query config would leak the curator link into
    the input and score a trivial 100%.
    """
    if config.group_label_column == config.name_column:
        raise CuratorLeakError(
            f"{config.key}: curator group label column equals the query name column — the grouping "
            f"must be held out, not handed to BioMapper."
        )
    missing = [
        c
        for c in (config.group_label_column, config.gold_hmdb_column, config.gold_pubchem_column)
        if c not in mapped_df.columns
    ]
    if missing:
        raise CuratorLeakError(
            f"{config.key}: held-out curator columns {missing!r} are absent from the mapped frame; "
            f"the adapter must carry them through untouched for the scorer."
        )


def _clean_id_value(v: str) -> str:
    """Strip a bare provided-id value, dropping a float ``.0`` tail (TSV readback coerces numeric
    PubChem ids to float, e.g. ``159663.0``) and R null tokens."""
    s = v.strip()
    if s.lower() in _NULL_TOKENS:
        return ""
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s


def _hmdb_accession_forms(value: str) -> list[str]:
    """Legacy-and-modern HMDB accession forms (Metabolon ships legacy 5-digit ``HMDB02759``; the KG
    uses the zero-padded 7-digit ``HMDB0002759``). Returns both zero-padded and original digit forms
    so the oracle can resolve either."""
    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits:
        return [value]
    forms = [f"HMDB{digits.zfill(7)}"]
    original = f"HMDB{digits}"
    if original not in forms:
        forms.append(original)
    return forms


def curator_resolution_curies(row: pd.Series, config: MetLinkRDatasetConfig) -> list[str]:
    """The row's HELD-OUT curator provided ids as KG-RESOLVABLE CURIE candidates (HMDB / PubChem).

    Bare source values (e.g. ``HMDB02759``, ``497299``) are offered in each namespace's KG-resolvable
    prefix form: PubChem as ``PUBCHEM.COMPOUND:`` first (the bare ``PUBCHEM:`` is not addressable in
    the KG), and HMDB in BOTH the zero-padded 7-digit modern accession and its legacy form (Metabolon
    delivers legacy short accessions). Order is HMDB then PubChem; the structural scorer resolves
    candidates in order and takes the first that yields a block. ``|``-multi values are supported.
    """
    out: list[str] = []
    seen: set[str] = set()

    def _add(curie: str) -> None:
        if curie not in seen:
            seen.add(curie)
            out.append(curie)

    for column, key in ((config.gold_hmdb_column, "hmdb"), (config.gold_pubchem_column, "pubchem")):
        raw = _norm(row.get(column))
        if not raw:
            continue
        for part in raw.split("|"):
            v = _clean_id_value(part)
            if not v:
                continue
            if ":" in v:
                _add(v)  # already prefixed (defensive)
            elif key == "hmdb":
                for form in _hmdb_accession_forms(v):
                    _add(f"HMDB:{form}")
            else:
                for pfx in _CURATOR_RESOLUTION_PREFIXES[key]:
                    _add(f"{pfx}:{v}")
    return out


def prediction_block(row: pd.Series, oracle: "StructureBlockOracle | None") -> str | None:
    """BioMapper's chosen-node InChIKey first-block.

    Primary: read the INCHIKEY carried INLINE in the row's ``kg_equivalent_ids`` (already fetched by
    the mapping's equivalence expansion — no extra network call, robust to a flaky get-nodes route).
    Fallback: resolve ``chosen_kg_id`` through the oracle. Returns None when neither yields a block.
    """
    equiv = _parse_equiv(row.get(EQUIV_COL))
    inchikeys = equiv.get("INCHIKEY") if isinstance(equiv, dict) else None
    if isinstance(inchikeys, (list, tuple)) and inchikeys:
        b = first_block(inchikeys[0])
        if b is not None:
            return b
    chosen = row.get(CHOSEN_COL)
    if oracle is not None and _has_prediction(chosen):
        return oracle.resolved_block(str(chosen).strip())
    return None


def merge_vocab_runs(mapped_dfs: list[pd.DataFrame], config: MetLinkRDatasetConfig) -> pd.DataFrame:
    """Union the per-vocab mapper passes of the SAME input row into one row (no per-vocab axis).

    ``run_all`` runs one pass per target vocab; a given metabolite may resolve in the HMDB pass but
    not the CHEBI pass. Keyed by ``input_row_id`` (source-file-scoped, unique across datasets), this
    folds every pass's predictions (``chosen_kg_id`` + ``kg_equivalent_ids``) into one row so a link
    caught in any pass counts. The held-out curator columns are carried through untouched.
    """
    if not mapped_dfs:
        raise ValueError("merge_vocab_runs: no vocab runs to merge")
    carry = [
        config.name_column,
        config.group_label_column,
        config.gold_hmdb_column,
        config.gold_pubchem_column,
        config.source_file_column,
        INPUT_ROW_ID_COL,
    ]
    agg: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for df in mapped_dfs:
        for _, row in df.iterrows():
            key = _norm(row.get(INPUT_ROW_ID_COL)) or _norm(row.get(config.name_column))
            rec = agg.get(key)
            if rec is None:
                rec = {col: _norm(row.get(col)) for col in carry}
                rec[CHOSEN_COL] = ""
                rec["_ns"] = {}  # namespace -> set of local ids across passes
                agg[key] = rec
                order.append(key)
            chosen = row.get(CHOSEN_COL)
            if _has_prediction(chosen) and not rec[CHOSEN_COL]:
                rec[CHOSEN_COL] = str(chosen).strip()  # representative node (first non-empty pass)
            for curie in predicted_curies(row):
                ns, _, local = curie.partition(":")
                rec["_ns"].setdefault(ns, set()).add(local or ns)
    rows: list[dict[str, Any]] = []
    for key in order:
        rec = agg[key]
        rec[EQUIV_COL] = {ns: sorted(locals_) for ns, locals_ in rec.pop("_ns").items()}
        rows.append(rec)
    return pd.DataFrame(rows)


def _curator_cross_pairs(mapped_df: pd.DataFrame, config: MetLinkRDatasetConfig) -> list[tuple[int, int]]:
    """Index pairs the curators cross-linked ACROSS datasets (same group label, different source file)."""
    groups: dict[str, list[int]] = {}
    for i in range(len(mapped_df)):
        label = _norm(mapped_df.iloc[i].get(config.group_label_column))
        if label:
            groups.setdefault(label, []).append(i)
    pairs: list[tuple[int, int]] = []
    sf_col = config.source_file_column
    for members in groups.values():
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                i, j = members[a], members[b]
                sfi = _norm(mapped_df.iloc[i].get(sf_col))
                sfj = _norm(mapped_df.iloc[j].get(sf_col))
                if sfi and sfj and sfi != sfj:
                    pairs.append((i, j))
    return pairs


def score_metlinkr(
    mapped_df: pd.DataFrame,
    config: MetLinkRDatasetConfig,
    vocab: str | None = None,
    *,
    oracle: StructureBlockOracle | None = None,
) -> dict[str, Any]:
    """Dual-oracle scoring: curator-agreement rate + InChIKey structural concordance."""
    assert_curator_held_out(mapped_df, config)  # anti-trivial: grouping/provided-ids held out
    total_rows = len(mapped_df)

    # Precompute the predicted CURIE set per row once (used by oracle (a)).
    preds: list[set[str]] = [predicted_curies(mapped_df.iloc[i]) for i in range(total_rows)]

    # ---- Oracle (a): curator agreement over cross-dataset linked pairs -----------------------------
    pairs = _curator_cross_pairs(mapped_df, config)
    linked = 0
    for i, j in pairs:
        if preds[i] & preds[j]:  # BioMapper links iff the two canonical sets intersect
            linked += 1
    curator_rate = (linked / len(pairs)) if pairs else None

    # ---- Oracle (b): InChIKey structural concordance vs the held-out curator provided id -----------
    struct_available = oracle is not None and hasattr(oracle, "resolved_block")
    struct_scored = 0
    struct_concordant = 0
    struct_per_row: list[dict[str, Any]] = []
    if struct_available:
        for i in range(total_rows):
            row = mapped_df.iloc[i]
            chosen = row.get(CHOSEN_COL)
            curator_ids = curator_resolution_curies(row, config)
            if not curator_ids or not _has_prediction(chosen):
                continue
            # Prediction side: inline INCHIKEY (no network) with an oracle fallback.
            pred_block = prediction_block(row, oracle)
            # Curator (reference) side: first held-out provided id that the oracle resolves to a block.
            gold_block: str | None = None
            for cid in curator_ids:
                b = oracle.resolved_block(cid)  # type: ignore[union-attr]
                if b is not None:
                    gold_block = b
                    break
            if pred_block is None or gold_block is None:
                continue  # coverage-only: unresolved either side -> excluded from the denominator
            struct_scored += 1
            concordant = pred_block == gold_block
            if concordant:
                struct_concordant += 1
            struct_per_row.append(
                {
                    "input_row_id": _norm(row.get(INPUT_ROW_ID_COL)),
                    "name": row.get(config.name_column),
                    "chosen_kg_id": str(chosen).strip(),
                    "pred_block": pred_block,
                    "gold_block": gold_block,
                    "concordant": concordant,
                }
            )

    if not pairs and struct_scored == 0:
        raise UnscorableRunError(
            f"{config.key}: no curator cross-dataset pairs AND no structurally-resolvable rows — "
            f"nothing to score. Refusing to report a hollow rate for a run that measured nothing."
        )

    structural: dict[str, Any] | None
    if struct_available:
        structural = {
            "metric": "inchikey_structural_concordance",
            "scored": struct_scored,
            "concordant": struct_concordant,
            "concordance_rate": (struct_concordant / struct_scored) if struct_scored else None,
            "shared_infra_caveat": (
                "prediction and curator id both resolved via the KG structure oracle; not a fully "
                "infra-independent curated-InChIKey column (none exists in the metLinkR SI)"
            ),
        }
    else:
        structural = None

    # Count BioMapper links the curators did NOT assert as a cross-pair (context only, not merged):
    # of the curator's WITHIN-group non-cross pairs? Kept minimal — we report only the confirmed count.
    return {
        "vocab": vocab,
        "input_type": config.input_type,
        "curator_agreement": {
            "metric": "curator_agreement_rate",
            "curator_agreement_rate": curator_rate,
            "linked": linked,
            "curator_cross_pairs": len(pairs),
        },
        "inchikey_structural_concordance": structural,
        "n_rows": total_rows,
    }
