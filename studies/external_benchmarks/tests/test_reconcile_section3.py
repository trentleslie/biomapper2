"""Every numeric claim in the results section resolves to a named artifact field.

The source-prose guard covers files in this repository. The manuscript is not one of them, so the
surface it protects is not the surface at risk: a number can be correct in the artifact, stale in
the prose, and nothing turns red. These tests close that gap from both ends.

* **Resolution** — every claim in the committed inventory either names a field, or names the
  blocker that stops it from naming one. Nothing is left implicitly unverified.
* **Rename detection** — a field the artifact no longer has must break the check. Silent renaming
  is the dangerous failure: the claim keeps reading as backed while nothing backs it.
* **Completeness** — every measurement-shaped number in the committed copy of the prose is
  accounted for by the inventory or by an explicit not-a-measurement entry. Resolving the claims
  we listed says nothing about the claims we forgot to list.

Drift between the manuscript's value and the artifact's value is reported separately and is not a
test failure: the manuscript predates the current run, so drift is a restatement task. Conflating
it with a rename would leave the check unable to fail for the right reason.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from studies.analysis import confidence_report as cr
from studies.external_benchmarks import reconcile_section3 as rs


@pytest.fixture
def claims():
    return rs.load_claims()


@pytest.fixture
def artifact_path():
    path = rs.latest_interval_artifact()
    if path is None:
        pytest.skip("no committed interval artifact in this tree")
    return path


@pytest.fixture
def artifact(artifact_path):
    return json.loads(artifact_path.read_text())


class TestInventoryStructure:
    def test_the_manuscript_copy_is_committed(self):
        """The check runs against a copy in this repository, not against a file elsewhere that
        could change without anyone here noticing."""
        assert rs.SOURCE_PATH.exists()
        assert rs.SOURCE_PATH.read_text().strip()

    def test_every_claim_either_names_a_field_or_names_its_blocker(self, claims):
        for entry in claims["claims"]:
            resolves = bool(entry["row_id"]) and bool(entry["field"])
            assert resolves or entry["blocked_by"], f"{entry['id']} is neither resolved nor blocked"

    def test_every_claim_names_a_known_artifact(self, claims):
        for entry in claims["claims"]:
            assert entry["artifact"] in claims["artifacts"], entry["id"]

    def test_claim_ids_are_unique(self, claims):
        ids = [entry["id"] for entry in claims["claims"]]
        assert len(set(ids)) == len(ids)

    def test_a_blocked_claim_gives_a_reason_a_reader_can_act_on(self, claims):
        for entry in claims["claims"]:
            if entry["blocked_by"]:
                assert len(entry["blocked_by"]) > 20, entry["id"]


class TestRenameDetection:
    def test_no_claim_currently_names_a_missing_field(self, claims, artifact):
        """The CI-enforceable invariant. Drift is allowed; a dangling field reference is not."""
        result = rs.reconcile(claims, artifact)
        assert result["renamed"] == [], result["renamed"]
        assert result["ok"] is True

    def test_renaming_a_row_turns_the_check_red(self, claims, artifact):
        """Red-green on the guard itself. A guard that cannot fail is not a guard."""
        mutated = json.loads(json.dumps(artifact))
        target = next(entry for entry in claims["claims"] if entry["row_id"] and not entry["blocked_by"])
        for row in mutated["rows"]:
            if row["row_id"] == target["row_id"]:
                row["row_id"] = row["row_id"] + "-renamed"
        result = rs.reconcile(claims, mutated)
        assert any(item["id"] == target["id"] for item in result["renamed"])
        assert result["ok"] is False

    def test_dropping_a_field_from_a_row_turns_the_check_red(self, claims, artifact):
        mutated = json.loads(json.dumps(artifact))
        for row in mutated["rows"]:
            row.pop("k", None)
        result = rs.reconcile(claims, mutated)
        assert result["renamed"]
        assert any("field" in item["reason"] for item in result["renamed"])

    def test_a_matching_field_is_not_reported_as_renamed(self, claims, artifact):
        result = rs.reconcile(claims, artifact)
        resolved_ids = {item["id"] for item in result["resolved"]}
        renamed_ids = {item["id"] for item in result["renamed"]}
        assert not (resolved_ids & renamed_ids)


class TestDriftIsSeparateFromRename:
    def test_drift_against_the_reference_suite_is_reported_not_hidden(self, claims, artifact):
        """The manuscript predates the current run, so several claims must show as needing
        restatement. A reconciliation reporting none of them would mean it is not comparing."""
        result = rs.reconcile(claims, artifact)
        assert result["restatement_required"] is True
        assert result["drifted"]

    def test_a_drifted_claim_is_still_counted_as_resolved(self, claims, artifact):
        result = rs.reconcile(claims, artifact)
        resolved_ids = {item["id"] for item in result["resolved"]}
        for item in result["drifted"]:
            assert item["id"] in resolved_ids

    def test_matching_a_claim_to_the_artifact_clears_its_drift(self, claims, artifact):
        """Constructed proof that drift tracks the values rather than always firing."""
        mutated = json.loads(json.dumps(artifact))
        target = next(
            entry
            for entry in claims["claims"]
            if entry["row_id"]
            and not entry["blocked_by"]
            and isinstance(entry["manuscript_value"], dict)
            and entry["manuscript_value"].get("k") is not None
        )
        for row in mutated["rows"]:
            if row["row_id"] == target["row_id"]:
                row["k"] = target["manuscript_value"]["k"]
                row["n"] = target["manuscript_value"]["n"]
        result = rs.reconcile(claims, mutated)
        assert target["id"] not in {item["id"] for item in result["drifted"]}


class TestCompleteness:
    def test_no_measurement_shaped_number_in_the_prose_is_unclassified(self, claims):
        """The half that catches an omission rather than a mismatch.

        A number that never enters the inventory is exactly the one that reaches print unbacked,
        and no amount of checking the listed claims will find it.
        """
        unclassified = rs.unclassified_prose_numbers(claims, rs.SOURCE_PATH.read_text())
        assert unclassified == [], unclassified

    def test_adding_an_unclassified_number_to_the_prose_turns_the_check_red(self, claims):
        text = rs.SOURCE_PATH.read_text() + "\n\nBioMapper resolved 1,234 of the 5,678 held-out rows.\n"
        assert rs.unclassified_prose_numbers(claims, text)

    def test_every_not_a_measurement_entry_gives_its_reason(self, claims):
        for token, reason in claims["not_a_measurement"].items():
            assert reason, token

    def test_links_and_code_spans_are_not_scanned(self):
        """A figure filename or a url is not a claim; treating it as one would force noise into
        the allowlist until the allowlist stopped meaning anything."""
        text = "![Figure 4. Determinism.](assets/Fig4_determinism.png) and `CHEBI:16856`."
        assert rs.prose_numbers(text) == []


class TestArtifactBinding:
    def test_the_artifact_the_check_reads_names_its_suite_and_commit(self, artifact):
        assert artifact["header"]["suite_id"]
        assert artifact["header"]["git_sha"]

    def test_the_report_the_claims_bind_to_is_the_one_this_repository_builds(self, artifact):
        """Guards against the claims drifting onto a hand-made file: the artifact must be readable
        by the same code that writes it."""
        assert set(artifact) >= {"header", "rows", "missing_datasets", "off_category_weighting"}
        assert cr.INDEPENDENCE_ROLES
        for row in artifact["rows"]:
            assert row["independence_role"] in cr.INDEPENDENCE_ROLES

    def test_no_claim_binds_to_a_row_that_the_registry_could_never_produce(self, claims):
        """A claim naming a dataset with no registered reader can never be satisfied, so it is a
        typo rather than an outstanding task."""
        for entry in claims["claims"]:
            if not entry["row_id"] or entry["artifact"] != "confidence_intervals":
                continue
            if entry["blocked_by"]:
                continue  # a blocked claim names the identifier it WILL bind to once unblocked
            dataset = entry["row_id"].split(":", 1)[0]
            assert dataset in cr.REGISTRY, f"{entry['id']} names dataset {dataset!r}, which has no reader"


def test_the_claims_file_is_regenerated_by_its_builder():
    """The inventory is generated, not hand-edited, so the committed copy must match the builder."""
    from studies.external_benchmarks.build_section3_claims import build

    assert json.loads(rs.CLAIMS_PATH.read_text()) == json.loads(json.dumps(build()))


def test_reconciliation_report_is_writable_next_to_the_artifact(tmp_path, claims, artifact):
    """The reconciliation itself is an artifact: a check whose result is only ever printed leaves
    nothing a reviewer can point at."""
    result = rs.reconcile(claims, artifact)
    out = tmp_path / "reconciliation.json"
    out.write_text(json.dumps(result, indent=2))
    assert json.loads(out.read_text())["n_claims"] == len(claims["claims"])
    assert Path(out).exists()
