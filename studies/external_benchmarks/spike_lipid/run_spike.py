"""Orchestrator: subset -> probe -> reference -> gate/score -> verdict, save-by-default.

SOP (institutional artifact hygiene): results persist BY DEFAULT to a timestamped path
— never behind a flag. ``--out`` is an OVERRIDE, not the only way to save. The run card
pins everything needed to reproduce: the LMSD subsample SHA (from the dataset card), the
NEW seed, the model id/version, and every metric. The path is printed when the run ends.

This is the ONLY module that spends money (the paid model calls). It is not run by the
offline test suite; the deterministic units it calls are each tested with fakes.

VERDICT ASYMMETRY (different from #3): here a LOW score is acceptable/desired IF the
failures are meaningful lipid chemistry. So the verdict is NOT read from the rate alone —
it pairs the species-match rate with the failure taxonomy, and always reports the
species-vs-strict GAP (how much published difficulty was isomer-lottery misspecification).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
from pathlib import Path

from . import probe as probe_mod
from . import reference as ref_mod
from . import score as score_mod
from . import subset as subset_mod

# Published anchors (LMSD, exact-InChIKey Top-1) — reference only, never recomputed.
LMSD_SHORTHAND_ANCHOR = 0.054  # 5.4% shorthand stratum
LMSD_BLENDED_ANCHOR = 0.198  # 19.8% blended (shorthand + common/systematic)
SEED_42_FORBIDDEN = 42  # reservoir seed that defines the 1,500-name LMSD subsample


def _source_sha(artifact: Path) -> str | None:
    card = artifact / "dataset_card.json"
    if not card.exists():
        return None
    try:
        return json.loads(card.read_text()).get("subsample_sha256")
    except Exception:
        return None


def _default_out(base: Path) -> Path:
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return base / f"lipid_spike_{stamp}"


def _verdict(species_rate: float | None, taxonomy: dict) -> str:
    """Read the species-match rate WITH the failure taxonomy (see module docstring).

    Bands are relative to TB-Science's 10-20% target solve rate. ``meaningful`` = the
    dominant miss buckets are chemistry (wrong carbon/db/class, formula_mismatch), not
    format noise (invalid_smiles / no_structure_emitted)."""
    if species_rate is None:
        return "INCONCLUSIVE (no gradeable names — check gate pass-rate + pygoslin coverage)"

    noise = (taxonomy.get("invalid_smiles", 0) + taxonomy.get("no_structure_emitted", 0))
    chem = sum(v for k, v in taxonomy.items() if k not in ("invalid_smiles", "no_structure_emitted"))
    meaningful = chem >= noise  # most misses are real chemistry, not format failures

    if species_rate > 0.40:
        return (
            "KILL / EASY-AT-RESOLUTION — the published 5.4% was mostly isomer-lottery "
            "misspecification; at the fair sum-composition resolution the task is not hard."
        )
    if 0.10 <= species_rate <= 0.20:
        return (
            "IN-BAND / PROMISING — build the Harbor task; confirm with harbor analyze."
            + ("" if meaningful else " (BUT misses look format-driven — inspect before trusting.)")
        )
    if 0.20 < species_rate <= 0.40:
        return (
            "ABOVE-BAND-ish — a little easy at species resolution; consider a harder "
            "stratum (e.g. sphingo/glyco classes) or a stricter resolution before building."
        )
    # species_rate < 0.10
    if meaningful:
        return (
            "BELOW-BAND but MEANINGFUL — genuinely hard lipid assembly (real chemistry "
            "failures). Buildable, but flag the too-hard risk: may sit below 10%."
        )
    return (
        "BELOW-BAND & ARTIFACT-RISK — misses are format/parse noise, not chemistry. "
        "Fix the output contract or reconsider the task."
    )


def run(
    *,
    seed: int,
    n: int = 100,
    query_source: str | None = "abbreviation",
    model: str = probe_mod.DEFAULT_MODEL,
    artifact: Path = subset_mod.DEFAULT_ARTIFACT,
    out_dir: Path | None = None,
    client=None,
    goslin_parse=None,
    formula_from_smiles=None,
    inchikey_from_smiles=None,
    class_check=None,
) -> dict:
    if seed == SEED_42_FORBIDDEN:
        raise ValueError(
            "seed=42 is the reservoir seed defining the 1,500-name LMSD subsample; "
            "measuring on it contaminates the difficulty estimate. Use a NEW recorded seed."
        )
    out_dir = out_dir or _default_out(Path(__file__).parent / "runs")
    out_dir.mkdir(parents=True, exist_ok=True)

    goslin_parse = goslin_parse or ref_mod.default_goslin_parse
    formula_from_smiles = formula_from_smiles or ref_mod.default_formula_from_smiles
    inchikey_from_smiles = inchikey_from_smiles or ref_mod.default_inchikey_from_smiles
    class_check = class_check or ref_mod.class_backbone_ok

    sub = subset_mod.draw_subset(seed=seed, n=n, query_source=query_source, artifact=artifact)
    (out_dir / "subset.json").write_text(json.dumps(sub.as_card(), indent=2))

    client = client or probe_mod.make_client()

    raw_rows: list[dict] = []
    scores: list[score_mod.NameScore] = []

    for case in sub.cases:
        # neutral reference (name -> species components + formula) and gold formula
        ref = goslin_parse(case.name)
        gold_formula = formula_from_smiles(case.gold_smiles)
        gradeable = score_mod.gold_quality_gate(
            parsed=ref.parsed, ref_formula=ref.formula, gold_formula=gold_formula
        )

        pr = probe_mod.probe_name(client, case.name, model=model)
        model_smiles = pr.emitted.get("smiles") or None
        model_ik = pr.emitted.get("inchikey")
        if not ref_mod.is_valid_inchikey(model_ik):
            # derive the strict key from the model's own SMILES (RDKit, offline)
            model_ik = inchikey_from_smiles(model_smiles) if model_smiles else None
        model_formula = formula_from_smiles(model_smiles) if model_smiles else None
        class_ok = class_check(model_smiles, ref.lipid_class) if model_smiles else None

        s = score_mod.score_name(
            name=case.name,
            gradeable=gradeable,
            model_smiles=model_smiles,
            model_formula=model_formula,
            model_inchikey=model_ik,
            ref_formula=ref.formula,
            gold_inchikey=case.gold_inchikey,
            class_ok=class_ok,
            model_total_carbons=pr.emitted.get("total_carbons"),
            ref_total_carbons=ref.total_carbons,
            model_total_db=pr.emitted.get("total_double_bonds"),
            ref_total_db=ref.total_double_bonds,
            model_class=pr.emitted.get("lipid_class"),
            ref_class=ref.lipid_class,
        )
        scores.append(s)
        raw_rows.append(
            {
                "name": case.name,
                "gold_inchikey": case.gold_inchikey,
                "gold_smiles": case.gold_smiles,
                "reference": {
                    "parsed": ref.parsed,
                    "formula": ref.formula,
                    "species_string": ref.species_string,
                    "lipid_class": ref.lipid_class,
                    "total_carbons": ref.total_carbons,
                    "total_double_bonds": ref.total_double_bonds,
                    "gold_formula": gold_formula,
                    "gradeable": gradeable,
                },
                "model": pr.model,
                "error": pr.error,
                "emitted": pr.emitted,
                "derived": {
                    "model_formula": model_formula,
                    "model_inchikey": model_ik,
                    "class_ok": class_ok,
                },
                "score": {
                    "species_pass": s.species_pass,
                    "strict_block_pass": s.strict_block_pass,
                    "strict_full_pass": s.strict_full_pass,
                    "failure_bucket": s.failure_bucket,
                },
                "raw_response": pr.raw_response,
            }
        )

    (out_dir / "raw_outputs.jsonl").write_text(
        "\n".join(json.dumps(r) for r in raw_rows) + ("\n" if raw_rows else "")
    )

    agg = score_mod.aggregate(scores)
    verdict = _verdict(agg.species_match_rate, agg.failure_taxonomy)
    species_strict_gap = (
        (agg.species_match_rate - agg.strict_block_rate)
        if (agg.species_match_rate is not None and agg.strict_block_rate is not None)
        else None
    )

    card = {
        "spike": "lipid-shorthand #2 difficulty probe",
        "verdict": verdict,
        "anchors": {
            "lmsd_shorthand_exact_inchikey": LMSD_SHORTHAND_ANCHOR,
            "lmsd_blended_exact_inchikey": LMSD_BLENDED_ANCHOR,
        },
        "species_vs_strict_gap": species_strict_gap,  # misspecification magnitude
        "pins": {
            "seed": seed,
            "query_source": query_source,
            "n_requested": n,
            "n_drawn": len(sub.cases),
            "model": model,
            "subsample_sha256": _source_sha(artifact),
            "artifact": str(artifact),
        },
        "scores": agg.as_dict(),
    }
    (out_dir / "verdict.json").write_text(json.dumps(card, indent=2))
    card["out_dir"] = str(out_dir)
    print(f"[lipid-spike] verdict: {verdict}")
    print(
        f"[lipid-spike] species-match={agg.species_match_rate} "
        f"strict-block={agg.strict_block_rate} strict-full={agg.strict_full_rate} "
        f"(anchors: shorthand {LMSD_SHORTHAND_ANCHOR}, blended {LMSD_BLENDED_ANCHOR})"
    )
    print(
        f"[lipid-spike] gate: {agg.n_gradeable}/{agg.n_drawn} gradeable "
        f"(pass-rate {agg.gate_pass_rate}); species-vs-strict gap {species_strict_gap}"
    )
    print(f"[lipid-spike] failure taxonomy: {agg.failure_taxonomy}")
    print(f"[lipid-spike] saved run to {out_dir}")
    return card


def main() -> None:
    p = argparse.ArgumentParser(description="Lipid-shorthand difficulty spike (#2 viability probe).")
    p.add_argument("--seed", type=int, required=True, help="NEW recorded seed for the draw (not 42; e.g. 8617).")
    p.add_argument("--n", type=int, default=100)
    p.add_argument(
        "--query-source",
        default="abbreviation",
        choices=["abbreviation", "common_name", "systematic_name", "all"],
    )
    p.add_argument("--model", default=probe_mod.DEFAULT_MODEL)
    p.add_argument("--artifact", default=str(subset_mod.DEFAULT_ARTIFACT))
    p.add_argument("--out", default=None, help="override output dir (default: timestamped runs/)")
    args = p.parse_args()

    run(
        seed=args.seed,
        n=args.n,
        query_source=None if args.query_source == "all" else args.query_source,
        model=args.model,
        artifact=Path(args.artifact),
        out_dir=Path(args.out) if args.out else None,
    )


if __name__ == "__main__":
    main()
