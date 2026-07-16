"""metLinkR dual scorer — curator-agreement + InChIKey structural concordance (offline)."""

from __future__ import annotations

import pandas as pd
import pytest

from studies.external_benchmarks.config import METLINKR
from studies.external_benchmarks.scorers.metlinkr_scorer import (
    CuratorLeakError,
    UnscorableRunError,
    assert_curator_held_out,
    curator_external_ids,
    curator_resolution_curies,
    merge_vocab_runs,
    prediction_block,
    score_metlinkr,
)


class FakeBlockOracle:
    """Resolves a node id / CURIE to an InChIKey first-block via a dict (test double)."""

    def __init__(self, blocks: dict[str, str | None]):
        self._b = blocks

    def resolved_block(self, node_id: str):
        return self._b.get(node_id)


class FakeIndependentResolver:
    """External, KG-independent gold resolver (test double): curator HMDB/PubChem id -> block."""

    def __init__(self, hmdb: dict[str, str | None] | None = None, pubchem: dict[str, str | None] | None = None):
        self._h = hmdb or {}
        self._p = pubchem or {}

    def block_for_hmdb(self, hmdb: str):
        return self._h.get(hmdb)

    def block_for_pubchem(self, cid: str):
        return self._p.get(cid)


def _mapped_row(rid, name, group, source_file, chosen, equiv, hmdb="", pubchem=""):
    return {
        "input_row_id": rid,
        METLINKR.name_column: name,
        METLINKR.group_label_column: group,
        METLINKR.source_file_column: source_file,
        METLINKR.gold_hmdb_column: hmdb,
        METLINKR.gold_pubchem_column: pubchem,
        "chosen_kg_id": chosen,
        "kg_equivalent_ids": equiv,
    }


@pytest.fixture
def mapped_df():
    """Four rows: two curator cross-dataset pairs (one BioMapper links, one it does not)."""
    return pd.DataFrame(
        [
            # group 1, fileA + fileB -> curator cross pair. BioMapper links (both chosen CHEBI:4167).
            _mapped_row("a:1", "glucose", "1", "fileA", "CHEBI:4167", {"HMDB": ["HMDB0000122"]}, hmdb="HMDB0000122"),
            _mapped_row("b:1", "D-glucose", "1", "fileB", "CHEBI:4167", {}, pubchem="5793"),
            # group 2, fileA + fileB -> curator cross pair. BioMapper does NOT link (disjoint ids).
            _mapped_row("a:2", "citrate", "2", "fileA", "CHEBI:30769", {}),
            _mapped_row("b:2", "citric acid", "2", "fileB", "CHEBI:99999", {}),
        ]
    )


def test_curator_agreement_rate_counts_cross_dataset_links(mapped_df):
    result = score_metlinkr(mapped_df, METLINKR, oracle=None)
    ca = result["curator_agreement"]
    # 2 curator cross-dataset pairs; BioMapper links exactly 1 (the glucose pair) -> 50%
    assert ca["curator_cross_pairs"] == 2
    assert ca["linked"] == 1
    assert ca["curator_agreement_rate"] == 0.5


def test_structural_concordance_uses_held_out_curator_id(mapped_df):
    # Prediction blocks come from the oracle fallback on chosen_kg_id (no inline INCHIKEY in fixtures).
    # BioMapper's chosen CHEBI:4167 and the curator HMDB:HMDB0000122 both resolve to the glucose block;
    # the pubchem row (D-glucose) curator ref resolves to a DIFFERENT block -> 1 concordant of 2 scored.
    # The curator PubChem id is offered to the oracle in KG-form PUBCHEM.COMPOUND: first.
    oracle = FakeBlockOracle(
        {
            "CHEBI:4167": "WQZGKKKJIJFFOK",  # BioMapper's pick (both glucose rows)
            "HMDB:HMDB0000122": "WQZGKKKJIJFFOK",  # curator ref for glucose -> concordant
            "PUBCHEM.COMPOUND:5793": "XXXXXXXXXXXXXX",  # curator ref for D-glucose -> discordant
        }
    )
    result = score_metlinkr(mapped_df, METLINKR, oracle=oracle)
    st = result["inchikey_structural_concordance"]
    assert st["scored"] == 2  # glucose (hmdb) + D-glucose (pubchem) rows carry a provided id
    assert st["concordant"] == 1
    assert st["concordance_rate"] == 0.5
    assert "shared_infra_caveat" in st


def test_prediction_block_prefers_inline_inchikey():
    # An INCHIKEY carried inline in kg_equivalent_ids is used without any oracle call.
    row = pd.Series(
        {"chosen_kg_id": "CHEBI:4167", "kg_equivalent_ids": {"INCHIKEY": ["WQZGKKKJIJFFOK-GASJEMHNSA-N"]}}
    )
    assert prediction_block(row, oracle=None) == "WQZGKKKJIJFFOK"


def test_curator_resolution_curies_offers_kg_prefixes():
    row = pd.Series({METLINKR.gold_hmdb_column: "HMDB0000122", METLINKR.gold_pubchem_column: "5793"})
    cands = curator_resolution_curies(row, METLINKR)
    # HMDB direct; PubChem offered as PUBCHEM.COMPOUND: (KG-resolvable) before the bare fallback
    assert cands[0] == "HMDB:HMDB0000122"
    assert "PUBCHEM.COMPOUND:5793" in cands
    assert cands.index("PUBCHEM.COMPOUND:5793") < cands.index("PUBCHEM:5793")


def test_curator_resolution_normalizes_legacy_hmdb_and_float_pubchem():
    # Metabolon ships legacy 5-digit HMDB accessions and TSV readback can float-ify PubChem ids.
    row = pd.Series({METLINKR.gold_hmdb_column: "HMDB02759", METLINKR.gold_pubchem_column: "159663.0"})
    cands = curator_resolution_curies(row, METLINKR)
    assert "HMDB:HMDB0002759" in cands  # zero-padded modern accession offered
    assert "PUBCHEM.COMPOUND:159663" in cands  # float ".0" tail stripped
    assert not any(c.endswith(".0") for c in cands)
    assert "HMDB:nan" not in cands


def test_structural_uses_independent_resolver_for_gold(mapped_df):
    # PREDICTION side rides the KG oracle; GOLD side rides the INDEPENDENT external resolver (not the
    # KG). glucose: pred CHEBI:4167 -> block == curator HMDB block -> concordant. D-glucose: pred same
    # block, curator PubChem 5793 -> different block -> discordant. 1 concordant of 2 scored.
    oracle = FakeBlockOracle({"CHEBI:4167": "WQZGKKKJIJFFOK"})
    indep = FakeIndependentResolver(
        hmdb={"HMDB0000122": "WQZGKKKJIJFFOK"},  # curator gold for glucose -> concordant
        pubchem={"5793": "XXXXXXXXXXXXXX"},  # curator gold for D-glucose -> discordant
    )
    result = score_metlinkr(mapped_df, METLINKR, oracle=oracle, independent_resolver=indep)
    st = result["inchikey_structural_concordance"]
    assert st["scored"] == 2
    assert st["concordant"] == 1
    assert st["concordance_rate"] == 0.5
    assert st["gold_resolution"] == "independent_external_pubchem_pugrest"
    assert st["needs_verification"] == 0
    assert "independence_note" in st
    assert "shared_infra_caveat" not in st  # independent path is not circular


def test_structural_marks_needs_verification_when_external_uncovered(mapped_df):
    # The independent external resolver can cover glucose's HMDB but NOT D-glucose's PubChem id ->
    # that row is flagged needs-verification and EXCLUDED from the denominator (not KG-resolved).
    oracle = FakeBlockOracle({"CHEBI:4167": "WQZGKKKJIJFFOK"})
    indep = FakeIndependentResolver(hmdb={"HMDB0000122": "WQZGKKKJIJFFOK"}, pubchem={})  # 5793 -> None
    result = score_metlinkr(mapped_df, METLINKR, oracle=oracle, independent_resolver=indep)
    st = result["inchikey_structural_concordance"]
    assert st["scored"] == 1
    assert st["concordant"] == 1
    assert st["concordance_rate"] == 1.0
    assert st["needs_verification"] == 1
    assert st["needs_verification_rows"][0]["name"] == "D-glucose"


def test_curator_external_ids_bare_forms_hmdb_first():
    row = pd.Series({METLINKR.gold_hmdb_column: "HMDB02759", METLINKR.gold_pubchem_column: "159663.0"})
    ids = curator_external_ids(row, METLINKR)
    assert ("hmdb", "HMDB0002759") in ids  # legacy 5-digit zero-padded to modern accession
    assert ("pubchem", "159663") in ids  # float ".0" readback tail stripped
    assert ids[0][0] == "hmdb"  # HMDB offered before PubChem (resolution order)
    assert not any(v.endswith(".0") for _, v in ids)


def test_structural_none_when_no_oracle(mapped_df):
    result = score_metlinkr(mapped_df, METLINKR, oracle=None)
    assert result["inchikey_structural_concordance"] is None


def test_fail_loud_when_nothing_to_score():
    # No curator cross-pairs (all singleton groups, one file) and no provided ids -> unscorable.
    df = pd.DataFrame(
        [
            _mapped_row("a:1", "glucose", "1", "fileA", "CHEBI:4167", {}),
            _mapped_row("a:2", "citrate", "2", "fileA", "CHEBI:30769", {}),
        ]
    )
    with pytest.raises(UnscorableRunError):
        score_metlinkr(df, METLINKR, oracle=None)


def test_anti_trivial_guard_requires_held_out_columns():
    df = pd.DataFrame([{METLINKR.name_column: "glucose", "chosen_kg_id": "CHEBI:4167"}])
    with pytest.raises(CuratorLeakError, match="held-out"):
        assert_curator_held_out(df, METLINKR)


def test_merge_vocab_runs_unions_passes_by_input_row_id():
    # Two per-vocab passes of the SAME row (one resolves CHEBI, the other adds an HMDB equivalent).
    pass_chebi = pd.DataFrame(
        [_mapped_row("a:1", "glucose", "1", "fileA", "CHEBI:4167", {}, hmdb="HMDB0000122")]
    )
    pass_hmdb = pd.DataFrame(
        [_mapped_row("a:1", "glucose", "1", "fileA", "", {"HMDB": ["HMDB0000122"]}, hmdb="HMDB0000122")]
    )
    merged = merge_vocab_runs([pass_chebi, pass_hmdb], METLINKR)
    assert len(merged) == 1
    row = merged.iloc[0]
    assert row["chosen_kg_id"] == "CHEBI:4167"  # first non-empty pass is representative
    assert "HMDB" in row["kg_equivalent_ids"]  # equivalents unioned across passes
    assert row[METLINKR.group_label_column] == "1"  # held-out grouping carried through
