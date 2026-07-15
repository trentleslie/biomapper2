"""MetaboliteAnnotator name-hit registry entries + anti-trivial guards (offline)."""

from __future__ import annotations

import pytest

from studies.external_benchmarks.config import (
    METABOLITEANNOTATOR_ACCESSIONS,
    METABOLITEANNOTATOR_COMPETITORS,
    METABOLITEANNOTATOR_NEG,
    METABOLITEANNOTATOR_POS,
    NAME_HIT_REGISTRY,
    NEEDS_FETCHING_SENTINEL,
    NameHitDatasetConfig,
    RunnableConfig,
)
from studies.external_benchmarks.validate import citation_spot_check


def test_registry_has_both_modes_one_number_each():
    # One dataset per ion mode -> exactly one headline hit-rate each (matches the paper's two
    # reported numbers: 93.2% pos, 93.5% neg).
    assert set(NAME_HIT_REGISTRY) == {METABOLITEANNOTATOR_POS.key, METABOLITEANNOTATOR_NEG.key}
    assert METABOLITEANNOTATOR_POS.mode == "positive"
    assert METABOLITEANNOTATOR_NEG.mode == "negative"


def test_configs_satisfy_runnable_protocol():
    # runner.run_all consumes any RunnableConfig structurally; both mode configs must qualify.
    assert isinstance(METABOLITEANNOTATOR_POS, RunnableConfig)
    assert isinstance(METABOLITEANNOTATOR_NEG, RunnableConfig)
    assert METABOLITEANNOTATOR_POS.input_type == "name"
    assert METABOLITEANNOTATOR_POS.name_column == "metabolite_identification"


def test_six_accessions_resolved_to_real_mtbls_ids():
    # RESOLVED 2026-07-14 — the six MTBLS accessions are from the paper's Methods + Table 1
    # (PMID 41691569). No placeholder should remain, and the status flips to "resolved".
    assert len(METABOLITEANNOTATOR_ACCESSIONS) == 6
    assert set(METABOLITEANNOTATOR_ACCESSIONS) == {
        "MTBLS12997", "MTBLS13105", "MTBLS12764", "MTBLS11733", "MTBLS12636", "MTBLS13039"
    }
    assert not any(a.startswith(NEEDS_FETCHING_SENTINEL) for a in METABOLITEANNOTATOR_ACCESSIONS)
    assert METABOLITEANNOTATOR_POS.accessions_status == "resolved"
    assert METABOLITEANNOTATOR_NEG.accessions_status == "resolved"
    assert METABOLITEANNOTATOR_POS.accessions == METABOLITEANNOTATOR_ACCESSIONS


def test_anti_trivial_gold_id_column_not_name_column():
    with pytest.raises(ValueError, match="anti-trivial"):
        NameHitDatasetConfig(
            key="bad-gold-is-query",
            arm="metabolite",
            entity_type="metabolite",
            mode="positive",
            name_column="metabolite_identification",
            gold_id_column="metabolite_identification",  # gold == query -> trivial self-hit
            gold_smiles_column="gold_smiles",
            target_vocabs=("CHEBI",),
            accessions=METABOLITEANNOTATOR_ACCESSIONS,
            source_url_template="",
            license="x",
        )


def test_anti_trivial_requires_a_gold_id_column():
    with pytest.raises(ValueError, match="anti-trivial"):
        NameHitDatasetConfig(
            key="bad-no-gold",
            arm="metabolite",
            entity_type="metabolite",
            mode="positive",
            name_column="metabolite_identification",
            gold_id_column="",  # no held-out gold -> nothing to adjudicate a hit against
            gold_smiles_column="",
            target_vocabs=("CHEBI",),
            accessions=METABOLITEANNOTATOR_ACCESSIONS,
            source_url_template="",
            license="x",
        )


def test_competitors_are_citeable_and_unfabricated():
    # MetaboAnalyst 6.0 + metaboliteIDmapping baselines AND the MetaboliteAnnotator headline are
    # transcribed with value=None until verified against the source table (Metabolon-96.5% scar).
    tools = {c.tool for c in METABOLITEANNOTATOR_COMPETITORS}
    assert "MetaboliteAnnotator" in tools
    assert "MetaboAnalyst 6.0" in tools
    assert "metaboliteIDmapping" in tools
    assert all(c.value is None for c in METABOLITEANNOTATOR_COMPETITORS)
    # every entry carries DOI + table_ref, so citation_spot_check passes
    assert citation_spot_check(METABOLITEANNOTATOR_COMPETITORS).passed
