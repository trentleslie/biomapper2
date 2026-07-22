"""Unit 3 - pure scoring: gold-quality gate, two metrics, failure taxonomy.

All inputs here are already-normalised strings/ints (formulas from RDKit, components
from pygoslin) so this module has ZERO dependency on rdkit/pygoslin and is fully
offline-testable. It is the heart of the resolution-aware design.

Gold-quality GATE (the anti-#3-completeness defense, applied BEFORE scoring):
  keep a row only if the shorthand parses AND the neutral name->formula (pygoslin)
  equals the LMSD structure->formula (RDKit on gold_smiles). This guarantees the
  shorthand genuinely denotes the gold's sum composition — the two independent paths
  agree — so we never grade against a misspecified row. Gate failures are ungradeable
  (dropped, counted), not model failures. A high gate pass-rate is itself evidence the
  benchmark is well-specified (what ``harbor analyze`` / reviewers check for).

Two metrics on the SAME model output (mirrors #3's block-vs-full dual granularity):
  1. SPECIES-match (fair, the intended resolution): RDKit-formula(model_smiles) ==
     pygoslin-formula(shorthand). Any structurally valid realisation of the sum
     composition passes — the model is NOT required to hit LMSD's specific isomer.
  2. STRICT-match (over-specified, reproduces 5.4%): InChIKey(model) == gold_inchikey,
     at first-block and full granularity. This is the isomer lottery.

The GAP between (1) and (2) quantifies how much of the published difficulty is
misspecification (isomer lottery) vs genuine lipid-assembly failure. The failure
taxonomy on species-MISSES tells us whether the residual hardness is meaningful
chemistry (in-band-worthy) or format noise (below-band artifact).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass


@dataclass(frozen=True)
class NameScore:
    name: str
    gradeable: bool  # passed the gold-quality gate
    species_pass: bool
    strict_block_pass: bool
    strict_full_pass: bool
    class_ok: bool | None  # secondary backbone/class consistency (None = uncovered)
    failure_bucket: str | None  # populated on a species-miss


# --- gate ---------------------------------------------------------------------


def gold_quality_gate(*, parsed: bool, ref_formula: str | None, gold_formula: str | None) -> bool:
    """Row is gradeable iff shorthand parsed AND neutral name->formula == structure->formula."""
    return bool(parsed and ref_formula and gold_formula and ref_formula == gold_formula)


# --- per-name scoring ---------------------------------------------------------


def classify_failure(
    *,
    model_smiles: str | None,
    model_formula: str | None,
    ref_formula: str | None,
    model_total_carbons: int | None,
    ref_total_carbons: int | None,
    model_total_db: int | None,
    ref_total_db: int | None,
    model_class: str | None,
    ref_class: str | None,
    class_ok: bool | None,
) -> str:
    """Bucket a species-level miss into a meaningful-vs-artifact category.

    Uses the model's SELF-REPORTED reading (class / total C / total DB) where present to
    localise the error; falls back to formula-only signals. Order matters (most specific
    first).
    """
    if not model_smiles:
        return "no_structure_emitted"
    if model_formula is None:
        return "invalid_smiles"  # RDKit could not parse what the model emitted
    if model_class and ref_class and _norm(model_class) != _norm(ref_class):
        return "wrong_class"
    if (
        model_total_carbons is not None
        and ref_total_carbons is not None
        and model_total_carbons != ref_total_carbons
    ):
        return "wrong_carbon_count"
    if (
        model_total_db is not None
        and ref_total_db is not None
        and model_total_db != ref_total_db
    ):
        return "wrong_double_bond_count"
    return "formula_mismatch_other"


def _norm(s: str) -> str:
    return s.strip().lower().replace(" ", "")


def score_name(
    *,
    name: str,
    gradeable: bool,
    model_smiles: str | None,
    model_formula: str | None,
    model_inchikey: str | None,
    ref_formula: str | None,
    gold_inchikey: str,
    class_ok: bool | None,
    model_total_carbons: int | None = None,
    ref_total_carbons: int | None = None,
    model_total_db: int | None = None,
    ref_total_db: int | None = None,
    model_class: str | None = None,
    ref_class: str | None = None,
) -> NameScore:
    from .reference import first_block

    if not gradeable:
        return NameScore(
            name=name,
            gradeable=False,
            species_pass=False,
            strict_block_pass=False,
            strict_full_pass=False,
            class_ok=class_ok,
            failure_bucket=None,
        )

    species_pass = bool(model_formula and ref_formula and model_formula == ref_formula)

    mb, gb = first_block(model_inchikey), first_block(gold_inchikey)
    strict_block = bool(mb and gb and mb == gb)
    strict_full = bool(
        model_inchikey
        and gold_inchikey
        and model_inchikey.strip() == gold_inchikey.strip()
    )

    bucket = None
    if not species_pass:
        bucket = classify_failure(
            model_smiles=model_smiles,
            model_formula=model_formula,
            ref_formula=ref_formula,
            model_total_carbons=model_total_carbons,
            ref_total_carbons=ref_total_carbons,
            model_total_db=model_total_db,
            ref_total_db=ref_total_db,
            model_class=model_class,
            ref_class=ref_class,
            class_ok=class_ok,
        )

    return NameScore(
        name=name,
        gradeable=True,
        species_pass=species_pass,
        strict_block_pass=strict_block,
        strict_full_pass=strict_full,
        class_ok=class_ok,
        failure_bucket=bucket,
    )


# --- aggregate ----------------------------------------------------------------


@dataclass(frozen=True)
class Aggregate:
    n_drawn: int
    n_gradeable: int
    gate_pass_rate: float | None
    species_match_rate: float | None  # over gradeable
    strict_block_rate: float | None
    strict_full_rate: float | None
    # of species-passes, how many ALSO fail the class/backbone check (collision signal)
    species_pass_class_collisions: int
    failure_taxonomy: dict

    def as_dict(self) -> dict:
        return {
            "n_drawn": self.n_drawn,
            "n_gradeable": self.n_gradeable,
            "gate_pass_rate": self.gate_pass_rate,
            "species_match": {
                "rate": self.species_match_rate,
                "denominator": self.n_gradeable,
                "class_collisions_among_passes": self.species_pass_class_collisions,
            },
            "strict_match": {
                "first_block_rate": self.strict_block_rate,
                "full_key_rate": self.strict_full_rate,
                "denominator": self.n_gradeable,
            },
            "failure_taxonomy": self.failure_taxonomy,
        }


def aggregate(scores: list[NameScore]) -> Aggregate:
    n_drawn = len(scores)
    gradeable = [s for s in scores if s.gradeable]
    n_g = len(gradeable)

    def rate(passes: int) -> float | None:
        return (passes / n_g) if n_g else None

    species_passes = sum(1 for s in gradeable if s.species_pass)
    collisions = sum(1 for s in gradeable if s.species_pass and s.class_ok is False)
    tax = Counter(s.failure_bucket for s in gradeable if s.failure_bucket)

    return Aggregate(
        n_drawn=n_drawn,
        n_gradeable=n_g,
        gate_pass_rate=(n_g / n_drawn) if n_drawn else None,
        species_match_rate=rate(species_passes),
        strict_block_rate=rate(sum(1 for s in gradeable if s.strict_block_pass)),
        strict_full_rate=rate(sum(1 for s in gradeable if s.strict_full_pass)),
        species_pass_class_collisions=collisions,
        failure_taxonomy=dict(tax),
    )
