"""Unit tests for Phase 2 Shared Base hooks.

Validates get_cache_dir dynamic overrides, offline BiolinkClient loading,
EntityMappingResult kestrel_degraded serialization semantics, and route extraction.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from biomapper2.api.kestrel_discovery import load_from_disk, save_to_disk
from biomapper2.api.models.responses import EntityMappingResult
from biomapper2.api.routes.mapping import extract_mapping_result
from biomapper2.biolink_client import BiolinkClient
from biomapper2.config import PROJECT_ROOT, get_cache_dir
from biomapper2.core.annotators.metabolomics_workbench import MetabolomicsWorkbenchAnnotator
from biomapper2.core.structure_resolver import StructureResolver
from biomapper2.utils import get_session, reset_session


@pytest.mark.unit
def test_get_cache_dir_override() -> None:
    """get_cache_dir reflects os.environ['BIOMAPPER2_CACHE_DIR'] dynamically with 0700 permissions."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        with patch.dict(os.environ, {"BIOMAPPER2_CACHE_DIR": tmp_dir}):
            resolved = get_cache_dir()
            assert resolved == Path(tmp_dir)
            assert resolved.exists()
            stat_mode = resolved.stat().st_mode & 0o777
            assert stat_mode == 0o700

        with patch.dict(os.environ, {"BIOMAPPER2_CACHE_DIR": ""}):
            default_dir = get_cache_dir()
            assert default_dir == PROJECT_ROOT / "cache"


@pytest.mark.unit
def test_biolink_client_offline_predicate_map() -> None:
    """BiolinkClient initializes offline without network requests using local fixtures."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        with patch.dict(os.environ, {"BIOMAPPER2_CACHE_DIR": tmp_dir}):
            client = BiolinkClient()
            ancestors = client.get_ancestors("biolink:SmallMolecule")
            assert "biolink:SmallMolecule" in ancestors
            assert "biolink:ChemicalEntity" in ancestors
            assert (Path(tmp_dir) / "biolink-predicate-mapping.yaml").exists()


@pytest.mark.unit
def test_kestrel_discovery_preset_cache_path() -> None:
    """save_to_disk and load_from_disk use get_cache_dir() unless PRESET_CACHE_PATH was patched."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        with patch.dict(os.environ, {"BIOMAPPER2_CACHE_DIR": tmp_dir}):
            presets_data = {"biolink:Disease": ["MONDO"]}
            save_to_disk(presets_data)
            loaded = load_from_disk()
            assert loaded == presets_data
            assert (Path(tmp_dir) / "entity_type_presets.json").exists()

        # When explicitly patched to another location, patched path wins
        patched_file = Path(tmp_dir) / "custom_presets.json"
        with patch("biomapper2.api.kestrel_discovery.PRESET_CACHE_PATH", patched_file):
            save_to_disk({"biolink:Gene": ["HGNC"]})
            assert patched_file.exists()


@pytest.mark.unit
def test_entity_mapping_result_omits_kestrel_degraded_when_none() -> None:
    """EntityMappingResult serializes without 'kestrel_degraded' when value is None."""
    result = EntityMappingResult(name="glucose")
    dumped = result.model_dump()
    assert "kestrel_degraded" not in dumped
    # Other None fields remain present
    assert dumped["primary_curie"] is None
    assert dumped["chosen_kg_id"] is None


@pytest.mark.unit
def test_entity_mapping_result_includes_kestrel_degraded_when_true() -> None:
    """EntityMappingResult includes 'kestrel_degraded: true' when value is True."""
    result = EntityMappingResult(name="glucose", kestrel_degraded=True)
    dumped = result.model_dump()
    assert dumped.get("kestrel_degraded") is True


@pytest.mark.unit
def test_extract_mapping_result_wires_kestrel_degraded() -> None:
    """extract_mapping_result accurately maps kestrel_degraded flag from pipeline item."""
    item_normal = {"name": "aspirin", "chosen_kg_id": "CHEBI:15365"}
    res_normal = extract_mapping_result(item_normal, "aspirin")
    assert res_normal.kestrel_degraded is None
    assert "kestrel_degraded" not in res_normal.model_dump()

    item_degraded = {"name": "aspirin", "chosen_kg_id": "CHEBI:15365", "kestrel_degraded": True}
    res_degraded = extract_mapping_result(item_degraded, "aspirin")
    assert res_degraded.kestrel_degraded is True
    assert res_degraded.model_dump().get("kestrel_degraded") is True


@pytest.mark.unit
def test_annotator_sessions_use_get_cache_dir() -> None:
    """utils.get_session, MW annotator, and StructureResolver locate DBs in get_cache_dir()."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        with patch.dict(os.environ, {"BIOMAPPER2_CACHE_DIR": tmp_dir}):
            reset_session()
            session = get_session()
            db_path_session = getattr(session.cache, "db_path", None)
            assert db_path_session is not None and tmp_dir in str(db_path_session)
            reset_session()

            mw = MetabolomicsWorkbenchAnnotator()
            db_path_mw = getattr(mw._session.cache, "db_path", None)
            assert db_path_mw is not None and tmp_dir in str(db_path_mw)

            mock_linker = None
            sr = StructureResolver(linker=mock_linker)  # type: ignore
            db_path_sr = getattr(sr._session.cache, "db_path", None)
            assert db_path_sr is not None and tmp_dir in str(db_path_sr)
