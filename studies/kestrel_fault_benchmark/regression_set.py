"""Regression test runner and golden baseline capture/verification.

Executes the 20 regression entities, 10 special callsite probes, 1 batch run,
2 dataset stream runs, and 2 dataset tabular runs across the biomapper2 API.
Normalizes dynamic fields and verifies bit-for-bit SHA-256 identity against
golden_healthy_e578a93.json.gz and golden_healthy_manifest.json.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Any

import requests

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
DEFAULT_CASSETTE_PATH = FIXTURES_DIR / "kestrel_cassette.json.gz"
DEFAULT_GOLDEN_PATH = FIXTURES_DIR / "golden_healthy_e578a93.json.gz"
DEFAULT_MANIFEST_PATH = FIXTURES_DIR / "golden_healthy_manifest.json"
DISEASE_REG_PATH = FIXTURES_DIR / "disease_reg.tsv"
METAB_REG_PATH = FIXTURES_DIR / "metab_reg.tsv"

NORMALIZED_REQUEST_ID = "00000000-0000-0000-0000-000000000000"
NORMALIZED_TIMESTAMP = "1970-01-01T00:00:00+00:00"
NORMALIZED_MAPPED_DATASET = "MAPPED_DATASET_NORMALIZED"


def canonical_json_bytes(data: Any) -> bytes:
    """Serialize data to deterministic, sort-keyed UTF-8 JSON bytes."""
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_digest(content: bytes) -> str:
    """Compute SHA-256 hex digest of raw bytes."""
    return hashlib.sha256(content).hexdigest()


def normalize_mapping_response(resp_json: dict[str, Any]) -> dict[str, Any]:
    """Normalize dynamic request_id and processing_time_ms in JSON responses."""
    normalized = json.loads(json.dumps(resp_json))
    if "metadata" in normalized and isinstance(normalized["metadata"], dict):
        normalized["metadata"]["request_id"] = NORMALIZED_REQUEST_ID
        normalized["metadata"]["processing_time_ms"] = 0.0
    return normalized


def normalize_dataset_stats(stats: dict[str, Any]) -> dict[str, Any]:
    """Normalize dynamic run timestamp and dataset paths in tabular stats."""
    normalized = json.loads(json.dumps(stats))
    if "mapped_dataset" in normalized:
        normalized["mapped_dataset"] = NORMALIZED_MAPPED_DATASET
    if "run_provenance" in normalized and isinstance(normalized["run_provenance"], dict):
        if "run_timestamp" in normalized["run_provenance"]:
            normalized["run_provenance"]["run_timestamp"] = NORMALIZED_TIMESTAMP
    return normalized


def load_regression_items(cassette_path: Path | str = DEFAULT_CASSETTE_PATH) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Load the 20 regression entities and 10 special callsite probes from cassette fixture."""
    path = Path(cassette_path)
    with gzip.open(path, "rt", encoding="utf-8") as f:
        data = json.load(f)
    return data.get("regression_entities", []), data.get("special_callsite_probes", [])


class RegressionSuiteResult:
    """Container for regression suite results across all checks."""

    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []
        self.suite_sha256: str = ""

    def add_check(self, check_id: str, check_type: str, canonical_bytes: bytes, raw_data: Any) -> None:
        digest = sha256_digest(canonical_bytes)
        self.checks.append({
            "check_id": check_id,
            "check_type": check_type,
            "sha256": digest,
            "data": raw_data,
        })

    def finalize(self) -> None:
        """Compute deterministic overall suite SHA-256."""
        self.checks.sort(key=lambda c: c["check_id"])
        manifest_lines = [f"{c['check_id']}:{c['sha256']}" for c in self.checks]
        suite_content = "\n".join(manifest_lines).encode("utf-8")
        self.suite_sha256 = sha256_digest(suite_content)

    def to_manifest_dict(self) -> dict[str, Any]:
        """Convert to human-readable manifest summary."""
        return {
            "suite_sha256": self.suite_sha256,
            "check_count": len(self.checks),
            "checks": {c["check_id"]: c["sha256"] for c in self.checks},
        }

    def to_golden_dict(self) -> dict[str, Any]:
        """Convert to full golden payload dictionary."""
        return {
            "suite_sha256": self.suite_sha256,
            "check_count": len(self.checks),
            "checks": self.checks,
        }


def run_regression_suite(
    api_url: str,
    cassette_path: Path | str = DEFAULT_CASSETTE_PATH,
    timeout: float = 60.0,
) -> RegressionSuiteResult:
    """Run all 35 regression checks against a running biomapper2 API."""
    regression_entities, special_probes = load_regression_items(cassette_path)
    suite = RegressionSuiteResult()
    session = requests.Session()

    # 1. 20 Regression Entities on /api/v1/map/entity
    for idx, entity in enumerate(regression_entities, start=1):
        clean_name = "".join(c if c.isalnum() else "_" for c in entity["name"].lower()).strip("_")
        check_id = f"entity_{idx:02d}_{clean_name}"

        payload: dict[str, Any] = {
            "name": entity["name"],
            "entity_type": entity.get("entity_type"),
            "identifiers": entity.get("identifiers", {}),
        }
        resp = session.post(f"{api_url}/api/v1/map/entity", json=payload, timeout=timeout)
        resp.raise_for_status()

        norm = normalize_mapping_response(resp.json())
        norm_bytes = canonical_json_bytes(norm)
        suite.add_check(check_id, "entity", norm_bytes, norm)

    # 2. 10 Special Callsite Probes on /api/v1/map/entity
    for idx, probe in enumerate(special_probes, start=1):
        clean_name = "".join(c if c.isalnum() else "_" for c in probe["name"].lower()).strip("_")
        check_id = f"probe_{idx:02d}_{clean_name}"

        payload = {
            "name": probe["name"],
            "entity_type": probe.get("entity_type"),
            "identifiers": probe.get("identifiers", {}),
            "options": probe.get("options", {}),
        }
        resp = session.post(f"{api_url}/api/v1/map/entity", json=payload, timeout=timeout)
        resp.raise_for_status()

        norm = normalize_mapping_response(resp.json())
        norm_bytes = canonical_json_bytes(norm)
        suite.add_check(check_id, "probe", norm_bytes, norm)

    # 3. Batch Check: all 20 regression entities on /api/v1/map/batch
    batch_payload = {
        "entities": [
            {
                "name": e["name"],
                "entity_type": e.get("entity_type"),
                "identifiers": e.get("identifiers", {}),
            }
            for e in regression_entities
        ]
    }
    resp = session.post(f"{api_url}/api/v1/map/batch", json=batch_payload, timeout=timeout)
    resp.raise_for_status()

    norm_batch = normalize_mapping_response(resp.json())
    suite.add_check("batch_all_20", "batch", canonical_json_bytes(norm_batch), norm_batch)

    # 4. Dataset Stream: disease_reg.tsv and metab_reg.tsv on /api/v1/map/dataset/stream
    stream_datasets = [
        ("stream_disease_reg", DISEASE_REG_PATH, {"entity_type": "disease", "name_column": "name", "provided_id_columns": "icd10cm"}),
        ("stream_metab_reg", METAB_REG_PATH, {"entity_type": "metabolite", "name_column": "name", "provided_id_columns": "kegg,hmdb,chebi,pubchem,inchikey"}),
    ]
    for check_id, tsv_path, params in stream_datasets:
        with open(tsv_path, "rb") as f:
            resp = session.post(
                f"{api_url}/api/v1/map/dataset/stream",
                params=params,
                files={"file": (tsv_path.name, f.read(), "text/tab-separated-values")},
                timeout=timeout,
            )
        resp.raise_for_status()

        lines = [line.strip() for line in resp.text.splitlines() if line.strip()]
        canonical_lines = []
        parsed_lines = []
        for line in lines:
            parsed = json.loads(line)
            parsed_lines.append(parsed)
            canonical_lines.append(json.dumps(parsed, sort_keys=True, separators=(",", ":")))
        stream_bytes = ("\n".join(canonical_lines) + "\n").encode("utf-8")
        suite.add_check(check_id, "dataset_stream", stream_bytes, parsed_lines)

    # 5. Tabular Dataset: disease_reg.tsv and metab_reg.tsv on /api/v1/map/dataset
    dataset_runs = [
        ("dataset_disease_reg", DISEASE_REG_PATH, {"entity_type": "disease", "name_column": "name", "provided_id_columns": "icd10cm"}),
        ("dataset_metab_reg", METAB_REG_PATH, {"entity_type": "metabolite", "name_column": "name", "provided_id_columns": "kegg,hmdb,chebi,pubchem,inchikey"}),
    ]
    for check_id, tsv_path, params in dataset_runs:
        with open(tsv_path, "rb") as f:
            resp = session.post(
                f"{api_url}/api/v1/map/dataset",
                params=params,
                files={"file": (tsv_path.name, f.read(), "text/tab-separated-values")},
                timeout=timeout,
            )
        resp.raise_for_status()
        res_json = resp.json()

        output_file_path = Path(res_json["output_file"])
        tsv_content = output_file_path.read_bytes()
        norm_stats = normalize_dataset_stats(res_json["stats"])

        # Combined dataset record: raw tsv bytes + canonical normalized stats
        dataset_record = {
            "tsv_sha256": sha256_digest(tsv_content),
            "stats": norm_stats,
            "tsv_text": tsv_content.decode("utf-8"),
        }
        check_bytes = canonical_json_bytes(dataset_record)
        suite.add_check(check_id, "dataset", check_bytes, dataset_record)

    suite.finalize()
    return suite


def capture_golden_baseline(
    api_url: str,
    out_golden_path: Path | str = DEFAULT_GOLDEN_PATH,
    out_manifest_path: Path | str = DEFAULT_MANIFEST_PATH,
    cassette_path: Path | str = DEFAULT_CASSETTE_PATH,
) -> RegressionSuiteResult:
    """Run regression suite and save golden baseline fixtures."""
    suite = run_regression_suite(api_url, cassette_path=cassette_path)

    golden_path = Path(out_golden_path)
    manifest_path = Path(out_manifest_path)
    golden_path.parent.mkdir(parents=True, exist_ok=True)

    with gzip.open(golden_path, "wt", encoding="utf-8") as f:
        json.dump(suite.to_golden_dict(), f, indent=2)

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(suite.to_manifest_dict(), f, indent=2)

    logger.info("Saved golden baseline: suite_sha256=%s", suite.suite_sha256)
    return suite


def verify_against_golden(
    api_url: str,
    golden_path: Path | str = DEFAULT_GOLDEN_PATH,
    cassette_path: Path | str = DEFAULT_CASSETTE_PATH,
) -> tuple[bool, str, list[str]]:
    """Run regression suite and assert 100% SHA-256 match with golden baseline."""
    suite = run_regression_suite(api_url, cassette_path=cassette_path)

    path = Path(golden_path)
    if not path.exists():
        return False, suite.suite_sha256, [f"Golden baseline file not found: {path}"]

    with gzip.open(path, "rt", encoding="utf-8") as f:
        golden_data = json.load(f)

    expected_suite_sha256 = golden_data.get("suite_sha256")
    golden_checks = {c["check_id"]: c["sha256"] for c in golden_data.get("checks", [])}

    mismatches: list[str] = []
    current_checks = {c["check_id"]: c["sha256"] for c in suite.checks}

    for check_id, exp_sha in golden_checks.items():
        actual_sha = current_checks.get(check_id)
        if actual_sha != exp_sha:
            mismatches.append(f"Check {check_id} mismatch: actual={actual_sha}, expected={exp_sha}")

    for check_id in current_checks:
        if check_id not in golden_checks:
            mismatches.append(f"Unexpected new check: {check_id}")

    if suite.suite_sha256 != expected_suite_sha256:
        mismatches.append(
            f"Overall suite_sha256 mismatch: actual={suite.suite_sha256}, expected={expected_suite_sha256}"
        )

    matched = len(mismatches) == 0
    return matched, suite.suite_sha256, mismatches


def main() -> None:
    """CLI for capturing or verifying the healthy regression set."""
    parser = argparse.ArgumentParser(description="Regression Suite Runner & Golden Verifier")
    parser.add_argument("--api-url", default="http://127.0.0.1:18101", help="Biomapper2 API URL")
    parser.add_argument("--capture", action="store_true", help="Capture and save golden baseline")
    parser.add_argument("--verify", action="store_true", help="Verify against golden baseline")
    parser.add_argument("--golden-path", default=str(DEFAULT_GOLDEN_PATH), help="Path to golden_healthy.json.gz")
    parser.add_argument("--manifest-path", default=str(DEFAULT_MANIFEST_PATH), help="Path to manifest JSON")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if args.capture:
        suite = capture_golden_baseline(
            api_url=args.api_url,
            out_golden_path=args.golden_path,
            out_manifest_path=args.manifest_path,
        )
        print(f"Captured golden baseline: suite_sha256={suite.suite_sha256}")
        sys.exit(0)

    if args.verify:
        matched, suite_sha, mismatches = verify_against_golden(
            api_url=args.api_url,
            golden_path=args.golden_path,
        )
        if matched:
            print(f"VERIFIED: 100% SHA-256 match with golden baseline (suite_sha256={suite_sha})")
            sys.exit(0)
        else:
            print(f"FAILED: Mismatches detected (suite_sha256={suite_sha}):", file=sys.stderr)
            for m in mismatches:
                print(f"  - {m}", file=sys.stderr)
            sys.exit(1)

    # Default action: run and print manifest summary
    suite = run_regression_suite(api_url=args.api_url)
    print(json.dumps(suite.to_manifest_dict(), indent=2))


if __name__ == "__main__":
    main()
