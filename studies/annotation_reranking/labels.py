"""InChIKey-connectivity label derivation for the annotation-reranking study (Task 10).

Realizes Change B: derives independent structural labels for disagreement cases
by comparing InChIKey first blocks (2-D connectivity skeletons), scaling the
eval beyond the ~13 hand-triaged cases.

Public interface
----------------
name_block(name) -> str | None
    The analyte's TRUE InChIKey first block resolved by NAME only
    (MW → PubChem; no KG layer — there is no node_id for a bare name).
    Cached by name. Never raises.

derive_label(case, *, name_block_fn, node_block_fn) -> tuple[str|None, str, str|None]
    Single-case label derivation.  Both block functions are injectable for tests.

derive_labels(cases) -> list[EvalCase]
    Apply derive_label to every case in-place and return the list.
"""
from __future__ import annotations

import functools
import logging
from typing import Callable

from studies.annotation_reranking.inchikey_resolver import (
    _block_from_mw,
    _block_from_pubchem,
    inchikey_block,
)
from studies.annotation_reranking.models_data import EvalCase

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# name_block — NAME-only resolution (MW → PubChem; no KG layer)
# ---------------------------------------------------------------------------

def _name_block_impl(name: str) -> str | None:
    """Resolve the analyte's true InChIKey first block by name.

    Layer order: Metabolomics Workbench → PubChem (no KG — there is no node_id).
    Returns the first non-None result or None on any error.  Never raises.
    """
    block = _block_from_mw(name)
    if block is not None:
        return block
    return _block_from_pubchem(name)


# Cached by name — same pattern as inchikey_block.
name_block: Callable[[str], str | None] = functools.lru_cache(maxsize=2048)(_name_block_impl)


# ---------------------------------------------------------------------------
# derive_label — priority-ordered decision rule
# ---------------------------------------------------------------------------

def derive_label(
    case: EvalCase,
    *,
    name_block_fn: Callable[[str], str | None] = name_block,
    node_block_fn: Callable[[str, str], str | None] | None = None,
) -> tuple[str | None, str, str | None]:
    """Derive a structural label for *case*.

    Decision rule (PRIORITY ORDER — earlier rules take precedence):

    1. Hand-triaged wins: ``label_source`` starts with ``"independent_"``
       → return (case.correct_id, case.label_source, None) unchanged.

    2. Same connectivity → not adjudicable: if ``rb is not None`` and any
       biomapper block ``bb == rb`` → (None, "expert_needed", ref).
       NOTE: this rule fires even when ref differs from rb.

    3. Structural pick (needs ref):
       - rb == ref and no bio bb == ref → (refmet_curie, "inchikey_connectivity", ref)
       - exactly one bio bb == ref and rb != ref → (that_bid, "inchikey_connectivity", ref)
       - else → (None, "refmet_agreement", ref)

    4. ref is None (and not same-connectivity) → (None, "refmet_agreement", None).

    Parameters
    ----------
    case:
        EvalCase to derive label for.
    name_block_fn:
        Injectable function ``(name: str) -> str | None``.  Defaults to
        ``name_block`` (the module-level cached resolver).
    node_block_fn:
        Injectable function ``(node_id: str, name: str) -> str | None``.
        Defaults to ``inchikey_resolver.inchikey_block``.

    Returns
    -------
    tuple of (correct_id, label_source, inchikey_block_correct)
    """
    if node_block_fn is None:
        node_block_fn = inchikey_block

    # Rule 1: hand-triaged cases are returned unchanged.
    if case.label_source.startswith("independent_"):
        return (case.correct_id, case.label_source, None)

    refmet_curie = f"CHEBI:{case.refmet_id.strip()}"
    rb = node_block_fn(refmet_curie, case.refmet_name)

    bio_blocks: list[str | None] = [
        node_block_fn(bid, case.biomapper_name) for bid in case.biomapper_ids
    ]

    # Rule 2: same connectivity → not adjudicable (even if ref differs).
    if rb is not None and any(bb == rb for bb in bio_blocks if bb is not None):
        ref = name_block_fn(case.name)
        return (None, "expert_needed", ref)

    # Resolve analyte's true connectivity by name.
    ref = name_block_fn(case.name)

    # Rule 3: structural pick (ref required).
    if ref is not None:
        bio_matches = [
            bid
            for bid, bb in zip(case.biomapper_ids, bio_blocks)
            if bb is not None and bb == ref
        ]
        if rb == ref and not bio_matches:
            return (refmet_curie, "inchikey_connectivity", ref)
        if len(bio_matches) == 1 and rb != ref:
            return (bio_matches[0], "inchikey_connectivity", ref)
        # Ambiguous / neither cleanly matches.
        return (None, "refmet_agreement", ref)

    # Rule 4: ref is None and not same-connectivity.
    return (None, "refmet_agreement", None)


# ---------------------------------------------------------------------------
# derive_labels — bulk application
# ---------------------------------------------------------------------------

def derive_labels(cases: list[EvalCase]) -> list[EvalCase]:
    """Apply ``derive_label`` to each case and mutate it in-place.

    Sets ``case.correct_id``, ``case.label_source``, and
    ``case.inchikey_block_correct`` on every case, then returns the list.
    """
    for case in cases:
        correct_id, label_source, inchikey_block_correct = derive_label(case)
        case.correct_id = correct_id
        case.label_source = label_source
        case.inchikey_block_correct = inchikey_block_correct
    return cases
