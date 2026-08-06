"""Bind the results section's numeric claims to named artifact fields.

The prose guard in the test suite covers source files. The manuscript is not a source file and does
not live in this repository, so guarding a module that by construction contains no prose numbers
protects a surface that was never at risk. This is the check that covers the surface that is:
every numeric claim in the committed copy of the results section resolves to a NAMED field in the
committed interval artifact, and the check fails when a claim resolves to nothing or when a field
it named has been renamed underneath it.

Two failure modes, kept distinct because the fixes differ:

* **unresolved** — a claim names no field, or names one in an artifact that is not committed. The
  fix is to produce the artifact (usually a gated run) or to withdraw the claim.
* **renamed** — a claim names a field that the artifact no longer has. The fix is in the code that
  writes the artifact, or in the claim. Silent renaming is the dangerous one: the claim keeps
  reading as backed while nothing backs it.

Drift between a claim's manuscript value and the artifact's value is reported separately. Drift is
expected while the manuscript predates the current run: it is a restatement task, not a defect in
either file, and conflating it with a rename would make the check unable to fail for the right
reason.

Everything is read from disk. No requests.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

MODULE_DIR = Path(__file__).parent
MANUSCRIPT_DIR = MODULE_DIR / "manuscript"
SOURCE_PATH = MANUSCRIPT_DIR / "section3_source.md"
CLAIMS_PATH = MANUSCRIPT_DIR / "section3_claims.json"
# The interval artifact is produced by ``studies/analysis/confidence_report.py`` and lands beside
# the other analysis artifacts, under the ``.gitignore`` negation that keeps them committed. This
# module reads it from there rather than from its own tree.
# The interval artifact is produced by ``confidence_report.py``, now a sibling module, so this is
# simply the shared results directory rather than a hop across trees.
RESULTS_DIR = MODULE_DIR / "results"

# Relative tolerance when comparing a manuscript rate against an artifact rate. The manuscript
# rounds; the artifact does not.
RATE_TOLERANCE = 5e-3


def load_claims(path: Path | None = None) -> dict[str, Any]:
    return json.loads((path or CLAIMS_PATH).read_text())


def latest_interval_artifact(results_dir: Path | None = None) -> Path | None:
    candidates = sorted((results_dir or RESULTS_DIR).glob("confidence_intervals_*.json"))
    return candidates[-1] if candidates else None


def _index_rows(artifact: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["row_id"]: row for row in artifact.get("rows", [])}


def reconcile(claims: dict[str, Any], artifact: dict[str, Any]) -> dict[str, Any]:
    """Resolve every claim against the artifact and classify the outcome."""
    rows = _index_rows(artifact)
    resolved: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    renamed: list[dict[str, Any]] = []
    drifted: list[dict[str, Any]] = []

    for entry in claims["claims"]:
        if entry.get("blocked_by"):
            unresolved.append({"id": entry["id"], "artifact": entry["artifact"], "reason": entry["blocked_by"]})
            continue
        if entry["artifact"] != "confidence_intervals":
            # Named, but owned by an artifact this check does not read. Recorded rather than
            # silently passed: an unchecked claim is not a verified claim.
            unresolved.append(
                {
                    "id": entry["id"],
                    "artifact": entry["artifact"],
                    "reason": "resolves against an artifact this check does not read",
                }
            )
            continue
        row = rows.get(entry["row_id"])
        if row is None:
            renamed.append(
                {
                    "id": entry["id"],
                    "row_id": entry["row_id"],
                    "reason": "no row with this identifier in the artifact; it was renamed or dropped",
                }
            )
            continue
        missing_fields = [key for key in entry["field"].split(",") if key not in row]
        if missing_fields:
            renamed.append(
                {
                    "id": entry["id"],
                    "row_id": entry["row_id"],
                    "reason": f"row is present but field(s) {missing_fields!r} are not",
                }
            )
            continue
        record = {
            "id": entry["id"],
            "row_id": entry["row_id"],
            "field": entry["field"],
            "artifact_value": {key: row[key] for key in entry["field"].split(",")},
            "manuscript_value": entry["manuscript_value"],
        }
        resolved.append(record)
        if _has_drifted(entry, row):
            drifted.append(record)

    return {
        "artifact_suite_id": artifact["header"]["suite_id"],
        "artifact_git_sha": artifact["header"]["git_sha"],
        "n_claims": len(claims["claims"]),
        "resolved": resolved,
        "unresolved": unresolved,
        "renamed": renamed,
        "drifted": drifted,
        "ok": not renamed,
        "restatement_required": bool(drifted),
    }


def _has_drifted(entry: dict[str, Any], row: dict[str, Any]) -> bool:
    value = entry.get("manuscript_value")
    if value is None:
        return False
    if isinstance(value, dict):
        if value.get("k") is None or value.get("n") is None:
            return False
        if row.get("k") is None or row.get("n") is None:
            return False  # the field is absent; that is a rename, already reported as one
        return int(value["k"]) != int(row["k"]) or int(value["n"]) != int(row["n"])
    if row.get("rate") is None:
        return True
    return abs(float(value) - float(row["rate"])) > RATE_TOLERANCE


# ------------------------------------------------------------------------------------------------
# The completeness half: no number in the prose may be missing from the inventory
# ------------------------------------------------------------------------------------------------
_PROSE_NUMBER = re.compile(r"\b\d+(?:,\d{3})*(?:\.\d+)?%?")
_NOT_A_MEASUREMENT = re.compile(r"!\[[^\]]*\]\([^)]*\)|\[[^\]]*\]\(https?://[^)]*\)|`[^`]*`")


def prose_numbers(text: str) -> list[str]:
    """Every number-looking token in the prose, with links and code spans stripped first."""
    scrubbed = _NOT_A_MEASUREMENT.sub(" ", text)
    return [match.group(0) for match in _PROSE_NUMBER.finditer(scrubbed)]


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact", type=Path, default=None)
    parser.add_argument("--claims", type=Path, default=None)
    args = parser.parse_args(argv)

    artifact_path = args.artifact or latest_interval_artifact()
    if artifact_path is None:
        print("no committed interval artifact found; run confidence_report first")
        return 2
    result = reconcile(load_claims(args.claims), json.loads(artifact_path.read_text()))
    print(json.dumps(result, indent=2))
    if result["renamed"]:
        print(f"FAIL: {len(result['renamed'])} claim(s) name a field the artifact no longer has")
        return 1
    if result["unresolved"]:
        print(f"OUTSTANDING: {len(result['unresolved'])} claim(s) resolve to no committed field")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())


# Measurement-shaped. Small bare integers are structural facts ("two groups", "four models"), not
# measurements, so they stay out.
#
# ``\d+\.\d+`` is load-bearing, and its absence was a real defect. The rule was inherited verbatim
# from the source-prose guard, which is tuned for CODE COMMENTS -- where a measurement is normally
# written as a count or an explicit percent. Section 3 is a RESULTS section, and its dominant format
# is the bare decimal proportion. Requiring three digits before the decimal point meant every
# accuracy in the head-to-head table was invisible: ``0.791`` is one digit and a fraction, so it
# matched no branch. The completeness check reported zero omissions on a table full of them, which
# is precisely the failure it exists to prevent.
#
# The lesson is not "add a branch". It is that inheriting a threshold is not the same as validating
# it against the text it will actually scan. ``test_the_completeness_check_sees_a_decimal_proportion``
# pins this shape specifically, so the blind spot cannot silently return.
_MEASUREMENT_SHAPED = re.compile(r"^(?:\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?%|\d{3,}(?:\.\d+)?|\d+\.\d+)$")


def _token_forms(value: Any) -> set[str]:
    """Every way a claim's value could legitimately appear in prose."""
    forms: set[str] = set()

    def add_number(number: float | int) -> None:
        as_int = int(number)
        if float(number) == as_int:
            forms.add(str(as_int))
            forms.add(f"{as_int:,}")
        # Three places matters: the head-to-head table writes proportions as ``0.963``, so stopping
        # at two meant a correctly-inventoried claim still read as unaccounted. This defect and the
        # decimal blindness in ``_MEASUREMENT_SHAPED`` concealed each other -- the classifier never
        # surfaced a three-decimal token, so nothing ever exercised the accounting side against one.
        for places in (1, 2, 3):
            forms.add(f"{number:.{places}f}")

    if isinstance(value, dict):
        for key in ("k", "n"):
            if value.get(key) is not None:
                add_number(value[key])
        if value.get("k") is not None and value.get("n"):
            rate = 100.0 * value["k"] / value["n"]
            for places in (0, 1, 2):
                forms.add(f"{rate:.{places}f}%")
                forms.add(f"{rate:.{places}f}".rstrip("0").rstrip(".") + "%")
    elif isinstance(value, (int, float)):
        add_number(value)
        rate = 100.0 * float(value)
        for places in (0, 1, 2):
            forms.add(f"{rate:.{places}f}%")
            forms.add(f"{rate:.{places}f}".rstrip("0").rstrip(".") + "%")
    return forms


def unclassified_prose_numbers(claims: dict[str, Any], text: str) -> list[str]:
    """Measurement-shaped tokens in the prose that the inventory does not account for.

    This is the completeness half of the check. Resolving the claims we happen to have listed says
    nothing about the claims we forgot to list, and a number that never enters the inventory is
    exactly the one that goes to print unbacked.
    """
    accounted: set[str] = set()
    for entry in claims["claims"]:
        accounted |= _token_forms(entry.get("manuscript_value"))
    accounted |= set(claims.get("not_a_measurement", {}))
    return sorted(
        {token for token in prose_numbers(text) if _MEASUREMENT_SHAPED.match(token) and token not in accounted}
    )
