from unittest.mock import MagicMock, patch

import pytest

from biomapper2.provenance import KgBuildInfo, RunProvenance, build_run_provenance


@pytest.mark.unit
def test_kg_build_info_tolerates_unknown_fields():
    """Forward-compatible: enrichments like node_count are accepted, not rejected."""
    info = KgBuildInfo.model_validate({"kg_version": "2026.06.0", "node_count": 9_000_000})
    assert info.kg_version == "2026.06.0"


@pytest.mark.unit
def test_build_run_provenance_from_mocked_health():
    fake = MagicMock()
    fake.json.return_value = {"kestrel_version": "0.2.0", "kg_build": {"kg_version": "2026.06.0", "sources": ["kg2"]}}
    fake.raise_for_status.return_value = None
    with patch("biomapper2.provenance.requests.get", return_value=fake):
        prov = build_run_provenance("https://kestrel.example/api", run_timestamp="2026-06-15T00:00:00+00:00")
    assert isinstance(prov, RunProvenance)
    assert prov.kestrel_version == "0.2.0"
    assert prov.kg_build.kg_version == "2026.06.0"


@pytest.mark.unit
def test_build_run_provenance_degrades_to_unknown_on_failure(caplog):
    """No network / bad response → explicit 'unknown', logged, never a crash."""
    with patch("biomapper2.provenance.requests.get", side_effect=ConnectionError("down")):
        with caplog.at_level("WARNING"):
            prov = build_run_provenance("https://kestrel.example/api", run_timestamp="2026-06-15T00:00:00+00:00")
    assert prov.kestrel_version == "unknown"
    assert prov.kg_build.kg_version == "unknown"
    assert any("provenance" in r.message.lower() for r in caplog.records)


@pytest.mark.integration
@pytest.mark.requires_api
def test_live_health_yields_real_kg_build():
    """Against a live Kestrel that exposes build metadata, kg_build is populated.

    Skips (rather than fails) when the deployed Kestrel predates the build_info
    feature — i.e. /health serves no kg_build yet. Becomes a real assertion once the
    KRAKEN/Kestrel build-info changes are deployed and the KG is rebuilt.
    """
    from biomapper2.config import get_kestrel_api_url
    from biomapper2.provenance import build_run_provenance

    url = get_kestrel_api_url()
    prov = build_run_provenance(url, run_timestamp="2026-06-15T00:00:00+00:00")
    if prov.kestrel_version == "unknown" or prov.kg_build.kg_version == "unknown":
        pytest.skip(f"Kestrel at {url} does not expose build_info yet — deploy KRAKEN/Kestrel build-info to enable")
    assert prov.kestrel_version != "unknown"
    assert prov.kg_build.kg_version != "unknown"
