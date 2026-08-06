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
from studies.analysis import reconcile_section3 as rs


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
    def test_drift_is_reported_not_hidden(self, artifact):
        """A claim that disagrees with its artifact must be reported and must fail the check.

        This used to assert that the COMMITTED manuscript drifted -- "the manuscript predates the
        current run, so several claims must show as needing restatement." That encoded the stale
        state as the expected state: it passed because nineteen internal-host figures were sitting
        in the source, and it would have turned red the moment someone corrected them. A test whose
        precondition is a defect cannot survive the defect being fixed.

        Rewritten against a fixture, so it asserts the checker's behaviour rather than the
        manuscript's condition, and keeps working once the source is clean.
        """
        row = next(r for r in artifact["rows"] if r.get("k") is not None)
        drifted_claims = {
            "claims": [
                {
                    "id": "fixture.drifted",
                    "manuscript_value": {"k": row["k"] + 7, "n": row["n"]},
                    "kind": "counts",
                    "artifact": "confidence_intervals",
                    "row_id": row["row_id"],
                    "field": "k,n",
                    "blocked_by": None,
                    "note": "",
                }
            ],
            "not_a_measurement": {},
        }
        result = rs.reconcile(drifted_claims, artifact)
        assert result["drifted"], "a claim disagreeing with its artifact must be reported"
        assert result["restatement_required"] is True
        assert result["ok"] is False, "drift must fail the check, not merely annotate it"

    def test_the_committed_manuscript_does_not_drift(self, claims, artifact):
        """The live control: every §3 figure agrees with the pinned public-backend artifact."""
        result = rs.reconcile(claims, artifact)
        assert result["drifted"] == [], result["drifted"]

    def test_a_drifted_claim_is_still_counted_as_resolved(self, claims, artifact):
        result = rs.reconcile(claims, artifact)
        resolved_ids = {item["id"] for item in result["resolved"]}
        for item in result["drifted"]:
            assert item["id"] in resolved_ids

    # ------------------------------------------------------------------------------------------
    # Red-green pins for the field-resolution repair.
    #
    # The repair itself was verified by hand and the commit message said so -- which is the same
    # mistake one level up: a control a reader cannot re-run is not a control, and the module this
    # file guards exists precisely because a check reported ok while real disagreement sat in the
    # source. Without these, reverting ``_has_drifted`` to the form that compared every claim
    # against ``row["k"]/row["n"]`` leaves the whole suite green.
    # ------------------------------------------------------------------------------------------

    @staticmethod
    def _override(claims: dict, claim_id: str, manuscript_value) -> dict:
        mutated = json.loads(json.dumps(claims))
        target = next(entry for entry in mutated["claims"] if entry["id"] == claim_id)
        target["manuscript_value"] = manuscript_value
        target["blocked_by"] = None
        return mutated

    def test_a_k_less_coverage_claim_is_checked_against_the_field_it_names(self, claims, artifact):
        """POSITIVE control. The exact shape the old form accepted without comparing anything.

        ``necs.delivered_metabolites`` names ``coverage`` and carries no ``k``. Pointed at the
        SCORED-row denominator instead of ``coverage.total`` it must be reported as drift; the old
        code returned False on any k-less claim and never looked.
        """
        mutated = self._override(claims, "necs.delivered_metabolites", {"k": None, "n": 796})
        result = rs.reconcile(mutated, artifact)
        assert "necs.delivered_metabolites" in {item["id"] for item in result["drifted"]}
        assert result["ok"] is False

    def test_a_correct_k_less_coverage_claim_stays_quiet(self, claims, artifact):
        """NEGATIVE control, over the FULL committed set.

        Pinned across every claim rather than one, because the first attempt at this repair omitted
        ``k,n`` from the field whitelist and turned twelve correct claims into false drift. A
        positive control alone would not have caught that.
        """
        result = rs.reconcile(claims, artifact)
        assert result["drifted"] == [], result["drifted"]

    def test_a_claim_naming_a_field_the_check_cannot_read_is_reported(self, claims, artifact):
        """An unreadable field must be drift, never silent agreement.

        The failure being prevented is a claim that resolves to nothing while reporting as backed --
        the shape that let unbacked figures reach print.
        """
        mutated = self._override(claims, "necs.delivered_metabolites", {"k": None, "n": 1495})
        target = next(e for e in mutated["claims"] if e["id"] == "necs.delivered_metabolites")
        target["field"] = "half_width_pt"
        result = rs.reconcile(mutated, artifact)
        assert "necs.delivered_metabolites" in {item["id"] for item in result["drifted"]}
        assert result["ok"] is False

    def test_a_coverage_claim_resolves_its_numerator_from_coverage_too(self, claims, artifact):
        """A coverage claim must not borrow its numerator from the scored rows.

        Dormant on today's claim set (both k-bearing coverage claims are blocked), and pinned now
        so it cannot wake up silently when the Pham source is reconstructed.
        """
        row = next(
            r
            for r in artifact["rows"]
            if isinstance(r.get("coverage"), dict)
            and r["coverage"].get("n_predicted") is not None
            and r.get("k") is not None
            and r["k"] != r["coverage"]["n_predicted"]
        )
        hybrid = {
            "claims": [
                {
                    "id": "fixture.hybrid_coverage",
                    "manuscript_value": {"k": row["k"], "n": row["coverage"]["total"]},
                    "kind": "counts",
                    "artifact": "confidence_intervals",
                    "row_id": row["row_id"],
                    "field": "coverage",
                    "blocked_by": None,
                    "note": "",
                }
            ],
            "not_a_measurement": {},
        }
        result = rs.reconcile(hybrid, artifact)
        assert result["drifted"], "a scored-row numerator under a coverage field must be reported"

    @pytest.mark.parametrize(
        "label,mutate",
        [
            ("total_key_removed", lambda cov: cov.pop("total", None)),
            ("total_is_none", lambda cov: cov.update(total=None)),
        ],
    )
    def test_an_unreadable_coverage_field_is_drift_not_agreement(self, claims, artifact, label, mutate):
        """An unreadable field must never read as agreement.

        The rename check is TOP-LEVEL only -- ``[k for k in field.split(",") if k not in row]`` --
        so it cannot see a missing ``coverage`` sub-key and cannot see present-but-None. These
        paths once returned False with a comment claiming the rename check had already reported
        them. It had not: the whole reconciliation returned ok=True with nothing compared.
        """
        mutated = json.loads(json.dumps(artifact))
        for row in mutated["rows"]:
            if isinstance(row.get("coverage"), dict):
                mutate(row["coverage"])
        result = rs.reconcile(claims, mutated)
        assert result["drifted"], f"{label}: an unreadable coverage field must be reported"
        assert result["ok"] is False

    @pytest.mark.parametrize("field_key", ["n", "k"])
    def test_a_present_but_null_row_field_is_drift_not_agreement(self, claims, artifact, field_key):
        """Present-but-None is invisible to the rename check, so the drift check must catch it."""
        mutated = json.loads(json.dumps(artifact))
        for row in mutated["rows"]:
            row[field_key] = None
        result = rs.reconcile(claims, mutated)
        assert result["drifted"], f"row[{field_key!r}] = None must be reported"
        assert result["ok"] is False

    @pytest.mark.parametrize(
        "coverage,expected",
        [
            ({"total": 1500}, True),  # n_predicted absent -> compared against nothing
            ({"n_predicted": None, "total": 1500}, True),  # ... and present-but-None
            ({"n_predicted": 1499, "total": 1500}, False),  # readable and correct
        ],
    )
    def test_a_k_bearing_coverage_claim_needs_a_readable_numerator(self, coverage, expected):
        """Closing one silent pass must not open another.

        Before the numerator fix a k-bearing coverage claim was compared against ``row["k"]`` --
        the wrong field, which is why it was fixed. After it, an absent ``coverage.n_predicted``
        compared it against nothing at all. Unreachable from today's claim set (both k-bearing
        coverage claims are blocked) and pinned before the Pham source unblocks them.
        """
        entry = {"manuscript_value": {"k": 1499, "n": 1500}, "field": "coverage"}
        row = {"k": 255, "n": 1500, "coverage": coverage}
        assert rs._has_drifted(entry, row) is expected

    @pytest.mark.parametrize(
        "field,expected",
        [
            ("rate", False),  # names the field it is actually compared against
            ("coverage", True),  # coverage.fraction is a different quantity from rate
            ("half_width_pt", True),  # a field this check cannot read
        ],
    )
    def test_a_scalar_claim_is_dispatched_on_the_field_it_names(self, artifact, field, expected):
        """The field dispatch must cover BOTH value shapes.

        It was added to the dict branch only, so every scalar claim went on being compared against
        ``row["rate"]`` whatever field it named -- a coverage rate reporting agreement with the
        scored-subsample accuracy. Dormant on today's claim set (all live scalar claims name
        ``rate``) and pinned before a coverage-shaped rate claim is written.
        """
        row = next(
            r
            for r in artifact["rows"]
            if r.get("rate") is not None
            and isinstance(r.get("coverage"), dict)
            and r["coverage"].get("fraction") is not None
            and abs(r["coverage"]["fraction"] - r["rate"]) > 0.01
        )
        entry = {"manuscript_value": row["rate"], "field": field}
        assert rs._has_drifted(entry, row) is expected

    @pytest.mark.parametrize(
        "manuscript_value,expected",
        [
            ({"k": 999999}, True),  # numerator wrong, no denominator asserted
            ({"k": 999999, "n": None}, True),  # ... and explicitly null
            ({"n": 999999}, True),  # denominator wrong, no numerator asserted
            ({"k": None, "n": None}, True),  # asserts nothing: not a comparison
        ],
    )
    def test_a_claim_is_checked_on_whichever_side_it_asserts(self, artifact, manuscript_value, expected):
        """``n``-less and ``k``-less must be symmetric.

        The k-less case was fixed while the n-less case still returned agreement, so a claim
        asserting only a numerator was never compared -- a manuscript count wrong by three orders
        of magnitude read as artifact-backed.
        """
        row = next(r for r in artifact["rows"] if r.get("k") is not None and r.get("n") is not None)
        entry = {"manuscript_value": manuscript_value, "field": "k,n"}
        assert rs._has_drifted(entry, row) is expected

    def test_a_correct_single_sided_claim_still_stays_quiet(self, artifact):
        """Guards the guard above: single-sided checking must not fire on a CORRECT claim."""
        row = next(r for r in artifact["rows"] if r.get("k") is not None and r.get("n") is not None)
        assert rs._has_drifted({"manuscript_value": {"k": row["k"]}, "field": "k,n"}, row) is False
        assert rs._has_drifted({"manuscript_value": {"n": row["n"]}, "field": "k,n"}, row) is False

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
    from studies.analysis.build_section3_claims import build

    assert json.loads(rs.CLAIMS_PATH.read_text()) == json.loads(json.dumps(build()))


def test_reconciliation_report_is_writable_next_to_the_artifact(tmp_path, claims, artifact):
    """The reconciliation itself is an artifact: a check whose result is only ever printed leaves
    nothing a reviewer can point at."""
    result = rs.reconcile(claims, artifact)
    out = tmp_path / "reconciliation.json"
    out.write_text(json.dumps(result, indent=2))
    assert json.loads(out.read_text())["n_claims"] == len(claims["claims"])
    assert Path(out).exists()


class TestTheCompletenessCheckCanFailOnTheFormatSection3Uses:
    """Red-green controls for the classifier itself.

    The completeness half of this check was live for a full review cycle while being structurally
    incapable of seeing the number format Section 3 is mostly written in. ``_MEASUREMENT_SHAPED``
    was inherited from the source-prose guard, which is tuned for code comments, and required three
    digits before the decimal point; every proportion in the head-to-head table is one digit and a
    fraction. ``unclassified_prose_numbers`` returned an empty list against a document containing
    ten unaccounted cells, and the suite was green.

    A guard that cannot fail on the format it exists to catch is not a guard. These tests make the
    failure mode reachable, so the blind spot cannot silently return.
    """

    def test_a_decimal_proportion_with_no_claim_is_reported(self):
        """The exact defect: a bare proportion, unaccounted, must surface."""
        claims = {"claims": [], "not_a_measurement": {}}
        text = "The tool reached 0.791 on the Ensembl namespace."
        assert rs.unclassified_prose_numbers(claims, text) == ["0.791"]

    def test_a_decimal_proportion_with_a_claim_is_not_reported(self):
        """The other half: accounting for it must actually silence it.

        This is what catches a regression in ``_token_forms`` rather than in the classifier. Three
        decimal places were missing there too, so a correctly-inventoried claim still read as
        unaccounted -- the two defects concealed each other, because nothing ever surfaced a
        three-decimal token for the accounting side to fail on.
        """
        claims = {"claims": [{"manuscript_value": 0.791}], "not_a_measurement": {}}
        text = "The tool reached 0.791 on the Ensembl namespace."
        assert rs.unclassified_prose_numbers(claims, text) == []

    def test_small_bare_integers_are_still_structural(self):
        """The rule must not swing the other way: 'two arms' is not a measurement."""
        claims = {"claims": [], "not_a_measurement": {}}
        assert rs.unclassified_prose_numbers(claims, "We ran 3 arms across 2 modes.") == []

    def test_the_committed_section_has_no_unaccounted_numbers(self):
        """The live document, as an end-to-end control over the two tests above."""
        claims = json.loads(rs.CLAIMS_PATH.read_text())
        assert rs.unclassified_prose_numbers(claims, rs.SOURCE_PATH.read_text()) == []


class TestBlockedClaimsArePinned:
    """The unresolved pile must not grow silently.

    ``reconcile()`` computes ``ok`` from renamed and drifted only, so a claim moved to
    ``blocked_by`` stops being checked without failing anything -- and it stays in the completeness
    inventory, so it still reads as accounted-for. That is the right escape hatch for a figure with
    no committed artifact, but it is only honest if each use is a deliberate, reviewed edit.

    Pinning the exact set makes adding one a visible diff rather than a silent subtraction from what
    the check covers. Removing one (because its artifact landed) is equally visible.
    """

    EXPECTED_BLOCKED = {
        "competitors.uniprot_scoring_artifact",
        "determinism.biomapper_accuracy",
        "determinism.opus_accuracy",
        "determinism.qwen_accuracy",
        "hajjar.charge_normalized_estimate",
        "hajjar.strict",
        "headtohead.biodbnet.ensembl",
        "headtohead.biodbnet.ncbigene",
        "headtohead.biodbnet.union",
        "headtohead.biodbnet.uniprot",
        "headtohead.biodbnet.uniprot_precorrection",
        "headtohead.gconvert.ensembl",
        "headtohead.gconvert.ncbigene",
        "headtohead.gconvert.union",
        "headtohead.gconvert.uniprot",
        "headtohead.gconvert.uniprot_precorrection",
        "headtohead.uniprot_idmapping.union",
        "headtohead.uniprot_idmapping.uniprot",
        "lmsd.subsample_population",
        "metabench.best_closed_book_lm",
        "metabench.best_retrieval_augmented_lm",
        "metabench.pre_fix_harness_output",
        "metaboliteannotator.id_concordance_negative",
        "metaboliteannotator.id_concordance_positive",
        "metaboliteannotator.negative",
        "metaboliteannotator.published_negative",
        "metaboliteannotator.published_negative_denominator",
        "metaboliteannotator.published_positive",
        "metlinkr.published_curator_agreement",
        "ms1.all_namespace_agreement",
        "ms1.any_namespace_agreement",
        "ms1.chebi_agreement",
        "ms1.comparable_features",
        "ms1.hmdb_agreement",
        "ms1.inchikey_agreement",
        "ms1.kegg_agreement",
        "ms1.lipidmaps_agreement",
        "ms1.panel_comparability",
        "ms1.residual_disagreement",
        "pham.ambiguity_rate_published",
        "pham.ambiguous_population",
        "pham.gold_cross_check",
        "pham.lipid_stratum",
        "pham.non_lipid_membership",
        "provided_id.ncbigene_to_ensembl",
        "refmet.source_population",
    }

    def test_the_blocked_set_is_exactly_what_was_reviewed(self, claims):
        blocked = {entry["id"] for entry in claims["claims"] if entry["blocked_by"]}
        added = blocked - self.EXPECTED_BLOCKED
        removed = self.EXPECTED_BLOCKED - blocked
        assert not added, (
            f"claims newly excluded from the drift check: {sorted(added)}. If deliberate, add them "
            "here with the reason in blocked_by -- an unbacked number must not become unbacked "
            "silently."
        )
        assert not removed, (
            f"claims no longer blocked: {sorted(removed)}. If their artifact landed, remove them "
            "here so the pin tracks reality."
        )
