"""Build the machine-readable inventory of the results section's numeric claims.

Run this when the manuscript copy changes; the output it writes is what
``reconcile_section3`` checks against the committed interval artifact. Kept as a script rather than
as a hand-maintained file so a claim's manuscript value and its artifact field are recorded
together at the moment the claim is entered.

Reads two files already on disk and writes a third. It makes no requests.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

MODULE_DIR = Path(__file__).parent
MANUSCRIPT_DIR = MODULE_DIR / "manuscript"
SOURCE_PATH = MANUSCRIPT_DIR / "section3_source.md"
CLAIMS_PATH = MANUSCRIPT_DIR / "section3_claims.json"

# artifact identifiers a claim may resolve against. Anything else is a typo, not a new artifact.
ARTIFACTS = (
    "confidence_intervals",  # this axis owns it; the field path is a row_id + key
    "off_category_audit",
    "tier3_determinism",
    "northstar_ms1",
    "published_external",  # a figure quoted from another group's paper; nothing here regenerates it
    # The gene/protein head-to-head. Deliberately its own artifact rather than folded into
    # published_external: these are OUR measurements of other tools, run on our gold set with our
    # scorer, so they need an artifact and not a citation. That artifact does not exist yet.
    "competitor_headtohead",
)


def claim(
    claim_id: str,
    *,
    manuscript_value: Any,
    kind: str,
    artifact: str,
    row_id: str | None,
    field: str | None,
    blocked_by: str | None = None,
    note: str = "",
) -> dict[str, Any]:
    assert artifact in ARTIFACTS, artifact
    assert blocked_by or (row_id and field), f"{claim_id}: a claim must resolve to a field or name its blocker"
    return {
        "id": claim_id,
        "manuscript_value": manuscript_value,
        "kind": kind,
        "artifact": artifact,
        "row_id": row_id,
        "field": field,
        "blocked_by": blocked_by,
        "note": note,
    }


def build() -> dict[str, Any]:
    ci = "confidence_intervals"
    claims: list[dict[str, Any]] = [
        # --- determinism -------------------------------------------------------------------
        claim(
            "determinism.biomapper_accuracy",
            manuscript_value=0.44,
            kind="rate",
            artifact="tier3_determinism",
            row_id=None,
            field=None,
            blocked_by="the determinism study is a separate harness with its own artifact; it is "
            "not part of the benchmark suite this report reads",
        ),
        # --- grounding ---------------------------------------------------------------------
        claim(
            "metabench.overall",
            manuscript_value={"k": 545, "n": 1000},
            kind="counts",
            artifact=ci,
            row_id="metabench:overall:strict",
            field="k,n",
            note="the manuscript value predates the reference suite; restatement pending",
        ),
        claim(
            "metabench.kegg",
            manuscript_value={"k": 302, "n": 400},
            kind="counts",
            artifact=ci,
            row_id="metabench:KEGG:strict",
            field="k,n",
        ),
        claim(
            "metabench.hmdb",
            manuscript_value={"k": 86, "n": 400},
            kind="counts",
            artifact=ci,
            row_id="metabench:HMDB:strict",
            field="k,n",
        ),
        claim(
            "metabench.chebi",
            manuscript_value={"k": 157, "n": 200},
            kind="counts",
            artifact=ci,
            row_id="metabench:CHEBI:strict",
            field="k,n",
        ),
        claim(
            "metabench.best_retrieval_augmented_lm",
            manuscript_value=0.4093,
            kind="rate",
            artifact="published_external",
            row_id=None,
            field=None,
            blocked_by="a published aggregate from another group with no per-item data; the "
            "registry value is deliberately null pending transcription, and the denominator is "
            "not attainable on the stated sample size",
        ),
        claim(
            "metabench.best_closed_book_lm",
            manuscript_value=0.0087,
            kind="rate",
            artifact="published_external",
            row_id=None,
            field=None,
            blocked_by="a published figure from another group; nothing in this repository regenerates it",
        ),
        # --- structure-anchored ------------------------------------------------------------
        claim(
            "hajjar.strict",
            manuscript_value={"k": 81, "n": 100},
            kind="counts",
            artifact=ci,
            row_id="hajjar:CHEBI:overall:strict",
            field="k,n",
            blocked_by="the curated set has no pinned source url and is hand-passed, so it is not "
            "in the unattended suite this report reads",
        ),
        claim(
            "refmet.strict",
            manuscript_value={"k": 1341, "n": 1500},
            kind="counts",
            artifact=ci,
            row_id="refmet:CHEBI:overall:strict",
            field="k,n",
        ),
        claim(
            "refmet.charge_normalized",
            manuscript_value={"k": 1343, "n": 1500},
            kind="counts",
            artifact=ci,
            row_id="refmet:CHEBI:overall:charge_normalized",
            field="k,n",
        ),
        claim(
            "necs.strict",
            manuscript_value={"k": 608, "n": 796},
            kind="counts",
            artifact=ci,
            row_id="necs:CHEBI:overall:strict",
            field="k,n",
        ),
        claim(
            "necs.charge_normalized",
            manuscript_value={"k": 622, "n": 796},
            kind="counts",
            artifact=ci,
            row_id="necs:CHEBI:overall:charge_normalized",
            field="k,n",
        ),
        # --- coverage ----------------------------------------------------------------------
        claim(
            "metaboliteannotator.positive",
            manuscript_value={"k": 4096, "n": 4314},
            kind="counts",
            artifact=ci,
            row_id="metaboliteannotator:positive:name_hit",
            field="k,n",
        ),
        claim(
            "metaboliteannotator.negative",
            manuscript_value={"k": 2386, "n": 2509},
            kind="counts",
            artifact=ci,
            row_id="metaboliteannotator:negative:name_hit",
            field="k,n",
            blocked_by="the negative arm returned server errors in the reference run and produced "
            "no results file; re-running it is a gated live step",
        ),
        claim(
            "metaboliteannotator.published_positive",
            manuscript_value=0.932,
            kind="rate",
            artifact="published_external",
            row_id=None,
            field=None,
            blocked_by="a transcribed baseline from another group's paper",
        ),
        claim(
            "metaboliteannotator.published_negative",
            manuscript_value=0.935,
            kind="rate",
            artifact="published_external",
            row_id=None,
            field=None,
            blocked_by="a transcribed baseline from another group's paper",
        ),
        # --- cross-linking -----------------------------------------------------------------
        claim(
            "metlinkr.curator_agreement",
            manuscript_value={"k": 334, "n": 401},
            kind="counts",
            artifact=ci,
            row_id="metlinkr:curator_agreement",
            field="k,n",
        ),
        claim(
            "metlinkr.structural_concordance",
            manuscript_value={"k": 549, "n": 650},
            kind="counts",
            artifact=ci,
            row_id="metlinkr:structural_concordance",
            field="k,n",
        ),
        claim(
            "metlinkr.published_curator_agreement",
            manuscript_value=0.853,
            kind="rate",
            artifact="published_external",
            row_id=None,
            field=None,
            blocked_by="the tool's own published figure",
        ),
        # --- clinical reference material ---------------------------------------------------
        claim(
            "srm1950.strict",
            manuscript_value={"k": 396, "n": 983},
            kind="counts",
            artifact=ci,
            row_id="srm1950:CHEBI:overall:strict",
            field="k,n",
        ),
        # --- lipid regimes -----------------------------------------------------------------
        claim(
            "lmsd.common_systematic.strict",
            manuscript_value=0.516,
            kind="rate",
            artifact=ci,
            row_id="lmsd:CHEBI:common_systematic:strict",
            field="rate",
        ),
        claim(
            "lmsd.common_systematic.charge_normalized",
            manuscript_value=0.535,
            kind="rate",
            artifact=ci,
            row_id="lmsd:CHEBI:common_systematic:charge_normalized",
            field="rate",
        ),
        claim(
            "lmsd.shorthand.strict",
            manuscript_value=0.054,
            kind="rate",
            artifact=ci,
            row_id="lmsd:CHEBI:shorthand:strict",
            field="rate",
        ),
        claim(
            "lmsd.overall.strict",
            manuscript_value=0.198,
            kind="rate",
            artifact=ci,
            row_id="lmsd:CHEBI:overall:strict",
            field="rate",
        ),
        claim(
            "lmsd.subsample_population",
            manuscript_value={"k": None, "n": 50000},
            kind="counts",
            artifact=ci,
            row_id="lmsd:CHEBI:overall:strict",
            field="coverage",
            note="an approximate source-population size recorded on the dataset card",
        ),
        # --- ambiguity ---------------------------------------------------------------------
        claim(
            "pham.non_lipid_membership",
            manuscript_value={"k": 625, "n": 1500},
            kind="counts",
            artifact=ci,
            row_id="pham:overall:strict",
            field="k,n",
            blocked_by="the source is a release directory that must be reconstructed into a table "
            "by hand, so it is not in the unattended suite",
        ),
        # --- gene / protein ----------------------------------------------------------------
        claim(
            "hgnc.any_namespace",
            manuscript_value=0.963,
            kind="rate",
            artifact=ci,
            row_id="hgnc:ENSEMBL:any-namespace:strict",
            field="rate",
        ),
        claim(
            "hgnc.ncbigene",
            manuscript_value=0.978,
            kind="rate",
            artifact=ci,
            row_id="hgnc:ENSEMBL:NCBIGene:strict",
            field="rate",
        ),
        claim(
            "hgnc.uniprot",
            manuscript_value=0.906,
            kind="rate",
            artifact=ci,
            row_id="hgnc:ENSEMBL:UniProtKB:strict",
            field="rate",
        ),
        claim(
            "hgnc.ensembl",
            manuscript_value=0.767,
            kind="rate",
            artifact=ci,
            row_id="hgnc:ENSEMBL:ENSEMBL:strict",
            field="rate",
        ),
        claim(
            "provided_id.ncbigene_to_ensembl",
            manuscript_value=0.992,
            kind="rate",
            artifact=ci,
            row_id="provided-id:overall:strict",
            field="rate",
            blocked_by="a dataset family over bulk backbones; needs a pinned artifact, so it is "
            "not in the unattended suite",
        ),
        # --- end-to-end case study ---------------------------------------------------------
        claim(
            "ms1.comparable_features",
            manuscript_value={"k": 127, "n": 152},
            kind="counts",
            artifact="northstar_ms1",
            row_id=None,
            field=None,
            blocked_by="the case study reads a delivery panel, not the benchmark suite; its "
            "figures belong to a separate artifact",
        ),
        claim(
            "ms1.chebi_agreement",
            manuscript_value={"k": 107, "n": 126},
            kind="counts",
            artifact="northstar_ms1",
            row_id=None,
            field=None,
            blocked_by="same separate artifact as the other case-study figures",
        ),
        # --- sampling provenance and secondary qualifiers -----------------------------------
        claim(
            "refmet.source_population",
            manuscript_value={"k": 34404, "n": 206000},
            kind="counts",
            artifact=ci,
            row_id="refmet:CHEBI:overall:strict",
            field="coverage",
            note="structure-bearing rows out of the source release; recorded on the dataset card",
        ),
        claim(
            "refmet.subsample",
            manuscript_value={"k": None, "n": 1500},
            kind="counts",
            artifact=ci,
            row_id="refmet:CHEBI:overall:strict",
            field="n",
        ),
        claim(
            "srm1950.entries",
            manuscript_value={"k": None, "n": 1058},
            kind="counts",
            artifact=ci,
            row_id="srm1950:CHEBI:overall:strict",
            field="coverage",
        ),
        claim(
            "necs.delivered_metabolites",
            manuscript_value={"k": None, "n": 1495},
            kind="counts",
            artifact=ci,
            row_id="necs:CHEBI:overall:strict",
            field="coverage",
        ),
        claim(
            "metabench.pre_fix_harness_output",
            manuscript_value=0.243,
            kind="rate",
            artifact=ci,
            row_id="metabench:overall:strict",
            field="rate",
            blocked_by="a superseded scorer output, retained in the prose as history; the current "
            "scorer's output is the row it points at, so the pre-fix figure resolves to nothing "
            "regenerable and must be presented as history or dropped",
        ),
        claim(
            "metaboliteannotator.id_concordance_positive",
            manuscript_value=0.071,
            kind="rate",
            artifact=ci,
            row_id="metaboliteannotator:positive:name_hit",
            field="rate",
            blocked_by="the secondary identifier-concordance qualifier lives in the name-hit "
            "results file and is not carried into the interval artifact",
        ),
        claim(
            "metaboliteannotator.id_concordance_negative",
            manuscript_value=0.216,
            kind="rate",
            artifact=ci,
            row_id="metaboliteannotator:negative:name_hit",
            field="rate",
            blocked_by="same secondary qualifier, on an arm that produced no results file",
        ),
        claim(
            "metaboliteannotator.published_negative_denominator",
            manuscript_value={"k": None, "n": 2510},
            kind="counts",
            artifact="published_external",
            row_id=None,
            field=None,
            blocked_by="the other group's stated denominator",
        ),
        claim(
            "hajjar.charge_normalized_estimate",
            manuscript_value=0.90,
            kind="rate",
            artifact=ci,
            row_id="hajjar:CHEBI:overall:charge_normalized",
            field="rate",
            blocked_by="an estimate stated in prose rather than a measured figure; it must either "
            "resolve to a charge-normalized row or be withdrawn",
        ),
        claim(
            "determinism.opus_accuracy",
            manuscript_value=0.48,
            kind="rate",
            artifact="tier3_determinism",
            row_id=None,
            field=None,
            blocked_by="the determinism study's own artifact",
        ),
        claim(
            "determinism.qwen_accuracy",
            manuscript_value=0.0,
            kind="rate",
            artifact="tier3_determinism",
            row_id=None,
            field=None,
            blocked_by="the determinism study's own artifact",
        ),
        claim(
            "pham.ambiguity_rate_published",
            manuscript_value=0.83,
            kind="rate",
            artifact="published_external",
            row_id=None,
            field=None,
            blocked_by="a rate quoted from another group's paper",
        ),
        claim(
            "pham.ambiguous_population",
            manuscript_value={"k": 16643, "n": 129877},
            kind="counts",
            artifact=ci,
            row_id="pham:overall:strict",
            field="coverage",
            blocked_by="the source must be reconstructed by hand, so the dataset is not in the unattended suite",
        ),
        claim(
            "pham.lipid_stratum",
            manuscript_value=0.059,
            kind="rate",
            artifact=ci,
            row_id="pham:lipid:strict",
            field="rate",
            blocked_by="same un-sourced dataset",
        ),
        claim(
            "pham.gold_cross_check",
            manuscript_value={"k": 102, "n": 887},
            kind="counts",
            artifact=ci,
            row_id="pham:overall:strict",
            field="coverage",
            blocked_by="same un-sourced dataset",
        ),
        claim(
            "competitors.uniprot_scoring_artifact",
            manuscript_value={"k": None, "n": 637},
            kind="counts",
            artifact=ci,
            row_id="competitors:uniprotkb:strict",
            field="n",
            blocked_by="the competitor head-to-head is a gated live run against three external "
            "hosted services; no artifact exists yet",
        ),
        claim(
            "ms1.panel_comparability",
            manuscript_value={"k": 1001, "n": 2710},
            kind="counts",
            artifact="northstar_ms1",
            row_id=None,
            field=None,
            blocked_by="the case study's separate artifact",
        ),
        claim(
            "ms1.all_namespace_agreement",
            manuscript_value=0.843,
            kind="rate",
            artifact="northstar_ms1",
            row_id=None,
            field=None,
            blocked_by="the case study's separate artifact",
        ),
        claim(
            "ms1.any_namespace_agreement",
            manuscript_value=0.953,
            kind="rate",
            artifact="northstar_ms1",
            row_id=None,
            field=None,
            blocked_by="the case study's separate artifact",
        ),
        claim(
            "ms1.inchikey_agreement",
            manuscript_value=0.984,
            kind="rate",
            artifact="northstar_ms1",
            row_id=None,
            field=None,
            blocked_by="the case study's separate artifact",
        ),
        claim(
            "ms1.kegg_agreement",
            manuscript_value=0.988,
            kind="rate",
            artifact="northstar_ms1",
            row_id=None,
            field=None,
            blocked_by="the case study's separate artifact",
        ),
        claim(
            "ms1.hmdb_agreement",
            manuscript_value=0.982,
            kind="rate",
            artifact="northstar_ms1",
            row_id=None,
            field=None,
            blocked_by="the case study's separate artifact",
        ),
        claim(
            "ms1.lipidmaps_agreement",
            manuscript_value=1.0,
            kind="rate",
            artifact="northstar_ms1",
            row_id=None,
            field=None,
            blocked_by="the case study's separate artifact",
        ),
        claim(
            "ms1.residual_disagreement",
            manuscript_value=0.05,
            kind="rate",
            artifact="northstar_ms1",
            row_id=None,
            field=None,
            blocked_by="the case study's separate artifact",
        ),
        # --- weighting ---------------------------------------------------------------------
        claim(
            "off_category.cross_dataset_rate",
            manuscript_value=None,
            kind="rate",
            artifact="off_category_audit",
            row_id="metabolite_total_deduplicated",
            field="pct_off_category",
            note="quote the DEDUPLICATED rate; the file-weighted one multiplies a dataset by the "
            "number of target-vocabulary files it ships",
        ),
    ]

    # The head-to-head table and the two withdrawn-claim correction figures. Every one of these was
    # published with no claim and no blocker, so the completeness check reported zero omissions on a
    # table of twelve of them. They are measured BY US -- same HGNC gold set, same scorer -- so the
    # honest classification is "measured, artifact missing", not "cited from a publication".
    _D4_BLOCKED = (
        "the gene/protein competitor head-to-head (D4) has never run on the public backend, so no "
        "committed artifact carries this value. studies/external_benchmarks/competitors/ holds the "
        "harness only, and the pinned suite contains no competitor results. Until D4 runs this cell "
        "is published with nothing behind it."
    )
    for claim_id, value, label in (
        ("biodbnet.ensembl", 0.791, "bioDBnet Ensembl"),
        ("biodbnet.ncbigene", 0.999, "bioDBnet NCBI Gene"),
        ("biodbnet.uniprot", 0.995, "bioDBnet UniProtKB"),
        ("biodbnet.union", 0.986, "bioDBnet union"),
        ("gconvert.ensembl", 0.960, "g:Convert Ensembl"),
        ("gconvert.ncbigene", 0.550, "g:Convert NCBI Gene"),
        ("gconvert.uniprot", 0.956, "g:Convert UniProtKB"),
        ("gconvert.union", 0.904, "g:Convert union"),
        ("uniprot_idmapping.uniprot", 0.937, "UniProt ID-mapping UniProtKB"),
        ("uniprot_idmapping.union", 0.398, "UniProt ID-mapping union"),
        ("gconvert.uniprot_precorrection", 0.000, "g:Convert UniProtKB before the separator fix"),
        ("biodbnet.uniprot_precorrection", 0.061, "bioDBnet UniProtKB before the separator fix"),
    ):
        claims.append(
            claim(
                f"headtohead.{claim_id}",
                manuscript_value=value,
                kind="rate",
                artifact="competitor_headtohead",
                row_id=None,
                field=None,
                blocked_by=_D4_BLOCKED,
                note=label,
            )
        )

    return {
        "inventory": "section 3 numeric claims",
        "source": str(SOURCE_PATH.relative_to(MODULE_DIR.parent.parent)),
        "artifacts": list(ARTIFACTS),
        "claims": claims,
        # Number-shaped tokens in the prose that are not measurements at all. Enumerated rather
        # than pattern-matched away: a rule broad enough to absorb these would also absorb a real
        # figure, and the whole point is that nothing numeric leaves the prose unclassified.
        "not_a_measurement": {
            "1950": "the designation of the certified reference material, not a count or a year",
            "2019": "a citation year",
            "2020": "a citation year",
            "2025": "a citation year",
            "2026": "a citation year",
            "2510.14944": "a preprint identifier",
            "100": "the size of the curated calibration set, stated as a structural fact",
            # Two-part version numbers. The prose guard strips three-part semver; these look
            # exactly like decimal proportions and can only be told apart by what they name.
            "4.5": "the MetaNetX release number",
            "4.6": "the Sonnet model version",
            "4.8": "the Opus model version",
            "6.0": "the MetaboAnalyst version",
            "409": (
                "an arithmetic illustration, not a result: the nearest attainable numerator to the "
                "published baseline rate on 1,000 items, cited to show that rate implies a "
                "different denominator"
            ),
        },
    }


def main() -> int:  # pragma: no cover - thin CLI
    CLAIMS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CLAIMS_PATH.write_text(json.dumps(build(), indent=2))
    print(f"wrote {CLAIMS_PATH}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
