"""Invariant: no measured figure may be restated in a comment or docstring.

Why this test exists
--------------------
The resolver-correctness change was halted three times in review for the same defect, in a
different file each time. The pattern was always identical: prose justified a decision with a
live measurement ("577 commits", "2,400 candidate rows", "18/45"), a reviewer checked one, and it
had either drifted from the artifact or was never sourced at all. Fixing the cited instance each
round did nothing, because the next round's narrative introduced fresh numbers.

So the rule is structural rather than editorial: **comments name the artifact field that carries a
number; they never restate its value.** A reader who wants the value opens
``studies/analysis/results/off_category_audit_*.json`` or reruns
``studies/analysis/off_category_audit.py``. That way a number can only be stale in one place, and
that place regenerates.

This test enforces it mechanically, so the defect cannot recur without turning the suite red.

What counts as a measured figure
--------------------------------
A number that could plausibly be a count or a rate: three or more digits, a thousands-separated
number, or any percentage. Small integers ("two shapes", "12 descendants") are structural facts
asserted elsewhere in code, not measurements, and are allowed. Identifiers are stripped before the
scan, since ``CHEBI:16856`` is a name rather than a quantity.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# The files this change owns. Listed explicitly rather than derived from git: the guard should hold
# for these files permanently, not just while they happen to appear in a diff.
GUARDED_FILES = (
    "src/biomapper2/config.py",
    "src/biomapper2/core/resolver.py",
    "src/biomapper2/core/structure_resolver.py",
    "src/biomapper2/core/annotation_engine.py",
    "src/biomapper2/core/annotators/base.py",
    "src/biomapper2/core/annotators/kestrel_hybrid.py",
    "src/biomapper2/core/annotators/kestrel_text.py",
    "src/biomapper2/core/annotators/kestrel_vector.py",
    "src/biomapper2/core/annotators/metabolomics_workbench.py",
    "src/biomapper2/core/annotators/goslin_lipid.py",
    "studies/analysis/__init__.py",
    "studies/analysis/off_category_audit.py",
    "studies/shared_gold_set/labeler.py",
    "tests/test_kestrel_hybrid_category.py",
    "tests/test_off_category_audit.py",
    "tests/test_annotation_engine_category.py",
    "tests/test_resolver_source_weighting.py",
    "tests/test_structure_resolver.py",
    "tests/test_annotation_engine_canonical.py",
    # The evidence-base files. These exist to put measured numbers in artifacts, so a measured
    # number restated in their own prose would be the defect they were written to remove.
    #
    # Deliberately NOT guarded: studies/external_benchmarks/config.py, which carries an external
    # baseline in a comment that is explicitly flagged needs-verification alongside a null registry
    # value. Guarding it would turn the suite red for a comment doing exactly the right thing.
    # Also not guarded: build_section3_claims.py, whose CODE is a list of manuscript values -- the
    # guard scans prose, not code, but the file's whole purpose is to hold those values.
    "studies/external_benchmarks/stats.py",
    "studies/external_benchmarks/confidence_report.py",
    "studies/external_benchmarks/reconcile_section3.py",
    "studies/external_benchmarks/request_timeout.py",
    "studies/external_benchmarks/tests/test_stats.py",
    "studies/external_benchmarks/tests/test_confidence_report.py",
    "studies/external_benchmarks/tests/test_reconcile_section3.py",
    "studies/external_benchmarks/tests/test_row_index_gold_guard.py",
    "src/biomapper2/utils.py",
    "tests/test_kestrel_client_hardening.py",
)

# Identifiers, not quantities. Stripped before scanning so a CURIE's digits are not read as a count.
_IDENTIFIER_PATTERNS = (
    re.compile(r"``[^`]*``"),  # inline code spans hold code, not prose
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),  # ISO dates ("verified live 2026-06-18")
    re.compile(r"\b[A-Za-z][A-Za-z0-9._]*:[A-Za-z0-9_.\-]+"),  # CURIEs: CHEBI:16856, OBO:NCIT_C103149
    re.compile(r"\bhttps?://\S+"),  # URLs
    re.compile(r"\b[A-Z]{10,}-[A-Z]{5,}-[A-Z]\b"),  # InChIKeys
    re.compile(r"\b[0-9a-f]{7,40}\b"),  # git SHAs
    re.compile(r"\bv?\d+\.\d+\.\d+\b"),  # semantic versions (biolink 4.2.5)
    re.compile(r"\bPR #\d+\b"),  # PR references
    re.compile(r"\b[a-z_]+\.py:\d+\b"),  # file:line references
    re.compile(r"\b:\d+\b"),  # bare line refs (``:229``)
)

# Exact tokens that are structural constants or protocol facts, never measurements.
_ALLOWED_TOKENS = frozenset(
    {
        "100",  # percentage arithmetic / "100%" of a structural set
        "200",
        "401",
        "404",  # HTTP status codes
        "120",  # ruff line-length
    }
)

_MEASURED_FIGURE = re.compile(
    r"""
    \b\d{1,3}(?:,\d{3})+\b        # thousands-separated: 1,138  12,605
  | \b\d+(?:\.\d+)?\s?%           # any percentage: 9.1%  93.8%
  | \b\d{3,}(?:\.\d+)?\b          # three or more digits: 577  2400  8814
    """,
    re.VERBOSE,
)


def _prose_segments(path: Path) -> list[tuple[int, str]]:
    """Return ``(lineno, text)`` for every comment and every docstring in the file.

    Uses ``tokenize`` rather than a line regex so that a number living in *code*
    (``HYBRID_SCAN_NAMES = 120``) is never mistaken for a number living in prose. Code is allowed to
    contain values; that is where values belong.
    """
    source = path.read_text()
    segments: list[tuple[int, str]] = []

    # Comments: tokenize is exact.
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT:
            segments.append((tok.start[0], tok.string))

    # Docstrings: ast.get_docstring is exact. A token-level heuristic is NOT -- a dict value
    # (``{"gold_chebi": "1234"}``) follows a ``:`` just as a docstring follows a ``def ...:``, so a
    # heuristic flags string literals in ordinary code. That false positive is not hypothetical; it
    # fired on this suite's own fixtures.
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                lineno = 1 if isinstance(node, ast.Module) else node.body[0].lineno
                segments.append((lineno, doc))
    return segments


def _violations(path: Path) -> list[str]:
    found: list[str] = []
    for lineno, text in _prose_segments(path):
        scrubbed = text
        for pattern in _IDENTIFIER_PATTERNS:
            scrubbed = pattern.sub(" ", scrubbed)
        for match in _MEASURED_FIGURE.finditer(scrubbed):
            token = match.group(0).strip()
            if token in _ALLOWED_TOKENS:
                continue
            line = text.splitlines()[0][:100] if text else ""
            label = path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path.name
            found.append(f"{label}:{lineno}: {token!r} in prose -- {line}")
    return found


@pytest.mark.parametrize("relative_path", GUARDED_FILES)
def test_no_measured_figure_is_restated_in_prose(relative_path: str) -> None:
    """A comment or docstring may NAME an artifact field; it may not restate the value.

    If this fails, do not delete the number and move on -- move it. The value belongs in
    ``studies/analysis/off_category_audit.py`` (and therefore in its committed artifact), and the
    prose should point at the field that now carries it.
    """
    path = REPO_ROOT / relative_path
    if not path.exists():  # pragma: no cover - guards a rename
        pytest.skip(f"{relative_path} not present")
    violations = _violations(path)
    assert not violations, (
        "measured figures found restated in prose:\n  "
        + "\n  ".join(violations)
        + "\n\nComments must name the artifact field that carries the number, never its value. "
        "See studies/analysis/off_category_audit.py and its committed artifact."
    )


def test_the_guard_actually_detects_a_restated_figure(tmp_path: Path) -> None:
    """Positive control: the guard is worthless if it cannot fail.

    Mirrors exactly the defect that halted review three times -- a real count restated in prose.
    """
    sample = tmp_path / "sample.py"
    sample.write_text(
        '"""A docstring citing 1,138 refusals and a 9.1% rate."""\n'
        "# and a comment citing 577 commits\n"
        "BATCH = 1000  # a value in CODE is fine; only prose is guarded\n"
    )
    found = _violations(sample)
    tokens = {v.split("'")[1] for v in found}
    assert tokens == {"1,138", "9.1%", "577"}, found


def test_the_guard_does_not_flag_identifiers_or_code(tmp_path: Path) -> None:
    """Negative control: CURIEs, versions, SHAs and in-code values must not trip it."""
    sample = tmp_path / "sample.py"
    sample.write_text(
        '"""Cites CHEBI:16856, OBO:NCIT_C103149, biolink 4.2.5, sha d059564 and file.py:229."""\n'
        "LIMIT = 2400  # structural constant, not prose\n"
    )
    assert _violations(sample) == []


def test_the_guard_does_not_treat_dict_values_as_docstrings(tmp_path: Path) -> None:
    """Regression: a token-level docstring heuristic flagged {"k": "1234"} as prose.

    A dict value follows a : exactly as a docstring follows def ...:, so only real AST
    docstrings count. This fired on this suite's own fixtures before the switch to ast.
    """
    sample = tmp_path / "sample.py"
    sample.write_text('row = {"gold_chebi": "1234", "gold_pubchem": "999999"}\n')
    assert _violations(sample) == []
