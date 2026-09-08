"""The species-level lipid predicate that drives the honest refused-lipid sub-label."""

from __future__ import annotations

from studies.external_benchmarks.certificate_adjudication import is_species_level_lipid


def test_flags_sum_composition_lipids():
    for n in ["PC(34:1)", "TG(16:0_18:1_18:2)", "1-stearoyl-2-oleoyl-GPE (18:0/18:1)",
              "sphingomyelin (d18:2/16:0)", "nervonoylcarnitine (c24:1)*"]:
        assert is_species_level_lipid(n), n


def test_does_not_flag_small_molecules():
    for n in ["glucose", "quinolinate", "4-hydroxyphenylpyruvate", "cortisol", "biliverdin", ""]:
        assert not is_species_level_lipid(n), n


def test_none_safe():
    assert is_species_level_lipid(None) is False
