"""Unit 5 — KG-independent link certificate (offline; InChIKey strings, no PubChem calls).

The co-derivation control is the load-bearing test: it proves the certificate refuses a link that
the CIRCULAR (KG-node) path would wrongly certify.
"""

from __future__ import annotations

from studies.external_benchmarks.scorers.link_certificate import (
    certificate_key,
    certify_link,
)

GLUCOSE = "WQZGKKKJIJFFOK-GASJEMHNSA-N"
GLUCOSE_STEREOISOMER = "WQZGKKKJIJFFOK-VFRWLCBQSA-N"  # same connectivity, different stereo layer
WRONG_MOLECULE = "ZZZZZZZZZZZZZZ-YYYYYYYYYY-N"  # different connectivity (block 1)


def test_certified_when_independent_structures_agree():
    cert = certify_link(GLUCOSE, GLUCOSE)
    assert cert.verdict == "certified" and cert.stereo_checked is True


def test_refuted_on_connectivity_disagreement():
    cert = certify_link(GLUCOSE, WRONG_MOLECULE)
    assert cert.verdict == "refuted" and "connectivity" in cert.reason


def test_refuted_on_stereoisomer():
    cert = certify_link(GLUCOSE, GLUCOSE_STEREOISOMER)
    assert cert.verdict == "refuted" and cert.stereo_checked is True and "stereo" in cert.reason


def test_co_derivation_positive_control():
    # Two cohort names both mis-resolve (via the KG) to glucose's node → shared CURIE → shared
    # KG-InChIKey (GLUCOSE). One is really a different molecule (WRONG_MOLECULE).
    kg_node_inchikey = GLUCOSE  # what the circular path would read for BOTH sides
    # Independent path (correct): cohort structure from PubChem is the TRUE molecule → refuted.
    correct = certify_link(GLUCOSE, WRONG_MOLECULE)
    assert correct.verdict == "refuted", "independent oracle must catch the wrong-molecule link"
    # Circular path (what we must NOT do): read the KG node for the cohort side → wrongly certified.
    circular = certify_link(GLUCOSE, kg_node_inchikey)
    assert circular.verdict == "certified", (
        "control has teeth: the ONLY thing preventing a false certify is passing the "
        "independent structure, not the KG node"
    )


def test_refused_when_cohort_has_no_independent_structure():
    # BLSA/LLFS endpoint (no vendor structure id) → cohort key None → refused, not certified.
    cert = certify_link(GLUCOSE, None)
    assert cert.verdict == "refused" and "cohort" in cert.reason


def test_refused_on_pubchem_lookup_failure_not_crash():
    # independent_inchikey is fail-soft (None on network error) → refusal, never an exception.
    cert = certify_link(None, GLUCOSE)
    assert cert.verdict == "refused" and "NECS" in cert.reason


def test_first_block_only_certifies_at_connectivity():
    # PubChem resolver's current granularity: first block only → connectivity match, stereo flagged.
    cert = certify_link("WQZGKKKJIJFFOK", "WQZGKKKJIJFFOK")
    assert cert.verdict == "certified" and cert.stereo_checked is False


def test_certificate_key_parsing():
    full = certificate_key(GLUCOSE)
    assert full is not None and full.connectivity == "WQZGKKKJIJFFOK" and full.stereo8 == "GASJEMHN"
    assert certificate_key("WQZGKKKJIJFFOK").stereo8 is None  # first-block-only
    assert certificate_key("") is None and certificate_key(None) is None
