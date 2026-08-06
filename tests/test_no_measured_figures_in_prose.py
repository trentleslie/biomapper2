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

# The guarded set is DERIVED FROM A GLOB, not hand-maintained. That is the whole point.
#
# It used to be an explicit include-list, and the failure mode was silent: this guard reported a
# screen of green while scanning none of the files in the change it was supposedly guarding, because
# nobody had thought to add them. An enforcement mechanism that passes without checking is worse
# than none, because it manufactures confidence. Deriving from a glob means the default for a new
# file is COVERED, and an exemption has to be argued for in ``SKIPPED`` below.
GUARDED_TREES = (
    "src/biomapper2/core",
    "studies/analysis",
    "studies/shared_gold_set",
    "tests",
)

# KNOWN GAP, stated rather than left to be discovered: ``studies/external_benchmarks`` is NOT
# guarded. It is the largest body of measurement-bearing code in the repo outside this standard, and
# it does not pass today -- run ``_violations`` over the tree to size it before adding it here.
# Bringing it in is a real cleanup, not a one-line tree addition, and doing it by burying the tree in
# SKIPPED entries would hollow out the meta-tests below. It is named here so the guard's coverage is
# legible; silence would recreate the false confidence this rewrite exists to remove.
#
# One case in that tree wants an exemption rather than a rewrite when it happens:
# ``studies/external_benchmarks/config.py`` restates competitor baseline figures inside a comment
# that explicitly marks them UNVERIFIED and refuses to treat them as fact. That comment is the
# needs-verification marker doing its job, not a drifted measurement.
UNGUARDED_TREES_KNOWN = ("studies/external_benchmarks",)

# Files outside the guarded trees that the standard still covers. Kept short on purpose: anything
# that needs to be listed here individually is a hint the tree list is wrong.
GUARDED_EXTRA_FILES = (
    "src/biomapper2/config.py",
    "src/biomapper2/mapper.py",
    "src/biomapper2/models.py",
)

# Documented exemptions. A skip-list rather than an include-list, so the guard FAILS CLOSED: adding
# a file never silently escapes the standard, and every escape carries a reason a reviewer can
# check. ``test_no_skip_outlives_its_reason`` deletes the entry's cover the moment it stops being
# needed, so this list cannot quietly accumulate.
#
# Every reason below is the same class: the scrubber cannot tell a vocabulary FORMAT EXAMPLE or an
# HTTP status code from a measurement. None of them is a figure that could drift out of sync with an
# artifact, which is what the standard exists to prevent.
SKIPPED: dict[str, str] = {
    "src/biomapper2/core/normalizer/validators.py": "docstrings quote vocabulary format examples (LOINC, RXCUI)",
    "src/biomapper2/core/normalizer/cleaners.py": "docstring quotes a zipcode format example",
    "src/biomapper2/core/gene_symbol_resolver.py": "docstring quotes an accession format example",
    "tests/test_api.py": "names an HTTP status code",
    "tests/test_api_unit.py": "names HTTP status codes and a request-size limit asserted in code alongside",
    "tests/test_dataset_analysis.py": "names a percentage that is the fixture's own constructed value",
    "tests/test_dataset_kg_mapping.py": "names live-suite counts; belongs to the integration arm, not a figure",
    "tests/test_gold_set_labeler.py": "quotes a CURIE-set literal that appears verbatim in the assertion",
    "tests/test_goslin_grammar.py": "quotes a monoisotopic mass, a physical constant rather than a measurement",
    "tests/test_kestrel_discovery.py": "spells out a fixture's own composition next to the fixture",
    "tests/test_no_measured_figures_in_prose.py": "this guard's own positive-control fixtures and rationale",
    "tests/test_visualizer.py": "names percentages that are the fixture's constructed inputs",
}


def _discover_guarded_files() -> tuple[str, ...]:
    """Every source file under the guarded trees, minus documented exemptions.

    Derived, never listed. A file added to a guarded tree is guarded from the moment it lands.
    """
    found: set[str] = set()
    for tree in GUARDED_TREES:
        root = REPO_ROOT / tree
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            found.add(str(path.relative_to(REPO_ROOT)))
    found.update(GUARDED_EXTRA_FILES)
    return tuple(sorted(found - set(SKIPPED)))


GUARDED_FILES = _discover_guarded_files()

# Identifiers, not quantities. Stripped before scanning so a CURIE's digits are not read as a count.
_IDENTIFIER_PATTERNS = (
    re.compile(r"``[^`]*``"),                                   # inline code spans hold code, not prose
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),                       # ISO dates ("verified live 2026-06-18")
    re.compile(r"\b[A-Za-z][A-Za-z0-9._]*:[A-Za-z0-9_.\-]+"),  # CURIEs: CHEBI:16856, OBO:NCIT_C103149
    re.compile(r"\bhttps?://\S+"),                              # URLs
    re.compile(r"\b[A-Z]{10,}-[A-Z]{5,}-[A-Z]\b"),              # InChIKeys
    re.compile(r"\b[0-9a-f]{7,40}\b"),                          # git SHAs
    re.compile(r"\bv?\d+\.\d+\.\d+\b"),                         # semantic versions (biolink 4.2.5)
    re.compile(r"\bPR #\d+\b"),                                 # PR references
    re.compile(r"\b[a-z_]+\.py:\d+\b"),                         # file:line references
    re.compile(r"\b:\d+\b"),                                    # bare line refs (``:229``)
    re.compile(r"\b0o?[0-7]{3,4}\b"),                           # Unix file modes (0700, 0644, 0o700)
)

# Exact tokens that are structural constants or protocol facts, never measurements.
_ALLOWED_TOKENS = frozenset(
    {
        "100",  # percentage arithmetic / "100%" of a structural set
        "200",
        "301",
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


def test_no_source_file_under_a_guarded_tree_escapes_the_check() -> None:
    """The meta-test. Without it, the next directory reorganisation silently reopens the hole.

    Every ``.py`` under a guarded tree must be either checked or explicitly exempted. Nothing may
    simply fall out of the set.
    """
    checked = set(GUARDED_FILES) | set(SKIPPED)
    unaccounted = []
    for tree in GUARDED_TREES:
        root = REPO_ROOT / tree
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            if "__pycache__" in path.parts:
                continue
            relative = str(path.relative_to(REPO_ROOT))
            if relative not in checked:
                unaccounted.append(relative)
    assert not unaccounted, (
        "these files live under a guarded tree but are neither checked nor exempted:\n  "
        + "\n  ".join(sorted(unaccounted))
    )


def test_the_guarded_set_is_not_trivially_small() -> None:
    """A glob that matched nothing would make every parametrized case vacuously green -- the exact
    failure this rewrite exists to remove, in a new disguise."""
    assert len(GUARDED_FILES) > len(SKIPPED)
    for tree in GUARDED_TREES:
        assert any(f.startswith(tree) for f in GUARDED_FILES), f"no file guarded under {tree}"


def test_no_skip_outlives_its_reason() -> None:
    """An exemption that no longer exempts anything is a hole with a comment on it.

    If this fails, the fix is to DELETE the entry, not to loosen the guard: the file now passes.
    """
    stale = []
    for relative, reason in SKIPPED.items():
        path = REPO_ROOT / relative
        assert reason.strip(), f"{relative} is exempted without a reason"
        if not path.exists():
            stale.append(f"{relative} (file is gone)")
        elif not _violations(path):
            stale.append(f"{relative} (no longer violates; remove the exemption)")
    assert not stale, "stale exemptions:\n  " + "\n  ".join(stale)


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


def test_the_guard_does_not_flag_file_modes_or_protocol_status_codes(tmp_path: Path) -> None:
    """Negative control: a Unix file mode and an HTTP status code are not measurements.

    Both classes arrived with the cache-redaction change and are the same shape as the exemptions
    already documented in ``SKIPPED``. They are fixed in the SCRUBBER rather than by skip-listing the
    two files, because a file-level exemption would retire the whole file from the standard to
    silence one token -- which is how an include-list-shaped hole reopens under a different name. A
    leading-zero octal is never a count, and a redirect code is a protocol fact with no artifact to
    drift against.
    """
    sample = tmp_path / "sample.py"
    sample.write_text(
        '"""Treats the directory as 0700 and the files as 0644."""\n'
        "# retiring the internal host with a 301 to the public one strips the credential\n"
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


def test_known_unguarded_trees_are_real_and_still_unguarded() -> None:
    """``UNGUARDED_TREES_KNOWN`` documents a gap; unenforced, it is just a comment.

    Two ways the entry rots, both caught here: the tree stops existing (stale entry naming a
    directory nobody has), or the tree quietly becomes guarded (the entry now hides nothing and its
    presence misleads a reviewer into thinking coverage is narrower than it is). Either way the list
    must be edited rather than left to drift -- the same failure mode as the include-list this
    rewrite replaced.
    """
    for tree in UNGUARDED_TREES_KNOWN:
        path = REPO_ROOT / tree
        assert path.is_dir(), f"UNGUARDED_TREES_KNOWN names {tree!r}, which does not exist"
        assert tree not in GUARDED_TREES, (
            f"{tree!r} is listed as a known gap but is now guarded; delete the entry so the "
            "documented gap matches reality"
        )
        assert any(path.rglob("*.py")), f"UNGUARDED_TREES_KNOWN names {tree!r}, which holds no Python"
