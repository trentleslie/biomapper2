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
def test_biolink_client_uses_get_cache_dir() -> None:
    """BiolinkClient reads cached schema and prefix map from BIOMAPPER2_CACHE_DIR via get_cache_dir()."""
    import json
    from unittest.mock import MagicMock

    import requests as req_mod

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        (tmp_path / "biolink-model_4.2.5.yaml").write_text(
            "id: https://w3id.org/biolink/biolink-model\n", encoding="utf-8"
        )
        (tmp_path / "biolink-model-prefix-map_4.2.5.json").write_text(
            json.dumps({"CHEBI": "http://purl.obolibrary.org/obo/CHEBI_"}),
            encoding="utf-8",
        )
        with (
            patch.dict(os.environ, {"BIOMAPPER2_CACHE_DIR": tmp_dir}),
            patch("biomapper2.biolink_client._build_toolkit", return_value=MagicMock()) as mock_tk,
            patch.object(req_mod, "get", side_effect=req_mod.ConnectionError("Network disabled")),
        ):
            client = BiolinkClient()
            mock_tk.assert_called_once_with(str(tmp_path / "biolink-model_4.2.5.yaml"))
            prefix_map = client.get_prefix_map()
            assert prefix_map["CHEBI"] == "http://purl.obolibrary.org/obo/CHEBI_"


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


@pytest.mark.unit
def test_build_toolkit_unset_matches_origin_dev() -> None:
    """When BIOMAPPER2_PREDICATE_MAP_URL is unset, _build_toolkit matches origin/dev byte-for-byte."""
    import json
    from unittest.mock import MagicMock

    import bmt.toolkit as bmt_toolkit_mod
    from bmt import Toolkit

    from biomapper2.biolink_client import _build_toolkit

    fixtures_dir = PROJECT_ROOT / "studies" / "kestrel_fault_benchmark" / "fixtures"
    schema_path = str(fixtures_dir / "biolink-model_4.2.5.yaml")
    pred_yaml = (fixtures_dir / "biolink-predicate-mapping.yaml").read_text(encoding="utf-8")

    _build_toolkit.cache_clear()
    try:
        # 1. Exact constructor signature check: no predicate_map kwarg when unset or empty
        with (
            patch.dict(os.environ, {}, clear=False),
            patch("biomapper2.biolink_client.Toolkit", return_value=MagicMock()) as mock_tk,
        ):
            os.environ.pop("BIOMAPPER2_PREDICATE_MAP_URL", None)
            _build_toolkit("/tmp/schema_unset.yaml")
            assert mock_tk.call_args_list == [((), {"schema": "/tmp/schema_unset.yaml"})]

        _build_toolkit.cache_clear()
        custom_url = "http://127.0.0.1:18100/__fixtures/predicate_mapping.yaml"
        with (
            patch.dict(os.environ, {"BIOMAPPER2_PREDICATE_MAP_URL": custom_url}),
            patch("biomapper2.biolink_client.Toolkit", return_value=MagicMock()) as mock_tk_set,
        ):
            _build_toolkit("/tmp/schema_set.yaml")
            assert mock_tk_set.call_args_list == [((), {"schema": "/tmp/schema_set.yaml", "predicate_map": custom_url})]

        # 2. Real Toolkit output byte-for-byte identity vs direct origin/dev Toolkit(schema=schema_source)
        _build_toolkit.cache_clear()
        seen_urls: list[str] = []

        def _fake_bmt_get(url: str, *args: object, **kwargs: object) -> MagicMock:
            seen_urls.append(url)
            resp = MagicMock()
            resp.text = pred_yaml
            return resp

        with (
            patch.dict(os.environ, {}, clear=False),
            patch.object(bmt_toolkit_mod.requests, "get", side_effect=_fake_bmt_get),
        ):
            os.environ.pop("BIOMAPPER2_PREDICATE_MAP_URL", None)
            baseline_tk = Toolkit(schema=schema_path)
            actual_tk = _build_toolkit(schema_path)

        assert seen_urls == [bmt_toolkit_mod.PREDICATE_MAP, bmt_toolkit_mod.PREDICATE_MAP]
        baseline_payload = {
            "pmap": baseline_tk.pmap,
            "ancestors": sorted(
                baseline_tk.get_ancestors("biolink:SmallMolecule", formatted=True, mixin=True, reflexive=True)
            ),
            "descendants": sorted(
                baseline_tk.get_descendants("biolink:Disease", formatted=True, mixin=True, reflexive=True)
            ),
            "is_cat": baseline_tk.is_category("SmallMolecule"),
        }
        actual_payload = {
            "pmap": actual_tk.pmap,
            "ancestors": sorted(
                actual_tk.get_ancestors("biolink:SmallMolecule", formatted=True, mixin=True, reflexive=True)
            ),
            "descendants": sorted(
                actual_tk.get_descendants("biolink:Disease", formatted=True, mixin=True, reflexive=True)
            ),
            "is_cat": actual_tk.is_category("SmallMolecule"),
        }
        assert json.dumps(actual_payload, sort_keys=True).encode() == (
            json.dumps(baseline_payload, sort_keys=True).encode()
        )
    finally:
        _build_toolkit.cache_clear()
