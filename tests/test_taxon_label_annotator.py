"""Tests for the PR1 TaxonLabelAnnotator and its engine wiring (16S plan U5).

Kestrel is always faked (no network). The NCBI snapshot is the real packaged one: the guard's whole point
is that lineage facts come from it, so faking it would test nothing. The Prevotellaceae/Proteus/Homo
sapiens rows come from the live-recorded fixture (tests/fixtures/organism_taxon_hybrid_search_recorded.json).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest

from biomapper2 import config
from biomapper2.core.annotation_engine import AnnotationEngine
from biomapper2.core.annotators import taxon_label as tl
from biomapper2.core.annotators.base import (
    AVAILABILITY_NO_MATCH,
    AVAILABILITY_NOT_QUERIED,
    AVAILABILITY_UNAVAILABLE,
    AVAILABILITY_VOTED,
)
from biomapper2.core.annotators.taxon_label import TaxonLabelAnnotator
from biomapper2.core.fault_tracking import end_dataset_fault_recording, start_dataset_fault_recording

TAXON = "biolink:OrganismTaxon"
_FIXTURE = Path(__file__).parent / "fixtures" / "organism_taxon_hybrid_search_recorded.json"
_RECORDED = json.loads(_FIXTURE.read_text())["response"]


def _row(taxid: int | str, name: str, score: float, *, prefix: str = "NCBITaxon", synonyms=None) -> dict:
    return {
        "id": f"{prefix}:{taxid}",
        "name": name,
        "score": score,
        "synonyms": synonyms or [],
        "categories": [TAXON],
        "prefixes": [prefix],
    }


class FakeKestrel:
    """Records every hybrid-search call; answers from a {query: rows} table (missing -> [])."""

    def __init__(self, table: dict[str, list[dict]] | None = None, error: Exception | None = None):
        self.table = table or {}
        self.error = error
        self.calls: list[list[str]] = []

    def __call__(self, search_text, category, prefixes, limit=10):
        terms = [search_text] if isinstance(search_text, str) else list(search_text)
        self.calls.append(terms)
        assert category == TAXON
        if self.error is not None:
            raise self.error
        return {t: list(self.table.get(t, [])) for t in terms}


@pytest.fixture
def fake(monkeypatch):
    kestrel = FakeKestrel(
        {
            "Dorea": [_row(189330, "Dorea", 3.4), _row(88431, "Dorea longicatena", 1.4)],
            "Prevotellaceae": _RECORDED["Prevotellaceae"],
            "Proteus": [_row(210425, "Proteus", 5.0), _row(583, "Proteus", 2.0)],
            "Homo sapiens": _RECORDED["Homo sapiens"],
            "Bacillus": [_row(55087, "Bacillus", 4.0), _row(1386, "Bacillus", 3.0)],
            "Bacilus": [_row(55087, "Bacillus", 0.9)],
            "Firmicutes": _RECORDED["Firmicutes"],
            "Actinobacteria": [_row(201174, "Actinomycetota", 3.0, synonyms=["Actinobacteria"]), _row(1760, "x", 2.0)],
        }
    )
    monkeypatch.setattr(TaxonLabelAnnotator, "_kestrel_hybrid_search", staticmethod(kestrel))
    return kestrel


def _annotate_one(label: str):
    ann = TaxonLabelAnnotator()
    entity = {"name": label}
    cache = ann.build_availability_cache(entity, "name")
    votes = ann.get_annotations(entity, "name", TAXON, cache=cache)
    return (
        votes,
        ann.get_availability(entity, "name", cache=cache)[ann.slug],
        ann.get_source(entity, "name", cache=cache)[ann.slug],
        cache,
    )


def _voted_ids(votes) -> list[str]:
    return [f"{vocab}:{local}" for vocab, ids in votes.get(TaxonLabelAnnotator.slug, {}).items() for local in ids]


# ---------------------------------------------------------------------------------------- happy path


def test_gg_genus_label_searches_the_genus_and_votes_ncbitaxon(fake):
    votes, availability, source, _ = _annotate_one(
        "k__Bacteria;p__Firmicutes;c__Clostridia;o__Clostridiales;f__Lachnospiraceae;g__Dorea"
    )
    assert fake.calls == [["Dorea"]]
    assert _voted_ids(votes) == ["NCBITaxon:189330"]
    assert (availability, source) == (AVAILABILITY_VOTED, "exact")


def test_family_label_picks_ncbitaxon_over_higher_scoring_umls(fake):
    votes, _, source, _ = _annotate_one(
        "k__Bacteria;p__Bacteroidetes;c__Bacteroidia;o__Bacteroidales;f__Prevotellaceae"
    )
    assert _voted_ids(votes) == ["NCBITaxon:171552"]
    assert source == "exact"


def test_legacy_phylum_name_votes_the_phylum_via_synonym(fake):
    votes, _, source, _ = _annotate_one("D_0__Bacteria;D_1__Firmicutes;D_5__uncultured")
    assert _voted_ids(votes) == ["NCBITaxon:1239"]
    assert source == "synonym"


def test_vote_metadata_records_score_and_route(fake):
    votes, *_ = _annotate_one("k__Bacteria;g__Dorea")
    assert votes[TaxonLabelAnnotator.slug]["NCBITaxon"]["189330"] == {
        "score": 3.4,
        "resolved_via": "taxon_label:exact",
    }


# ---------------------------------------------------------------------------------------- edge cases


def test_proteus_label_skips_the_salamander_and_votes_the_bacterium(fake):
    votes, *_ = _annotate_one("k__Bacteria;p__Proteobacteria;f__Enterobacteriaceae;g__Proteus")
    assert _voted_ids(votes) == ["NCBITaxon:583"]


def test_bare_homo_sapiens_is_delegated_and_votes_its_node(fake):
    votes, availability, source, _ = _annotate_one("Homo sapiens")
    assert _voted_ids(votes) == ["NCBITaxon:9606"]
    assert (availability, source) == (AVAILABILITY_VOTED, "delegated")


def test_bare_bacillus_never_votes_the_stick_insect(fake):
    votes, *_ = _annotate_one("Bacillus")
    assert _voted_ids(votes) == ["NCBITaxon:1386"]


def test_misspelled_bare_name_whose_hit_is_a_homonym_non_prokaryote_casts_no_vote(fake):
    votes, availability, source, _ = _annotate_one("Bacilus")
    assert _voted_ids(votes) == []
    assert (availability, source) == (AVAILABILITY_NO_MATCH, "abstain:no_match")


def test_rank_must_match_the_label_rank(fake):
    # SILVA padded repeat dropped -> the query is the PHYLUM Actinobacteria (hint confirmed) -> the phylum node.
    votes, *_ = _annotate_one("D_0__Bacteria;D_1__Actinobacteria;D_2__Actinobacteria")
    assert _voted_ids(votes) == ["NCBITaxon:201174"]
    # GG class "Actinobacteria": the higher-scoring phylum row is not eligible; the class node is,
    # through its NCBI synonym in the snapshot, even though Kestrel's row name does not match.
    votes, _, source, _ = _annotate_one("k__Bacteria;c__Actinobacteria")
    assert _voted_ids(votes) == ["NCBITaxon:1760"]
    assert source == "synonym"


def test_clone_code_label_casts_no_vote_and_makes_no_search_call(fake):
    votes, availability, source, _ = _annotate_one("k__Bacteria;p__Bacteroidetes;o__B110;f__;g__")
    assert _voted_ids(votes) == []
    assert fake.calls == []
    assert (availability, source) == (AVAILABILITY_NOT_QUERIED, "abstain:clone_code")


@pytest.mark.parametrize(
    "label, reason",
    [
        ("sk__Eukaryota;k__Metazoa", "abstain:eukaryote"),
        ("k__Bacteria;p__Cyanobacteria;c__Chloroplast", "abstain:host_or_organelle"),
        ("k__;p__;c__", "abstain:empty"),
    ],
)
def test_host_organelle_and_empty_labels_make_no_search_call(fake, label, reason):
    votes, _, source, _ = _annotate_one(label)
    assert _voted_ids(votes) == []
    assert fake.calls == []
    assert source == reason


def test_superset_label_votes_the_base_genus_with_route_superset(fake):
    fake.table["Prevotella"] = [_row(838, "Prevotella", 3.0)]
    votes, _, source, _ = _annotate_one("D_0__Bacteria;D_4__Prevotellaceae;D_5__Prevotella_9")
    assert _voted_ids(votes) == ["NCBITaxon:838"]
    assert source == "superset"


def test_never_falls_back_to_a_non_ncbitaxon_top_hit(fake):
    fake.table["Lachnospiraceae"] = [_row("C0000001", "Lachnospiraceae", 5.0, prefix="UMLS")]
    votes, availability, _, _ = _annotate_one("k__Bacteria;f__Lachnospiraceae")
    assert _voted_ids(votes) == []
    assert availability == AVAILABILITY_NO_MATCH


def test_route_strings_come_from_the_declared_constant_set():
    assert tl.ROUTES >= {"exact", "synonym", "superset", "delegated"}
    assert all(r.startswith("abstain:") for r in tl.ABSTAIN_REASONS)


# ---------------------------------------------------------------------------------------- error paths


def test_kestrel_fault_is_recorded_and_is_not_an_abstention(monkeypatch):
    kestrel = FakeKestrel(error=ConnectionError("kestrel down"))
    monkeypatch.setattr(TaxonLabelAnnotator, "_kestrel_hybrid_search", staticmethod(kestrel))
    votes, availability, source, _ = _annotate_one("k__Bacteria;g__Dorea")
    assert _voted_ids(votes) == []
    assert availability == AVAILABILITY_UNAVAILABLE
    assert not source.startswith("abstain:")


def test_mixed_batch_faults_only_rows_that_searched(monkeypatch):
    kestrel = FakeKestrel(error=ConnectionError("kestrel down"))
    monkeypatch.setattr(TaxonLabelAnnotator, "_kestrel_hybrid_search", staticmethod(kestrel))
    df = pd.DataFrame({"name": ["k__Bacteria;p__Cyanobacteria;c__Chloroplast", "k__Bacteria;g__Dorea"]}, index=[7, 8])
    fault_map, token = start_dataset_fault_recording()
    try:
        ann = TaxonLabelAnnotator()
        cache = ann.build_availability_cache(df, "name")
        ann.get_annotations_bulk(df, "name", TAXON, cache=cache)
        sources = [ann.get_source(row, "name", cache=cache)[ann.slug] for _, row in df.iterrows()]
        availability = [ann.get_availability(row, "name", cache=cache)[ann.slug] for _, row in df.iterrows()]
    finally:
        end_dataset_fault_recording(token)
    assert set(fault_map) == {8}
    assert sources[0] == "abstain:host_or_organelle"
    assert availability[1] == AVAILABILITY_UNAVAILABLE


def test_missing_snapshot_raises_rather_than_guessing(monkeypatch, tmp_path, fake):
    from biomapper2.core import ncbi_taxonomy

    monkeypatch.setattr(config, "NCBI_TAXONOMY_SNAPSHOT_PATH", str(tmp_path / "prokaryote_taxa_gone.tsv"))
    ncbi_taxonomy.reset()
    try:
        with pytest.raises(ncbi_taxonomy.NcbiTaxonomyError):
            _annotate_one("k__Bacteria;g__Dorea")
    finally:
        monkeypatch.setattr(config, "NCBI_TAXONOMY_SNAPSHOT_PATH", None)
        ncbi_taxonomy.reset()


# ---------------------------------------------------------------------------------------- engine wiring


def _engine() -> AnnotationEngine:
    bc = MagicMock()
    bc.get_descendants.side_effect = lambda c: {c}
    return AnnotationEngine(biolink_client=bc)


def test_organism_taxon_selects_only_the_taxon_annotator():
    assert _engine()._select_annotators(TAXON) == ["taxon-label"]


def test_kill_switch_restores_the_generic_hybrid_annotator(monkeypatch):
    monkeypatch.setattr(config, "TAXON_LABEL_ANNOTATOR_ENABLED", False)
    assert _engine()._select_annotators(TAXON) == ["kestrel-hybrid-search"]


def test_ancestor_category_keeps_the_generic_hybrid_annotator():
    # biolink:NamedThing (the fallback for every unrecognized entity type) has OrganismTaxon among its
    # descendants; it must keep the generic annotator, not be routed to the taxon annotator.
    bc = MagicMock()
    bc.get_descendants.side_effect = lambda c: (
        {"biolink:NamedThing", TAXON, "biolink:SmallMolecule"} if c == "biolink:NamedThing" else {c}
    )
    assert AnnotationEngine(biolink_client=bc)._select_annotators("biolink:NamedThing") == [
        "metabolomics-workbench",
        "goslin-lipid",
        "kestrel-hybrid-search",
    ]


def test_small_molecule_selection_is_unchanged():
    assert _engine()._select_annotators("biolink:SmallMolecule") == [
        "metabolomics-workbench",
        "goslin-lipid",
        "kestrel-hybrid-search",
    ]


def _spy_kwargs(monkeypatch, engine, slug):
    seen: dict = {}

    def spy(entities, name_field, category, prefixes=None, **kwargs):
        seen.update(kwargs)
        return pd.Series([{} for _ in range(len(entities))], index=entities.index)

    monkeypatch.setattr(engine.annotator_registry[slug], "get_annotations_bulk", spy)
    return seen


def test_organism_taxon_kwargs_reach_the_selected_annotator(monkeypatch):
    engine = _engine()
    seen = _spy_kwargs(monkeypatch, engine, "taxon-label")
    engine.annotate(pd.DataFrame({"name": ["Dorea"]}), "name", [], TAXON, [], mode="all")
    assert seen["preferred_prefixes"] == {"NCBITaxon"}

    monkeypatch.setattr(config, "TAXON_LABEL_ANNOTATOR_ENABLED", False)
    engine = _engine()
    seen = _spy_kwargs(monkeypatch, engine, "kestrel-hybrid-search")
    engine.annotate(pd.DataFrame({"name": ["Dorea"]}), "name", [], TAXON, [], mode="all")
    assert seen["preferred_prefixes"] == {"NCBITaxon"}


def test_explicit_annotators_list_is_honored(monkeypatch, fake):
    engine = _engine()
    seen = _spy_kwargs(monkeypatch, engine, "kestrel-hybrid-search")
    engine.annotate(
        pd.DataFrame({"name": ["Dorea"]}), "name", [], TAXON, [], mode="all", annotators=["kestrel-hybrid-search"]
    )
    assert seen  # the generic annotator ran
    assert fake.calls == []  # the taxon annotator did not


def test_dataset_path_makes_one_bulk_search_and_records_endpoints_per_row(fake):
    labels = [
        "k__Bacteria;g__Dorea",
        "k__Bacteria;f__Prevotellaceae",
        "k__Bacteria;p__Cyanobacteria;c__Chloroplast",
        "k__Bacteria;g__Dorea",
        "Homo sapiens",
    ]
    out = _engine().annotate(pd.DataFrame({"name": labels}), "name", [], TAXON, [], mode="all")
    assert len(fake.calls) == 1
    assert sorted(fake.calls[0]) == ["Dorea", "Homo sapiens", "Prevotellaceae"]
    assert list(out["kestrel_endpoints_used"]) == [
        ["hybrid-search"],
        ["hybrid-search"],
        [],
        ["hybrid-search"],
        ["hybrid-search"],
    ]
    assert out["annotator_source"].iloc[2]["taxon-label"] == "abstain:host_or_organelle"
    assert "NCBITaxon" in out["assigned_ids"].iloc[0]["taxon-label"]


def test_single_path_records_no_endpoint_for_a_pre_search_abstention(fake):
    out = _engine().annotate({"name": "sk__Eukaryota;k__Metazoa"}, "name", [], TAXON, [], mode="all")
    assert list(out["kestrel_endpoints_used"]) == []
    out = _engine().annotate({"name": "k__Bacteria;g__Dorea"}, "name", [], TAXON, [], mode="all")
    assert list(out["kestrel_endpoints_used"]) == ["hybrid-search"]
