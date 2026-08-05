"""Tests for the Biolink-category validator on the committed node (accepted_categories path).

The guard is a **validator applied to the single committed node**, not a filter on the candidate
pool: a pool filter promotes the next-best row into the vacancy, and a live simulation on 45 sampled
off-category commits showed that promotion produces a *different still-wrong* node 18/45 times — one
that is harder to audit than what it replaced (``EFO:...measurement`` announces itself as
not-a-molecule; ``PUBCHEM.COMPOUND:131755421``, a triacylglycerol substituted for a plasmalogen,
does not). The validator can therefore only convert wrong->refuse, never wrong->right, which is the
deliberately accepted cost.

**The guard is on CATEGORY, never on NAMESPACE.** Writing it as "the committed node must be in a
canonical namespace" would destroy 294 legitimate non-canonical chemical commits (UNII 97, MESH 83,
PUBCHEM.COMPOUND 52, KEGG.GLYCAN 30, ...). Namespace preference is ``_select_canonical``'s job.

Fixture rows are live-verified shapes from KRAKEN 2.0.1, not invented ones. Every test passes
``prefer_human=False`` explicitly: ``get_annotations`` defaults it to True, and at ``:69`` a
``prefer_human`` miss fires the ``GeneSymbolResolver``, which would drive a live ``/get-nodes`` call.
"""

from unittest.mock import patch

import pandas as pd

from biomapper2.core.annotators.kestrel_hybrid import KestrelHybridSearchAnnotator

MET = {"CHEBI", "HMDB", "RM"}

# ``get_descendants('biolink:ChemicalEntity')`` under Biolink 4.2.5, n=12 (verified against bmt).
# Note what is absent: Protein, Polypeptide, PhenotypicFeature, Pathway, MolecularActivity — and
# NamedThing, which is why the top-of-hierarchy sentinel needs its own failure-open clause.
CHEMICAL = {
    "biolink:ChemicalEntity",
    "biolink:ChemicalMixture",
    "biolink:ComplexMolecularMixture",
    "biolink:Drug",
    "biolink:EnvironmentalFoodContaminant",
    "biolink:Food",
    "biolink:FoodAdditive",
    "biolink:MolecularEntity",
    "biolink:MolecularMixture",
    "biolink:NucleicAcidEntity",
    "biolink:ProcessedMaterial",
    "biolink:SmallMolecule",
}


def _row(node_id, score, name, categories=..., synonyms=None):
    """A hybrid-search row. ``categories=...`` omits the key entirely (the missing-key shape)."""
    row = {"id": node_id, "score": score, "name": name, "synonyms": synonyms or []}
    if categories is not ...:
        row["categories"] = categories
    return row


# Live-verified rows. Score ordering is meaningful: the off-category EFO row outranks every chemical.
EFO_MEASUREMENT = _row("EFO:0800030", 4.90, "X - 12345 measurement", ["biolink:PhenotypicFeature"])
CHEBI_SMALL_MOLECULE = _row("CHEBI:192245", 2.50, "some metabolite", ["biolink:SmallMolecule"])
UMLS_PROTEIN = _row("UMLS:C0639060", 3.10, "carnosine", ["biolink:Protein"])
NCIT_POLYPEPTIDE = _row("NCIT:C178456", 2.90, "carnosine", ["biolink:Polypeptide"])
UNII_CHEMICAL_ENTITY = _row("UNII:LYJ3482CB6", 2.00, "some chemical", ["biolink:ChemicalEntity"])
CHEBI_MIXTURE = _row("CHEBI:75549", 1.80, "a mixture", ["biolink:MolecularMixture"])
GO_ACTIVITY = _row("GO:0033265", 1.50, "choline binding", ["biolink:MolecularActivity"])
PATHWHIZ_PATHWAY = _row("PathWhiz:PW002494", 1.20, "a pathway", ["biolink:Pathway"])
NAMEDTHING_SENTINEL = _row("OBO:NCIT_C103149", 4.889, "S-Adenosylhomocysteine", ["biolink:NamedThing"])
EMPTY_CATEGORIES = _row("MESH:D000001", 3.00, "untyped node", [])
MISSING_CATEGORIES = _row("MESH:D000002", 3.00, "keyless node")


class TestIsOnCategory:
    """Unit-level acceptance decisions over the live-verified row shapes."""

    def test_none_accepted_set_accepts_everything(self):
        """``accepted=None`` is the disabled state — the gene path's byte-for-byte guarantee."""
        for row in (EFO_MEASUREMENT, GO_ACTIVITY, PATHWHIZ_PATHWAY, UMLS_PROTEIN):
            assert KestrelHybridSearchAnnotator._is_on_category(row, None) is True

    def test_chemical_rows_are_accepted(self):
        """SmallMolecule, and — critically — one level up (ChemicalEntity) and MolecularMixture."""
        for row in (CHEBI_SMALL_MOLECULE, UNII_CHEMICAL_ENTITY, CHEBI_MIXTURE):
            assert KestrelHybridSearchAnnotator._is_on_category(row, CHEMICAL) is True

    def test_off_category_rows_are_rejected(self):
        """PhenotypicFeature / Protein / Polypeptide / MolecularActivity / Pathway are all off-category.

        Peptide metabolites mistyped ``biolink:Protein`` via UMLS are safe to reject: a CHEBI row is
        always present within the real limit (glutathione CHEBI:16856, carnosine CHEBI:15727,
        anserine CHEBI:18323, ophthalmate CHEBI:189750) and ``_select_canonical`` already prefers it.
        """
        for row in (EFO_MEASUREMENT, UMLS_PROTEIN, NCIT_POLYPEPTIDE, GO_ACTIVITY, PATHWHIZ_PATHWAY):
            assert KestrelHybridSearchAnnotator._is_on_category(row, CHEMICAL) is False

    def test_failure_open_on_empty_and_missing_categories(self):
        """No type assertion is not a wrong type assertion — accept rather than silently refuse."""
        assert KestrelHybridSearchAnnotator._is_on_category(EMPTY_CATEGORIES, CHEMICAL) is True
        assert KestrelHybridSearchAnnotator._is_on_category(MISSING_CATEGORIES, CHEMICAL) is True
        assert KestrelHybridSearchAnnotator._is_on_category(_row("X:1", 1.0, "n", None), CHEMICAL) is True

    def test_failure_open_on_top_of_hierarchy_sentinel(self):
        """``biolink:NamedThing`` is a typing gap, not an off-category assertion.

        Across 1,200 live candidate rows *zero* had empty/missing categories, so the empty guard alone
        would have been dead code. Eight carried ``['biolink:NamedThing']`` — including
        ``OBO:NCIT_C103149`` "S-Adenosylhomocysteine" top-scored at 4.889, a legitimate metabolite.
        """
        assert KestrelHybridSearchAnnotator._is_on_category(NAMEDTHING_SENTINEL, CHEMICAL) is True
        assert KestrelHybridSearchAnnotator._is_on_category(_row("X:1", 1.0, "n", ["biolink:Entity"]), CHEMICAL) is True

    def test_sentinel_mixed_with_a_real_off_category_type_is_not_a_sentinel(self):
        """Only a *pure* sentinel is a typing gap; alongside a real type it is a real assertion."""
        mixed = _row("X:1", 1.0, "n", ["biolink:NamedThing", "biolink:Pathway"])
        assert KestrelHybridSearchAnnotator._is_on_category(mixed, CHEMICAL) is False


def _annotate(rows, term, preferred_prefixes=MET, accepted_categories=None):
    ann = KestrelHybridSearchAnnotator()
    return ann.get_annotations(
        {"name": term},
        "name",
        "biolink:SmallMolecule",
        prefer_human=False,
        preferred_prefixes=preferred_prefixes,
        accepted_categories=accepted_categories,
        cache={term: rows},
    )[ann.slug]


class TestValidatorAtCommitPoint:
    """The reproduced defect and its fix, through the annotator's cache path (no network)."""

    # The metLinkR defect shape: no canonical row in the pool, so `_select_canonical` falls back to
    # the honest top-1 — which is an EFO *measurement* node, not a molecule at all.
    DEFECT_ROWS = [EFO_MEASUREMENT, UMLS_PROTEIN, GO_ACTIVITY, PATHWHIZ_PATHWAY]

    def test_off_category_top1_is_committed_without_the_guard(self):
        """The defect, reproduced: today's behaviour commits ``EFO:0800030`` for a metabolite query."""
        annotations = _annotate(self.DEFECT_ROWS, "X - 12345")
        assert "0800030" in annotations.get("EFO", {})

    def test_off_category_top1_is_refused_with_the_guard(self):
        """The fix: the committed node fails the category check, so nothing is committed."""
        annotations = _annotate(self.DEFECT_ROWS, "X - 12345", accepted_categories=CHEMICAL)
        assert annotations == {}

    def test_refusal_never_promotes_the_next_best_row(self):
        """Refuse, do not substitute. The runner-up here is also wrong and *less* auditable."""
        annotations = _annotate(self.DEFECT_ROWS, "X - 12345", accepted_categories=CHEMICAL)
        assert "C0639060" not in annotations.get("UMLS", {})
        assert annotations == {}

    def test_on_category_canonical_pick_survives_and_keeps_its_provenance(self):
        rows = [EFO_MEASUREMENT, CHEBI_SMALL_MOLECULE, GO_ACTIVITY]
        annotations = _annotate(rows, "some metabolite", accepted_categories=CHEMICAL)
        assert "192245" in annotations.get("CHEBI", {})
        assert annotations["CHEBI"]["192245"].get("resolved_via") == "canonical_preference"

    def test_guard_is_on_category_not_namespace(self):
        """A non-canonical namespace with a chemical category must survive.

        ``UNII:LYJ3482CB6`` is not in {CHEBI, HMDB, RM} but is typed ``biolink:ChemicalEntity``. A
        namespace whitelist would destroy 294 legitimate commits like ``S-adenosylhomocysteine ->
        UNII:8K31Q2S66S``; all 26 of refmet's UNII/PUBCHEM commits are category-clean.
        """
        annotations = _annotate([UNII_CHEMICAL_ENTITY, GO_ACTIVITY], "some chemical", accepted_categories=CHEMICAL)
        assert "LYJ3482CB6" in annotations.get("UNII", {})

    def test_sentinel_typed_top_hit_survives_the_guard(self):
        """The failure-open clause reaches the commit point, not just the predicate."""
        annotations = _annotate([NAMEDTHING_SENTINEL], "S-Adenosylhomocysteine", accepted_categories=CHEMICAL)
        assert "NCIT_C103149" in annotations.get("OBO", {})

    def test_none_accepted_categories_reproduces_todays_behaviour(self):
        """Regression lock: with the guard disabled, every row shape commits exactly as before."""
        for rows, expect_vocab, expect_local in [
            (self.DEFECT_ROWS, "EFO", "0800030"),
            ([UMLS_PROTEIN], "UMLS", "C0639060"),
            ([GO_ACTIVITY], "GO", "0033265"),
            ([CHEBI_SMALL_MOLECULE], "CHEBI", "192245"),
        ]:
            annotations = _annotate(rows, rows[0]["name"], accepted_categories=None)
            assert expect_local in annotations.get(expect_vocab, {})

    def test_empty_results_still_refuse_quietly(self):
        assert _annotate([], "nothing", accepted_categories=CHEMICAL) == {}

    def test_refusal_is_logged_for_the_instrumented_run(self, caplog):
        """Log-only refusal (no AssignedIDsDict shape change), keyed so the audit run can grep it."""
        with caplog.at_level("INFO"):
            _annotate(self.DEFECT_ROWS, "X - 12345", accepted_categories=CHEMICAL)
        assert "off_category_refusal" in caplog.text
        assert "EFO:0800030" in caplog.text


class TestBulkThreading:
    def test_bulk_forwards_accepted_categories(self):
        """``get_annotations_bulk``'s internal re-dispatch must forward the kwarg, else a silent no-op."""
        ann = KestrelHybridSearchAnnotator()
        with patch.object(ann, "_kestrel_hybrid_search", return_value={"X - 12345": [EFO_MEASUREMENT]}):
            out = ann.get_annotations_bulk(
                pd.DataFrame({"name": ["X - 12345"]}),
                "name",
                "biolink:SmallMolecule",
                prefer_human=False,
                preferred_prefixes=MET,
                accepted_categories=CHEMICAL,
            )
        assert out.iloc[0][ann.slug] == {}

    def test_bulk_without_accepted_categories_is_unchanged(self):
        ann = KestrelHybridSearchAnnotator()
        with patch.object(ann, "_kestrel_hybrid_search", return_value={"X - 12345": [EFO_MEASUREMENT]}):
            out = ann.get_annotations_bulk(
                pd.DataFrame({"name": ["X - 12345"]}),
                "name",
                "biolink:SmallMolecule",
                prefer_human=False,
                preferred_prefixes=MET,
            )
        assert "0800030" in out.iloc[0][ann.slug].get("EFO", {})


class TestGenePathUnaffected:
    def test_gene_path_is_byte_for_byte_unchanged(self):
        """HGNC baseline is 0/4476 and gene/protein is intentionally absent from the acceptance map.

        93.8% of HGNC commits are "off-category" relative to the chemical root — the clean positive
        control proving the gene path must never receive an acceptance set.
        """
        ann = KestrelHybridSearchAnnotator()
        gene_row = {"id": "NCBIGene:7132", "score": 4.0, "name": "TNFRSF1A", "prefixes": ["HGNC"], "synonyms": []}
        annotations = ann.get_annotations(
            {"name": "TNFRSF1A"}, "name", "biolink:Gene", prefer_human=True, cache={"TNFRSF1A": [gene_row]}
        )[ann.slug]
        assert "7132" in annotations.get("NCBIGene", {})
