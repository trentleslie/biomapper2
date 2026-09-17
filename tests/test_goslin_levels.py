"""Unit 2: Goslin exposes every level it can render, not just species, plus the ordered chain list.
Real pygoslin (offline, deterministic, network-free), so these are plain unit tests.
"""

from __future__ import annotations

from biomapper2.core.annotators.goslin_grammar import LipidGrammar
from biomapper2.core.annotators.goslin_lipid import GoslinLipidAnnotator


def _parse(name: str):
    return LipidGrammar().parse(name)


def test_sn_position_input_exposes_all_levels_and_ordered_chains() -> None:
    parsed = _parse("PC 16:0/18:1")
    assert parsed is not None
    assert parsed.level_names.get("SPECIES") == "PC 34:1"
    assert parsed.level_names.get("MOLECULAR_SPECIES") == "PC 16:0_18:1"
    assert parsed.level_names.get("SN_POSITION") == "PC 16:0/18:1"
    assert parsed.chains == ("16:0", "18:1")  # sn order preserved


def test_canonical_name_stays_species_for_backward_compatibility() -> None:
    # The binder still receives the species-level name; only the extra fields are new.
    parsed = _parse("PC 16:0/18:1")
    assert parsed is not None
    assert parsed.canonical_name == "PC 34:1"


def test_species_input_has_no_individual_chains() -> None:
    parsed = _parse("PC 34:1")
    assert parsed is not None
    assert parsed.level_names.get("SPECIES") == "PC 34:1"
    assert "MOLECULAR_SPECIES" not in parsed.level_names  # a sum composition does not invent chains
    assert parsed.chains == ()


def test_sphingoid_base_is_kept_as_one_chain() -> None:
    parsed = _parse("SM d18:1/16:0")
    assert parsed is not None
    assert parsed.chains == ("18:1;O2", "16:0")


def test_annotator_metadata_carries_the_new_level_fields() -> None:
    parsed = _parse("PC 16:0/18:1")
    assert parsed is not None
    meta = GoslinLipidAnnotator._metadata(parsed, enrichment_fired=False)
    assert meta["goslin_input_level"] == parsed.level
    assert meta["goslin_level_names"]["SN_POSITION"] == "PC 16:0/18:1"
    assert meta["goslin_chains"] == ["16:0", "18:1"]
