"""Unit 2 — the certificate's KG-independence is ENFORCED at runtime, not asserted in a docstring.

Fail-closed provenance guard: a KG-derived structure (source ``"kg"``) can never be certified off,
and in strict mode an untagged block also refuses. The removed "same source+input" clause must NOT
force-refuse a legitimate same-source cross-cohort agreement. Pure/offline — keys passed directly.
"""

from __future__ import annotations

from studies.external_benchmarks.scorers.cross_cohort_overlap import Link
from studies.external_benchmarks.scorers.independent_inchikey import ProvidedBlock
from studies.external_benchmarks.scorers.independent_link_certificate_overlap import certify_links_tagged
from studies.external_benchmarks.scorers.link_certificate import certify_link

_IK = "FHQVHHIBKUMWTI-OTMQOFQ-N"  # same structure on both sides


def test_kg_tagged_side_refuses_even_when_blocks_match():
    # Positive control: identical structures would certify, but a KG-derived side is not independent.
    cert = certify_link(_IK, _IK, necs_source="kg", cohort_source="provided-hmdb")
    assert cert.verdict == "refused"


def test_untagged_side_refuses_in_strict_mode():
    cert = certify_link(_IK, _IK, necs_source="provided-hmdb", cohort_source=None, require_tags=True)
    assert cert.verdict == "refused"


def test_tagged_independent_sides_certify():
    cert = certify_link(_IK, _IK, necs_source="provided-hmdb", cohort_source="provided-pubchem", require_tags=True)
    assert cert.verdict == "certified"


def test_legitimate_same_source_still_certifies():
    # Two cohorts both carrying an HMDB id for the same metabolite is a VALID certification,
    # not correlated error — the old same-source refusal clause was removed.
    cert = certify_link(_IK, _IK, necs_source="provided-hmdb", cohort_source="provided-hmdb", require_tags=True)
    assert cert.verdict == "certified"


def test_legacy_untagged_non_strict_preserves_behavior():
    assert certify_link(_IK, _IK).verdict == "certified"


def _link(a, b):
    return Link(a_name=a, b_name=b, shared=frozenset())


def test_certify_links_tagged_counts_and_canary():
    links = [_link("necs_glucose", "coh_glucose"), _link("necs_x", "coh_missing")]
    a = {"necs_glucose": ProvidedBlock(_IK, "provided-hmdb", "success"),
         "necs_x": ProvidedBlock("AAAAAAAAAAAAAA", "provided-hmdb", "success")}
    b = {"coh_glucose": ProvidedBlock(_IK, "provided-pubchem", "success")}  # coh_missing absent -> untagged side
    overlap, untagged = certify_links_tagged(links, a, b)
    assert overlap.certified == 1  # the glucose link certifies
    assert overlap.refused == 1  # the missing-entry link refuses (fail-closed)
    assert untagged == 1  # the absent b-side is counted for the canary


def test_certify_links_tagged_kg_block_refused():
    links = [_link("n", "c")]
    a = {"n": ProvidedBlock(_IK, "kg", "success")}  # KG-derived -> must not certify
    b = {"c": ProvidedBlock(_IK, "provided-pubchem", "success")}
    overlap, _ = certify_links_tagged(links, a, b)
    assert overlap.certified == 0 and overlap.refused == 1
