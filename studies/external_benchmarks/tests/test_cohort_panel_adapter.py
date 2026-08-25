"""Unit 1 — cross-cohort panel adapter (offline, in-memory fixtures, no network)."""

from __future__ import annotations

import pandas as pd
import pytest

from studies.external_benchmarks.adapters.cohort_panel import (
    ARIVALE,
    BLSA,
    CohortPanelConfig,
    load_cohort_panel,
)


def _arivale_like() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "BiochemicalName": ["glucose", "citrate", "X - 12345", "", "glucose"],
            "CAS_ID": ["50-99-7", "77-92-9", "", "", "50-99-7"],
            "KEGG_ID": ["C00031", "C00158", "", "", "C00031"],
            "HMDB_ID": ["HMDB0000122", "HMDB0000094", "", "", "HMDB0000122"],
            "PubChem_ID": ["5793", "311", "", "", "5793"],
        }
    )


def test_loads_names_and_ids_certifiable():
    panel = load_cohort_panel(_arivale_like(), ARIVALE)
    # glucose (dup collapsed), citrate kept; "X - 12345" and blank excluded.
    assert panel.names == ["glucose", "citrate"]
    assert set(panel.id_columns) == {"cas", "kegg", "hmdb", "pubchem"}
    assert panel.certifiable is True  # has structural vendor IDs


def test_exclusions_counted_not_silent():
    panel = load_cohort_panel(_arivale_like(), ARIVALE)
    exc = panel.card["exclusions"]
    assert exc["blank_name"] == 1
    assert exc["unidentified_x"] == 1
    assert exc["duplicate_name"] == 1
    assert panel.card["n_raw"] == 5 and panel.card["n_rows"] == 2


def test_blsa_names_only_not_certifiable():
    frame = pd.DataFrame({"name": ["Alanine", "Arginine", "PC aa C34:2"]})
    panel = load_cohort_panel(frame, BLSA)
    assert panel.certifiable is False  # names only → counts-only, never certified off the KG
    assert panel.id_columns == ()


def test_missing_name_column_fails_loud():
    frame = pd.DataFrame({"WrongHeader": ["a", "b"]})
    with pytest.raises(KeyError):
        load_cohort_panel(frame, ARIVALE)


def test_monti_size_gap_surfaced_not_reconciled():
    # 2 loaded rows vs Monti's declared 626 → gap reported on the card, never silently filtered.
    panel = load_cohort_panel(_arivale_like(), ARIVALE)
    assert panel.card["monti_panel_size"] == 626
    assert panel.card["monti_size_gap"] == 2 - 626


def test_sha_pinned_and_deterministic():
    cfg = CohortPanelConfig(key="t", name_column="name")  # parse_name_list emits a "name" column
    p1 = load_cohort_panel(b"glucose\ncitrate\n", cfg, name_list=True)
    p2 = load_cohort_panel(b"glucose\ncitrate\n", cfg, name_list=True)
    assert p1.card["source_sha256"] == p2.card["source_sha256"]
    assert p1.names == ["glucose", "citrate"]


def test_kegg_only_is_not_certifiable():
    # KEGG alone is not resolvable to a structure via the PubChem oracle → not certifiable.
    cfg = CohortPanelConfig(key="k", name_column="name", id_columns={"kegg": "KEGG_ID"})
    frame = pd.DataFrame({"name": ["glucose"], "KEGG_ID": ["C00031"]})
    panel = load_cohort_panel(frame, cfg)
    assert panel.certifiable is False


def test_name_list_parsing_strips_and_drops_blanks():
    panel = load_cohort_panel(b"Alanine\n\n  Arginine  \nAlanine\n", BLSA, name_list=True)
    assert panel.names == ["Alanine", "Arginine"]  # blank dropped, whitespace stripped, dup collapsed
