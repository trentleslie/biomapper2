import csv
import hashlib

from studies.annotation_reranking.models_data import EvalCase

# Exact names copied from analyze.py TRUE_BIOMAPPER_ERRORS dict (11 cases).
# BioMapper picked the wrong compound in each of these; the correct answer
# is RefMet's node (CHEBI:<refmet_id>).
TRUE_BIOMAPPER_ERRORS: set[str] = {
    "(15:3)-anacardic acid",
    "2-hydroxypalmitate",
    "4-acetamidophenol",
    "4-hydroxyhippurate",
    "4-methylbenzenesulfonate",
    "9-hydroxystearate",
    "5_HpEPE__4_55",
    "2-Methylmaleate",
    "laurylcarnitine (C12)",
    "myristoylcarnitine (C14)",
    "glycerophosphoinositol*",
}

# Exact names copied from analyze.py REFMET_ERRORS dict (2 cases).
# RefMet was wrong; BioMapper's first ID is the correct answer.
REFMET_ERRORS: set[str] = {
    "6-shogaol",
    "Diethyl 2-methyl-3-oxosuccinate",
}


def _curie(raw: str) -> str:
    """Normalize a bare ChEBI integer or existing CURIE to 'CHEBI:<n>' form."""
    raw = raw.strip()
    return raw if raw.startswith("CHEBI:") else f"CHEBI:{raw}"


def load_eval_cases(csv_path: str) -> list[EvalCase]:
    """Load all rows from the ChEBI disagreement CSV as typed EvalCase objects."""
    cases: list[EvalCase] = []
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            name = row["name"]
            bm_ids = [_curie(x) for x in row["biomapper_id"].split("|") if x.strip()]
            if name in TRUE_BIOMAPPER_ERRORS:
                correct: str | None = _curie(row["refmet_id"])
                src = "independent_biomapper_error"
            elif name in REFMET_ERRORS:
                correct = bm_ids[0] if bm_ids else None
                src = "independent_refmet_error"
            else:
                correct = None
                src = "refmet_agreement"
            cases.append(
                EvalCase(
                    name=name,
                    level=row["level"],
                    refmet_id=row["refmet_id"],
                    refmet_name=row["refmet_name"],
                    biomapper_ids=bm_ids,
                    biomapper_name=row["biomapper_name"],
                    category=row["category"],
                    correct_id=correct,
                    label_source=src,
                )
            )
    return cases


def independent_cases(cases: list[EvalCase]) -> list[EvalCase]:
    """Return only the independently-adjudicated cases (label_source starts with 'independent_')."""
    return [c for c in cases if c.label_source.startswith("independent_")]


def dataset_sha256(csv_path: str) -> str:
    """Return the SHA-256 hex digest of the CSV file for reproducibility pinning."""
    with open(csv_path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()
