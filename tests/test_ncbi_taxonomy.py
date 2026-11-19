"""Tests for the pinned NCBI prokaryote taxonomy snapshot loader (core/ncbi_taxonomy.py, 16S plan U3).

Two inputs:
- the PACKAGED snapshot (src/biomapper2/data/ncbi_taxonomy/), for the real-taxonomy facts;
- the small FIXTURE subset (tests/fixtures/ncbi_taxonomy/, written by the same build script from the same
  taxdump), for the config override and error paths.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

import pytest

from biomapper2 import config
from biomapper2.core import ncbi_taxonomy as nt

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "ncbi_taxonomy"
FIXTURE = next(FIXTURE_DIR.glob("prokaryote_taxa_*.tsv"))
PACKAGED_DIR = Path(nt.__file__).resolve().parents[1] / "data" / "ncbi_taxonomy"

# Legacy phylum names (the older forms used by Greengenes, SILVA and RDP, renamed by Oren & Garrity and
# by later NCBI updates; see the plan's External References) that NCBI still carries ON the phylum
# node as a synonym or phylum-rank genbank common name. Each must resolve at PHYLUM rank (R6), never at the
# kingdom ("Firmicutes" is also a Synonym of kingdom Bacillati 1783272).
LEGACY_PHYLUM_NAMES = {
    "Acidobacteria": 57723,
    "Actinobacteria": 201174,
    "Aquificae": 200783,
    "Armatimonadetes": 67819,
    "Firmicutes": 1239,
    "Bacteroidetes": 976,
    "Caldiserica": 67814,
    "Calditrichaeota": 1930617,
    "Chlamydiae": 204428,
    "Chlorobi": 1090,
    "Chloroflexi": 200795,
    "Deinococcus-Thermus": 1297,
    "Dictyoglomi": 68297,
    "Elusimicrobia": 74152,
    "Fibrobacteres": 65842,
    "Fusobacteria": 32066,
    "Gemmatimonadetes": 142182,
    "Kiritimatiellaeota": 134625,
    "Lentisphaerae": 256845,
    "Tenericutes": 544448,
    "Nitrospinae": 1293497,
    "Nitrospirae": 40117,
    "Planctomycetes": 203682,
    "Proteobacteria": 1224,
    "Rhodothermaeota": 1853220,
    "Spirochaetes": 203691,
    "Synergistetes": 508458,
    "Thermomicrobia": 3027942,
    "Verrucomicrobia": 74201,
    "Cyanobacteria": 1117,
    "Euryarchaeota": 28890,
    "Crenarchaeota": 28889,
    "Thaumarchaeota": 651137,
}
# Legacy phylum names NCBI does NOT carry on the phylum node (taxdump 2026-11-19): they survive only as
# the CLASS name. Pinned so a rebuild that changes this is noticed, and so nobody re-adds a runtime rename
# table on the belief that the snapshot covers every legacy phylum. PR2's ladder must handle them.
LEGACY_PHYLUM_NAMES_ONLY_AT_CLASS = {
    "Atribacteria": 2847774,
    "Deferribacteres": 68337,
    "Thermodesulfobacteria": 67799,
    "Thermotogae": 188708,
}


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    monkeypatch.setattr(config, "NCBI_TAXONOMY_SNAPSHOT_PATH", None)
    nt.reset()
    yield
    nt.reset()


@pytest.fixture
def use_fixture(monkeypatch):
    monkeypatch.setattr(config, "NCBI_TAXONOMY_SNAPSHOT_PATH", str(FIXTURE))
    nt.reset()


# ---------------------------------------------------------------------------------------- happy path


def test_genus_lookups():
    assert nt.lookup("Ruminococcus", rank="genus") == [1263]
    assert nt.lookup("Blautia", rank="genus") == [572511]


def test_lookup_is_case_insensitive_and_rank_optional():
    assert nt.lookup("ruminococcus") == [1263]


def test_merged_old_taxid_maps_to_current():
    assert nt.current_taxid(705) == 662
    assert nt.current_taxid(662) == 662
    assert nt.current_taxid(999999999) is None


def test_names_and_rank_of_a_node():
    assert "Bacillota" in nt.names_of(1239)
    assert nt.rank_of(1239) == "phylum"
    assert nt.scientific_name(1239) == "Bacillota"


def test_version_is_the_sidecar_first_line():
    version = nt.version()
    assert version is not None and version.startswith("ncbi-taxdump/")


# ---------------------------------------------------------------------------------------- edge cases


def test_firmicutes_at_phylum_is_bacillota_never_the_kingdom():
    assert nt.lookup("Firmicutes", rank="phylum") == [1239]
    assert 1783272 not in nt.lookup("Firmicutes", rank="phylum")


@pytest.mark.parametrize("name, taxid", sorted(LEGACY_PHYLUM_NAMES.items()))
def test_legacy_phylum_names_resolve_at_phylum(name, taxid):
    assert nt.lookup(name, rank="phylum") == [taxid]


@pytest.mark.parametrize("name, taxid", sorted(LEGACY_PHYLUM_NAMES_ONLY_AT_CLASS.items()))
def test_legacy_phylum_names_ncbi_keeps_only_as_class(name, taxid):
    assert nt.lookup(name, rank="phylum") == []
    assert nt.lookup(name, rank="class") == [taxid]


def test_actinobacteria_depends_on_rank():
    assert nt.lookup("Actinobacteria", rank="class") == [1760]
    assert nt.lookup("Actinobacteria", rank="phylum") == [201174]


def test_is_prokaryote():
    assert nt.is_prokaryote(1263)
    assert nt.is_prokaryote(2) and nt.is_prokaryote(2157)
    assert not nt.is_prokaryote(210425)  # Proteus, the salamander
    assert not nt.is_prokaryote(9606)
    assert nt.is_prokaryote(1783270)  # FCB group: a clade node on the path


def test_merged_taxid_is_prokaryote_through_its_current_id():
    assert nt.is_prokaryote(705)


def test_every_parent_pointer_resolves_inside_the_snapshot():
    snap = nt.load_or_raise()
    for taxid, node in snap.nodes.items():
        if taxid in (2, 2157):
            assert node.parent is None
        else:
            assert node.parent in snap.nodes, taxid


def test_homonym_list_records_non_prokaryote_taxids():
    assert nt.homonym_nonprokaryote_taxids("Bacillus") == frozenset({55087})
    assert nt.homonym_nonprokaryote_taxids("proteus") == frozenset({210425})
    assert nt.is_homonym_nonprokaryote_side(55087)
    assert nt.is_homonym_nonprokaryote_side(210425)
    assert not nt.is_homonym_nonprokaryote_side(1386)
    assert not nt.is_homonym_nonprokaryote_side(9606)


def test_packaged_snapshot_is_small_enough():
    total = sum(p.stat().st_size for p in PACKAGED_DIR.iterdir() if p.is_file())
    assert total < 5 * 1024 * 1024


def test_is_present_and_version_with_fixture(use_fixture):
    assert nt.is_present()
    assert nt.lookup("Dorea", rank="genus") == [189330]


# ---------------------------------------------------------------------------------------- error paths


def _copy_fixture(tmp_path: Path) -> Path:
    for path in FIXTURE_DIR.iterdir():
        shutil.copy(path, tmp_path / path.name)
    return tmp_path / FIXTURE.name


def test_configured_but_missing_file_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "NCBI_TAXONOMY_SNAPSHOT_PATH", str(tmp_path / "prokaryote_taxa_nope.tsv"))
    with pytest.raises(nt.NcbiTaxonomyError):
        nt.load_or_raise()
    assert not nt.is_present()


def test_malformed_row_raises(monkeypatch, tmp_path):
    snapshot = _copy_fixture(tmp_path)
    with snapshot.open("a", encoding="utf-8") as fh:
        fh.write("not-a-taxid\t2\tgenus\tBroken\tscientific name\n")
    monkeypatch.setattr(config, "NCBI_TAXONOMY_SNAPSHOT_PATH", str(snapshot))
    with pytest.raises(nt.NcbiTaxonomyError, match="malformed"):
        nt.load_or_raise()


def test_unresolvable_parent_raises(monkeypatch, tmp_path):
    snapshot = _copy_fixture(tmp_path)
    with snapshot.open("a", encoding="utf-8") as fh:
        fh.write("424242\t31337\tgenus\tOrphanella\tscientific name\n")
    monkeypatch.setattr(config, "NCBI_TAXONOMY_SNAPSHOT_PATH", str(snapshot))
    with pytest.raises(nt.NcbiTaxonomyError, match="parent"):
        nt.load_or_raise()


def test_missing_companion_file_raises(monkeypatch, tmp_path):
    snapshot = _copy_fixture(tmp_path)
    next(tmp_path.glob("homonyms_*.tsv")).unlink()
    monkeypatch.setattr(config, "NCBI_TAXONOMY_SNAPSHOT_PATH", str(snapshot))
    with pytest.raises(nt.NcbiTaxonomyError, match="homonyms"):
        nt.load_or_raise()


def test_absent_sidecar_gives_version_none_and_a_loud_warning(monkeypatch, tmp_path, caplog):
    snapshot = _copy_fixture(tmp_path)
    snapshot.with_name(snapshot.name + ".version").unlink()
    monkeypatch.setattr(config, "NCBI_TAXONOMY_SNAPSHOT_PATH", str(snapshot))
    with caplog.at_level(logging.WARNING):
        assert nt.version() is None
    assert any("version" in rec.getMessage() for rec in caplog.records if rec.levelno >= logging.WARNING)
    assert nt.lookup("Ruminococcus", rank="genus") == [1263]
