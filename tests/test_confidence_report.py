"""End-to-end report generation over a committed fixture suite. No network, no live suite.

The fixture reproduces every result shape the real suite emits, including the ones that differ
enough to break a single generic reader: a dataset with no results file of the conventional name, a
dataset whose per-row correctness key is neither ``correct`` nor ``hit``, a dataset whose results
are wrapped under an extra level, a dataset carrying three correctness flags over the same rows,
and a dataset that is *absent* because its run failed.

That last one is the whole reason this is a registry and not a glob. A glob silently drops what it
does not match, and a silently-dropped dataset is indistinguishable from a dataset that scored
badly. The reader must be able to say "this dataset is missing, and here is why".
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from studies.analysis import confidence_report as cr

PINS = {
    "backend": "https://kestrel.example.invalid/api",
    "biolink_version": "4.2.5",
    "git_sha": "0123456789abcdef0123456789abcdef01234567",
    "kg_snapshot": "kraken 2.0.1 (10n/20e)",
    "chebi_release": "unrecorded",
    "chebi_node_count": 4321,
    "kg_metagraph": {"graph": "kraken", "version": "2.0.1", "summary": {"total_nodes": 10, "total_edges": 20}},
}


def _rows(n, correct, charge_extra=0, eq_extra=0, name_source=None, prefix="q"):
    """Per-row records with nested correctness flags: strict ⊆ charge-normalized ⊆ equivalence-set."""
    out = []
    for i in range(n):
        is_correct = i < correct
        is_charge = i < correct + charge_extra
        is_eq = i < correct + charge_extra + eq_extra
        out.append(
            {
                "name": f"{prefix}-{i:04d}",
                "chosen_kg_id": f"CHEBI:{1000 + i}",
                "gold_block": "AAAAAAAAAAAAAA",
                "predicted_block": "AAAAAAAAAAAAAA" if is_correct else None,
                "scored": True,
                "correct": is_correct,
                "needed_fallback": False,
                "charge_normalized_correct": is_charge,
                "kg_equivalence_set_correct": is_eq,
                "name_source": name_source,
            }
        )
    return out


def _core(metric, k, n):
    return {"metric": metric, "top1_accuracy": k / n, "correct": k, "scored_denominator": n}


@pytest.fixture
def fixture_suite(tmp_path):
    suite = tmp_path / "suite_FIXTURE"
    suite.mkdir()

    def write(rel, payload):
        path = suite / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))

    # refmet: three nested correctness flags over one row set.
    refmet_rows = _rows(100, 80, charge_extra=1, eq_extra=4)
    write(
        "refmet/CHEBI_results.json",
        {
            "vocab": "CHEBI",
            "input_type": "name",
            "comparable_core": _core("top1_accuracy", 80, 100),
            "comparable_core_charge_normalized": _core("top1_accuracy_charge_normalized", 81, 100),
            "comparable_core_kg_equivalence_set": _core("top1_accuracy_kg_equivalence_set", 85, 100),
            "by_name_source_regime": None,
            "coverage": {"n_predicted": 100, "total": 100, "fraction": 1.0},
            "per_row": refmet_rows,
        },
    )

    # lmsd: the regime split, where carrying one blended row hides a two-fold precision difference.
    lmsd_rows = _rows(30, 12, name_source="common_name", prefix="cs") + _rows(
        70, 4, name_source="shorthand", prefix="sh"
    )
    write(
        "lmsd/CHEBI_results.json",
        {
            "vocab": "CHEBI",
            "input_type": "name",
            "comparable_core": _core("top1_accuracy", 16, 100),
            "comparable_core_charge_normalized": _core("top1_accuracy_charge_normalized", 16, 100),
            "comparable_core_kg_equivalence_set": _core("top1_accuracy_kg_equivalence_set", 16, 100),
            "by_name_source_regime": {
                "common_systematic": {
                    "comparable_core": _core("top1_accuracy", 12, 30),
                    "comparable_core_charge_normalized": _core("top1_accuracy_charge_normalized", 12, 30),
                    "n_rows": 30,
                    "coverage": {"n_predicted": 30, "total": 30, "fraction": 1.0},
                },
                "shorthand": {
                    "comparable_core": _core("top1_accuracy", 4, 70),
                    "comparable_core_charge_normalized": _core("top1_accuracy_charge_normalized", 4, 70),
                    "n_rows": 70,
                    "coverage": {"n_predicted": 70, "total": 70, "fraction": 1.0},
                },
            },
            "coverage": {"n_predicted": 100, "total": 100, "fraction": 1.0},
            # Names drawn from several homologous lipid series, so a cluster key exists and the
            # cluster-robust companion is computable. One class throughout would leave no
            # between-cluster information at all.
            "per_row": [
                dict(r, name=f"{['TG', 'PC', 'PE', 'SM'][i % 4]} {40 + i}:{i % 7}") for i, r in enumerate(lmsd_rows)
            ],
        },
    )

    # srm1950: a single reference material, so items are not independent draws from a population.
    write(
        "srm1950/CHEBI_results.json",
        {
            "vocab": "CHEBI",
            "input_type": "name",
            "comparable_core": _core("top1_accuracy", 40, 90),
            "comparable_core_charge_normalized": _core("top1_accuracy_charge_normalized", 41, 90),
            "comparable_core_kg_equivalence_set": _core("top1_accuracy_kg_equivalence_set", 45, 90),
            "by_name_source_regime": None,
            "coverage": {"n_predicted": 95, "total": 100, "fraction": 0.95},
            "per_row": _rows(90, 40, charge_extra=1, eq_extra=4, prefix="srm"),
        },
    )

    write(
        "necs/CHEBI_results.json",
        {
            "vocab": "CHEBI",
            "input_type": "name",
            "comparable_core": _core("top1_accuracy", 60, 80),
            "comparable_core_charge_normalized": _core("top1_accuracy_charge_normalized", 61, 80),
            "comparable_core_kg_equivalence_set": _core("top1_accuracy_kg_equivalence_set", 66, 80),
            "by_name_source_regime": None,
            "coverage": {"n_predicted": 80, "total": 80, "fraction": 1.0},
            "per_row": _rows(80, 60, charge_extra=1, eq_extra=5, prefix="necs"),
        },
    )

    # hgnc: per-namespace subsets that overlap, plus an any-namespace union over them.
    write(
        "hgnc/ENSEMBL_results.json",
        {
            "vocab": "ENSEMBL",
            "arm": "gene",
            "input_type": "name",
            "comparable_core": _core("top1_accuracy", 96, 100),
            "coverage": {"n_predicted": 100, "total": 100, "fraction": 1.0},
            "curie_stats": {"precision": 0.9, "recall": 0.9, "f1": 0.9, "predicted_and_gold": 90},
            "per_namespace": {
                "ENSEMBL": {"correct": 70, "scored": 95},
                "NCBIGene": {"correct": 94, "scored": 98},
                "UniProtKB": {"correct": 40, "scored": 45},
            },
            "per_row": [
                {"query": f"G{i}", "predicted": [], "gold": [], "scored": True, "correct": i < 96} for i in range(100)
            ],
        },
    )

    # metabench: sub-rows that partition the whole exactly, so the overall row is derived.
    write(
        "metabench/metabench-grounding_results.json",
        {
            "dataset": "metabench-grounding",
            "arm": "metabolite",
            "input_type": "mixed",
            "mode": "metabench_grounding",
            "comparable_core": _core("top1_accuracy", 52, 100),
            "coverage": {"n_predicted": 100, "total": 100, "fraction": 1.0},
            "per_namespace": {
                "KEGG": {"correct": 30, "scored": 40},
                "HMDB": {"correct": 7, "scored": 40},
                "CHEBI": {"correct": 15, "scored": 20},
            },
            "per_row": [
                {"query": f"m{i}", "target_namespace": "KEGG", "scored": True, "correct": i < 52} for i in range(100)
            ],
        },
    )

    # metaboliteannotator: per-mode subdirectories, per-row key is `hit`, no gold/predicted pair.
    write(
        "metaboliteannotator/positive/name_hit_results.json",
        {
            "vocab": "CHEBI+HMDB+PUBCHEM+KEGG",
            "mode": "positive",
            "input_type": "name",
            "comparable_core": {"metric": "name_hit_rate", "name_hit_rate": 0.95, "matched": 95, "total": 100},
            "per_row": [
                {"name": f"n{i}", "chosen_kg_id": "CHEBI:1", "hit": i < 95, "id_concordant": False} for i in range(100)
            ],
        },
    )

    # metlinkr: no per-row list on the top-level object; the correctness key is `concordant`.
    write(
        "metlinkr/metlinkr_results.json",
        {
            "vocab": "CHEBI+HMDB",
            "input_type": "name",
            "curator_agreement": {
                "metric": "curator_agreement_rate",
                "curator_agreement_rate": 0.83,
                "linked": 83,
                "curator_cross_pairs": 100,
            },
            "inchikey_structural_concordance": {
                "metric": "inchikey_structural_concordance",
                "scored": 60,
                "concordant": 50,
                "concordance_rate": 50 / 60,
                "needs_verification": 2,
                "needs_verification_rows": [],
                "gold_resolution": "independent_external_pubchem_pugrest",
                "struct_per_row": [{"input_row_id": f"f:{i}", "concordant": i < 50} for i in range(60)],
                "struct_per_row_covers_all_rows": False,
            },
            "n_rows": 120,
        },
    )

    # hajjar: results wrapped under an extra level.
    write(
        "hajjar/CHEBI_results.json",
        {
            "structure": {"comparable_core": _core("top1_accuracy", 81, 100), "per_row": _rows(100, 81, prefix="h")},
            "paper": {"note": "round-trip consistency counts on identifier inputs; not the same task"},
        },
    )

    # nlmgene: NO conventionally-named results file at all. Two differently-named ones instead.
    write("nlmgene/unambiguous_accuracy.json", {"correct": 700, "scored": 1000, "metric": "unambiguous_accuracy"})
    write("nlmgene/ambiguous_flagrate.json", {"flagged": 120, "total": 400, "metric": "ambiguous_flag_rate"})

    manifest = {
        "suite_out_dir": str(suite),
        "created": "20260101T000000Z",
        "pins": PINS,
        "datasets": [
            {"dataset": "metabench", "status": "ok", "out_dir": str(suite / "metabench")},
            {"dataset": "necs", "status": "ok", "out_dir": str(suite / "necs")},
            {"dataset": "hgnc", "status": "ok", "out_dir": str(suite / "hgnc")},
            {"dataset": "metaboliteannotator", "status": "failed", "error": "negative arm returned a server error"},
            {"dataset": "metlinkr", "status": "ok", "out_dir": str(suite / "metlinkr")},
            {"dataset": "nlmgene", "status": "ok", "out_dir": str(suite / "nlmgene")},
            {"dataset": "refmet", "status": "ok", "out_dir": str(suite / "refmet")},
            {"dataset": "srm1950", "status": "ok", "out_dir": str(suite / "srm1950")},
            {"dataset": "lmsd", "status": "ok", "out_dir": str(suite / "lmsd")},
            {"dataset": "swisslipids", "status": "failed", "error": "join collision in the mapper"},
            {"dataset": "hajjar", "status": "ok", "out_dir": str(suite / "hajjar")},
        ],
    }
    (suite / "suite_manifest.json").write_text(json.dumps(manifest, indent=2))
    return suite


@pytest.fixture
def report(fixture_suite):
    return cr.build_report(fixture_suite)


# --------------------------------------------------------------------------------------------
# The registry, and the silent-drop failure mode it exists to prevent
# --------------------------------------------------------------------------------------------
class TestRegistryCoverage:
    def test_every_suite_dataset_is_registered(self):
        """A dataset that falls out of the registry must break the build, not vanish from the table."""
        from studies.external_benchmarks.run import SUITE_DATASETS, SUITE_SKIPPED

        for key in list(SUITE_DATASETS) + list(SUITE_SKIPPED):
            assert key in cr.REGISTRY, f"{key} is a suite dataset with no registered reader"

    def test_an_unregistered_dataset_raises(self, fixture_suite):
        manifest = json.loads((fixture_suite / "suite_manifest.json").read_text())
        manifest["datasets"].append({"dataset": "brand-new-benchmark", "status": "ok", "out_dir": "x"})
        (fixture_suite / "suite_manifest.json").write_text(json.dumps(manifest))
        with pytest.raises(cr.UnregisteredDatasetError, match="brand-new-benchmark"):
            cr.build_report(fixture_suite)

    def test_an_absent_dataset_is_reported_as_missing_not_skipped(self, report):
        """The distinction the whole registry exists to preserve.

        A dataset whose run failed leaves no results file. Silently omitting it is
        indistinguishable from a dataset that scored badly, so it is listed with the suite's own
        reason attached.
        """
        missing = {m["dataset"]: m for m in report["missing_datasets"]}
        assert "swisslipids" in missing
        assert missing["swisslipids"]["suite_status"] == "failed"
        assert missing["swisslipids"]["reason"]

    def test_a_partially_completed_dataset_is_reported_per_arm(self, report):
        """One arm produced usable results on disk under a dataset-level failed status; the report
        must surface the arm that completed rather than discarding the dataset."""
        keys = {r["row_id"] for r in report["rows"]}
        assert any("metaboliteannotator" in k and "positive" in k for k in keys)
        missing = {m["dataset"]: m for m in report["missing_datasets"]}
        assert "metaboliteannotator" in missing
        assert "negative" in json.dumps(missing["metaboliteannotator"])

    def test_a_changed_result_shape_raises_rather_than_reporting_zero(self, fixture_suite):
        """A silent zero is the worst possible failure: it looks like a measurement.

        If a scorer renames its numerator key, the reader must break rather than publish a rate of
        nothing under that dataset's name.
        """
        path = fixture_suite / "metaboliteannotator" / "positive" / "name_hit_results.json"
        payload = json.loads(path.read_text())
        payload["comparable_core"] = {"metric": "name_hit_rate", "renamed_numerator": 95, "total": 100}
        path.write_text(json.dumps(payload))
        with pytest.raises(cr.UnregisteredDatasetError):
            cr.build_report(fixture_suite)

    def test_a_dataset_without_a_conventional_results_file_is_still_read(self, report):
        """Globbing for the conventional results filename drops this dataset without a word."""
        assert any(r["dataset"] == "nlmgene" for r in report["rows"])


# --------------------------------------------------------------------------------------------
# Provenance on every row
# --------------------------------------------------------------------------------------------
class TestProvenance:
    def test_header_pins_the_suite(self, report):
        header = report["header"]
        for key in ("suite_id", "git_sha", "kg_snapshot", "biolink_version", "graph_census"):
            assert header[key]

    def test_unrecorded_chebi_release_is_recorded_as_such_with_a_fingerprint(self, report):
        """Omitting the field would leave a reader unable to tell "not recorded" from "not asked"."""
        assert report["header"]["chebi_release"] == "unrecorded"
        assert report["header"]["chebi_node_count"]

    def test_every_row_carries_its_own_git_sha_and_kg_snapshot(self, report):
        """Per row, not only in the header: for as long as any row could come from a different run,
        a single header pin is a claim about the table that the table cannot support."""
        assert report["rows"]
        for row in report["rows"]:
            assert row["git_sha"]
            assert row["kg_snapshot"]

    def test_every_interval_names_the_correctness_flag_it_came_from(self, report):
        """An unlabelled interval on a structure-oracle dataset is a silent metric switch."""
        for row in report["rows"]:
            assert row["correctness_flag"]
            assert row["metric"]


# --------------------------------------------------------------------------------------------
# LMSD regimes
# --------------------------------------------------------------------------------------------
class TestRegimeRows:
    def test_lmsd_emits_each_regime_separately(self, report):
        regimes = {r["regime"] for r in report["rows"] if r["dataset"] == "lmsd"}
        assert {"common_systematic", "shorthand"} <= regimes

    def test_the_blended_lmsd_row_is_marked_derived(self, report):
        """Carrying the dataset as one row is exactly how a regime rate gets printed against the
        wrong denominator. The blended row stays, but marked as an aggregate of the regimes."""
        overall = [r for r in report["rows"] if r["dataset"] == "lmsd" and r["regime"] == "overall"]
        assert overall
        assert overall[0]["independence_role"] == "derived_aggregate"

    def test_regime_half_widths_differ_materially(self, report):
        by_regime = {r["regime"]: r for r in report["rows"] if r["dataset"] == "lmsd" and r["metric"] == "strict"}
        assert by_regime["common_systematic"]["half_width_pt"] != by_regime["shorthand"]["half_width_pt"]


# --------------------------------------------------------------------------------------------
# Independence
# --------------------------------------------------------------------------------------------
class TestIndependence:
    def test_every_row_declares_its_family(self, report):
        for row in report["rows"]:
            assert row["independence_family"]
            assert row["independence_role"] in cr.INDEPENDENCE_ROLES

    def test_nested_oracle_variants_are_reported_as_paired_differences(self, report):
        """The failure this prevents: two nested rates' marginal intervals overlap heavily and read
        as "no difference", while the paired truth is an all-one-way discordance."""
        eq = [r for r in report["rows"] if r["dataset"] == "refmet" and r["metric"] == "kg_equivalence_set"][0]
        assert eq["independence_role"] == "nested"
        diff = eq["paired_difference"]
        assert diff["b"] + diff["c"] > 0
        assert diff["lower"] is not None
        assert diff["mcnemar"]["p_exact"] is not None

    def test_the_strict_rate_is_the_primary_interval(self, report):
        strict = [r for r in report["rows"] if r["dataset"] == "refmet" and r["metric"] == "strict"][0]
        assert strict["independence_role"] == "primary"

    def test_paired_difference_and_mcnemar_agree_on_significance(self, report):
        """Coherence, asserted rather than assumed: an interval excluding zero beside a large
        p-value (or the reverse) is the contradiction the closed forms were chosen to rule out."""
        for row in report["rows"]:
            diff = row.get("paired_difference")
            if not diff or diff["mcnemar"]["p_exact"] is None:
                continue
            excludes_zero = diff["lower"] > 0 or diff["upper"] < 0
            # Against the SCORE form, which is the statistic the interval inverts. The exact
            # binomial is conservative at small discordant totals, so comparing against it would
            # assert a coherence that no correct implementation has.
            assert excludes_zero == (diff["mcnemar"]["p_score"] < 0.05)

    def test_hgnc_any_namespace_is_marked_a_union(self, report):
        union = [r for r in report["rows"] if r["dataset"] == "hgnc" and r["independence_role"] == "derived_union"]
        assert union

    def test_metabench_overall_is_marked_derived_from_its_partition(self, report):
        overall = [
            r for r in report["rows"] if r["dataset"] == "metabench" and r["independence_role"] == "derived_aggregate"
        ]
        assert overall
        assert overall[0]["derived_from"]

    def test_intervals_are_declared_marginal_not_simultaneous(self, report):
        assert report["header"]["interval_simultaneity"] == "marginal"
        assert "overlap" in report["header"]["forbidden_inference"].lower()


class TestIndependenceAssumption:
    def test_every_row_states_its_independence_assumption(self, report):
        for row in report["rows"]:
            assumption = row["independence_assumption"]
            assert assumption["wilson_assumes"]
            assert ("cluster_key" in assumption) and ("cluster_robust" in assumption)

    def test_a_clustered_dataset_gets_a_cluster_robust_companion(self, report):
        """Templated names drawn from homologous series are not independent items, so the effective
        denominator is below the nominal one and the plain interval is over-precise."""
        clustered = [
            r for r in report["rows"] if r["dataset"] == "lmsd" and r["independence_assumption"]["cluster_key"]
        ]
        assert clustered
        companion = clustered[0]["independence_assumption"]["cluster_robust"]
        assert companion["lower"] is not None
        assert companion["design_effect"] is not None

    def test_a_single_reference_material_records_the_assertion(self, report):
        """Where no clustering is plausible the assertion is recorded, not left implicit."""
        row = [r for r in report["rows"] if r["dataset"] == "srm1950" and r["metric"] == "strict"][0]
        assert row["independence_assumption"]["assertion"]


# --------------------------------------------------------------------------------------------
# Pre-registration is consumed, not merely committed
# --------------------------------------------------------------------------------------------
class TestPreregistrationIsConsumed:
    def test_the_prereg_file_is_committed_and_loadable(self):
        prereg = cr.load_prereg()
        assert prereg["families"]
        assert {f["id"] for f in prereg["families"]} >= {"d4_competitor_headtohead", "oracle_variant_contrasts"}

    def test_the_report_carries_the_declared_family_and_correction(self, report):
        declared = report["header"]["preregistration"]
        assert declared["families"]
        assert any(f["correction"] for f in declared["families"])

    def test_every_emitted_p_value_names_its_declared_family(self, report):
        """A p-value with no declared family is a protocol violation rather than a finding."""
        for row in report["rows"]:
            diff = row.get("paired_difference")
            if not diff or diff["mcnemar"]["p_exact"] is None:
                continue
            assert diff["family"] in {f["id"] for f in cr.load_prereg()["families"]}

    def test_the_declared_correction_is_actually_applied(self, report):
        adjusted = [
            row["paired_difference"]
            for row in report["rows"]
            if row.get("paired_difference") and row["paired_difference"]["mcnemar"]["p_exact"] is not None
        ]
        assert adjusted
        for diff in adjusted:
            assert diff["p_adjusted"] is not None
            assert diff["p_adjusted"] >= diff["mcnemar"]["p_exact"] - 1e-12
            assert diff["n_tests_in_family"] >= 1

    def test_an_undeclared_family_is_refused(self):
        with pytest.raises(cr.UndeclaredTestFamilyError):
            cr.adjust_within_family([{"p": 0.01}], family_id="not-a-declared-family", p_key="p")


# --------------------------------------------------------------------------------------------
# metLinkR weighting
# --------------------------------------------------------------------------------------------
class TestMetLinkRWeighting:
    def test_the_deduplicated_companion_is_the_quotable_figure(self, report, tmp_path):
        block = report["off_category_weighting"]
        assert block["quote_this"] == "deduplicated"
        assert block["weighting_warning"]

    def test_the_file_weighted_figure_is_named_rather_than_restated(self, report):
        """The file-weighted rate multiplies a dataset by the number of target-vocabulary files it
        ships. It is pointed at by field name so a reader can find it, and its value is not carried
        here where it could be quoted by accident."""
        block = report["off_category_weighting"]
        assert block["file_weighted_field"]
        assert "value" not in block["file_weighted_field"]


# --------------------------------------------------------------------------------------------
# Artifact behaviour
# --------------------------------------------------------------------------------------------
class TestArtifactIsSavedByDefault:
    def test_saves_without_being_asked(self, fixture_suite, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr(cr, "RESULTS_DIR", tmp_path / "results")
        paths = cr.write_report(fixture_suite)
        assert paths["json"].exists() and paths["md"].exists()
        assert str(paths["json"]) in capsys.readouterr().out

    def test_out_is_an_override_not_the_only_way_to_save(self, fixture_suite, tmp_path):
        paths = cr.write_report(fixture_suite, out=tmp_path / "elsewhere")
        assert paths["json"].parent == tmp_path / "elsewhere"

    def test_markdown_renders_every_row(self, fixture_suite, tmp_path, monkeypatch):
        monkeypatch.setattr(cr, "RESULTS_DIR", tmp_path / "results")
        paths = cr.write_report(fixture_suite)
        text = paths["md"].read_text()
        report = cr.build_report(fixture_suite)
        for row in report["rows"]:
            assert row["row_id"] in text

    def test_markdown_carries_the_p_that_the_interval_inverts(self, fixture_suite, tmp_path, monkeypatch):
        """The rendered table is the surface a reader reads, so the invariant is pinned THERE.

        The sibling test on the report DATA already checks that interval and p agree. It passed
        while the .md printed the score-inverted interval beside the EXACT McNemar p -- an interval
        excluding zero next to a non-significant p, which is the contradiction ``stats`` cites to
        justify its own design. Deleting the ``score p`` column must turn this red.
        """
        monkeypatch.setattr(cr, "RESULTS_DIR", tmp_path / "results")
        text = cr.write_report(fixture_suite)["md"].read_text()
        lines = text.splitlines()
        header = next(line for line in lines if line.startswith("| row | contrast |"))
        assert "| score p |" in header
        assert "| exact p |" in header
        cells = [c for c in header.split("|") if c.strip()]
        separator = lines[lines.index(header) + 1]
        assert separator.count("---") == len(cells), "separator must match the header width"

    def test_markdown_flags_an_interval_that_disagrees_with_its_own_p(self, fixture_suite):
        """The coherence warning must actually render, not merely exist in the source.

        Built by mutating a REAL report rather than hand-rolling the row shape, so the test cannot
        drift away from the schema it guards. The state it induces -- an interval excluding zero
        beside a score p that says otherwise -- does not occur in the committed artifact, which is
        why it needs constructing to be exercised at all.
        """
        report = cr.build_report(fixture_suite)
        paired = next(
            row
            for row in report["rows"]
            if isinstance(row.get("paired_difference"), dict)
            and row["paired_difference"].get("mcnemar", {}).get("p_score") is not None
            and not row["paired_difference"].get("unavailable")
        )
        diff = paired["paired_difference"]
        diff["lower"], diff["upper"] = 0.02, 0.18  # excludes zero
        diff["mcnemar"]["p_score"] = 0.9  # ... while its own p says no difference

        text = "\n".join(cr.render_markdown(report))
        assert "\u26a0" in text, "an interval excluding zero beside a non-significant p must be flagged"

    def test_markdown_states_the_marginal_caveat(self, fixture_suite, tmp_path, monkeypatch):
        monkeypatch.setattr(cr, "RESULTS_DIR", tmp_path / "results")
        text = cr.write_report(fixture_suite)["md"].read_text()
        assert "marginal" in text.lower()

    def test_json_is_stable_across_two_builds(self, fixture_suite):
        """Seed-free by construction; a report that differs run to run cannot be a published table."""
        first = cr.build_report(fixture_suite)
        second = cr.build_report(fixture_suite)
        first["header"].pop("generated_utc", None)
        second["header"].pop("generated_utc", None)
        assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


class TestRowIdentity:
    def test_row_ids_are_unique(self, report):
        ids = [r["row_id"] for r in report["rows"]]
        assert len(set(ids)) == len(ids)

    def test_rate_matches_its_counts(self, report):
        for row in report["rows"]:
            if row["n"]:
                assert row["rate"] == pytest.approx(row["k"] / row["n"])

    def test_interval_brackets_the_rate(self, report):
        for row in report["rows"]:
            if row["n"]:
                assert row["wilson"]["lower"] <= row["rate"] <= row["wilson"]["upper"]


def test_reference_suite_regenerates_when_present():
    """The committed reference suite, when it is on this machine, must read end to end.

    Skipped rather than failed when absent: the suite directory is a run artifact, not a repository
    file, so its absence is an environment fact and not a defect in this code.
    """
    reference = Path.home() / "benchmark-runs" / "suite_20260805T033340Z"
    if not reference.exists():
        pytest.skip("reference suite directory is not present on this machine")
    report = cr.build_report(reference)
    assert report["rows"]
    assert all(row["git_sha"] for row in report["rows"])


def test_the_committed_reference_artifact_quotes_the_deduplicated_rate_only():
    """Guard on the artifact as SHIPPED, not merely on the code that builds it.

    The file-weighted cross-dataset rate multiplies a dataset by the number of target-vocabulary
    files it ships. Quoting it would overstate how often the resolver commits an off-category node
    by roughly a factor of two. The committed artifact must carry the deduplicated figure and must
    not carry the file-weighted one anywhere a reader could lift it.
    """
    import re

    results = Path(cr.__file__).parent / "results"
    artifacts = sorted(results.glob("confidence_intervals_*.json")) + sorted(results.glob("confidence_intervals_*.md"))
    if not artifacts:
        pytest.skip("no committed interval artifact in this tree")
    for path in artifacts:
        text = path.read_text()
        audit = json.loads(
            (Path(cr.__file__).parent / "results" / f"off_category_audit_{_suite_id(path)}.json").read_text()
        )
        file_weighted = str(audit["metabolite_total"]["pct_off_category"])
        deduplicated = str(audit["metabolite_total_deduplicated"]["pct_off_category"])
        assert not re.search(rf"\b{re.escape(file_weighted)}\b", text), f"{path} carries the file-weighted rate"
        assert re.search(rf"\b{re.escape(deduplicated)}\b", text), f"{path} does not quote the deduplicated rate"


def _suite_id(path: Path) -> str:
    return path.stem.replace("confidence_intervals_", "")


class TestNoDependentPairIsPresentedAsIndependent:
    """The universal form of the invariant, rather than one worked example per dataset."""

    def test_every_dependent_row_names_what_it_depends_on(self, report):
        for row in report["rows"]:
            if row["independence_role"] == "nested":
                assert row["not_independent_of"], row["row_id"]
            if row["independence_role"] in {"derived_union", "derived_aggregate"}:
                assert row["derived_from"], row["row_id"]

    def test_every_named_dependency_is_a_row_that_exists(self, report):
        ids = {row["row_id"] for row in report["rows"]}
        for row in report["rows"]:
            if row["not_independent_of"]:
                assert row["not_independent_of"] in ids, row["row_id"]
            for parent in row["derived_from"] or []:
                assert parent in ids, f"{row['row_id']} claims to derive from a row that is absent"

    def test_a_nested_row_carries_a_paired_contrast_or_says_why_not(self, report):
        """A nested row printed with only its own marginal interval is the failure this prevents:
        two heavily overlapping intervals read as "no difference" while the paired truth can be an
        all-one-way discordance."""
        for row in report["rows"]:
            if row["independence_role"] != "nested":
                continue
            diff = row["paired_difference"]
            assert diff is not None or row["independence_assumption"]["assertion"], row["row_id"]

    def test_the_rendered_table_marks_every_row_with_its_role(self, fixture_suite, tmp_path, monkeypatch):
        monkeypatch.setattr(cr, "RESULTS_DIR", tmp_path / "results")
        text = cr.write_report(fixture_suite)["md"].read_text()
        for role in {row["independence_role"] for row in cr.build_report(fixture_suite)["rows"]}:
            assert role in text
