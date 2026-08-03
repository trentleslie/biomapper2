"""Orchestrator: subset -> probe -> resolve -> score -> verdict, save-by-default.

SOP (institutional artifact hygiene): results persist BY DEFAULT to a timestamped
path - never behind a flag. ``--out`` is an OVERRIDE, not the only way to save.
The run card pins everything needed to reproduce: source-data SHA (from the Pham
dataset card), the NEW seed, the model id/version, and both scores at both
granularities. The path is printed when the run finishes.

This is the ONLY module that spends money (the paid model calls). It is not run
by the offline test suite; the deterministic units it calls are each tested with
fakes/fixtures.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
from pathlib import Path

from . import probe as probe_mod
from . import resolve as resolve_mod
from . import score as score_mod
from . import subset as subset_mod

BIOMAPPER_ANCHOR = 0.417  # 625/1500, non-lipid stratum. Reference only.
SEED_42_FORBIDDEN = 42  # defines the 1,500-name eval set; never measure on it


def _source_sha(artifact: Path) -> str | None:
    card = artifact / "dataset_card.json"
    if not card.exists():
        return None
    try:
        return json.loads(card.read_text()).get("source_sha256")
    except Exception:
        return None


def _default_out(base: Path) -> Path:
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return base / f"ambname_spike_{stamp}"


def _verdict(any_member_block: float | None) -> str:
    """Asymmetric decision rule (spec). Uses the block-granularity any-member
    rate (the softest, most generous-to-the-model number) as the KILL trigger."""
    if any_member_block is None:
        return "INCONCLUSIVE (no scorable names)"
    if any_member_block >= 0.40:
        return "KILL / change-scoring (naive one-shot matches gold too often)"
    if any_member_block <= 0.20:
        return "ESCALATE to the real Harbor harness (hard in one shot; NOT a greenlight)"
    return "AMBIGUOUS - inspect full-set recall and per-name detail before deciding"


def run(
    *,
    seed: int,
    n: int = 75,
    stratum: str | None = "non_lipid",
    model: str = probe_mod.DEFAULT_MODEL,
    artifact: Path = subset_mod.DEFAULT_ARTIFACT,
    out_dir: Path | None = None,
    client=None,
    pubchem: resolve_mod.PubChemResolver | None = None,
) -> dict:
    if seed == SEED_42_FORBIDDEN:
        raise ValueError(
            "seed=42 defines the 1,500-name benchmark eval set; measuring on it "
            "contaminates the difficulty estimate. Use a NEW recorded seed."
        )
    out_dir = out_dir or _default_out(Path(__file__).parent / "runs")
    out_dir.mkdir(parents=True, exist_ok=True)

    sub = subset_mod.draw_subset(seed=seed, n=n, stratum=stratum, artifact=artifact)
    (out_dir / "subset.json").write_text(json.dumps(sub.as_card(), indent=2))

    client = client or probe_mod.make_client()
    pubchem = pubchem or resolve_mod.PubChemResolver()

    raw_rows: list[dict] = []
    block_scores: list[score_mod.NameScore] = []
    full_scores: list[score_mod.NameScore] = []
    lane_counts: dict[str, int] = {lane.value: 0 for lane in resolve_mod.Lane}
    n_referents = 0

    for case in sub.cases:
        pr = probe_mod.probe_name(client, case.name, model=model)
        resolved = [resolve_mod.resolve_referent(r, pubchem=pubchem) for r in pr.referents]
        n_referents += len(resolved)
        for res in resolved:
            lane_counts[res.lane.value] += 1
        predicted = [res.inchikey for res in resolved if res.inchikey]

        for gran, bucket in (("block", block_scores), ("full", full_scores)):
            bucket.append(
                score_mod.score_name(
                    name=case.name,
                    gold_inchikeys=case.gold_inchikeys,
                    predicted_inchikeys=predicted,
                    granularity=gran,
                )
            )
        raw_rows.append(
            {
                "name": case.name,
                "gold_inchikeys": list(case.gold_inchikeys),
                "model": pr.model,
                "error": pr.error,
                "emitted": pr.referents,
                "resolved": [{"inchikey": r.inchikey, "lane": r.lane.value} for r in resolved],
                "raw_response": pr.raw_response,
            }
        )

    (out_dir / "raw_outputs.jsonl").write_text(
        "\n".join(json.dumps(r) for r in raw_rows) + ("\n" if raw_rows else "")
    )

    agg_block = score_mod.aggregate(block_scores, "block")
    agg_full = score_mod.aggregate(full_scores, "full")
    unresolved_rate = (
        lane_counts[resolve_mod.Lane.UNRESOLVED.value] / n_referents if n_referents else None
    )
    verdict = _verdict(agg_block.any_member_rate)

    card = {
        "spike": "ambiguous-name #3 viability probe",
        "verdict": verdict,
        "biomapper_anchor_nonlipid": BIOMAPPER_ANCHOR,
        "pins": {
            "seed": seed,
            "stratum": stratum,
            "n_requested": n,
            "n_drawn": len(sub.cases),
            "model": model,
            "source_sha256": _source_sha(artifact),
            "artifact": str(artifact),
        },
        "scores": {"block": agg_block.as_dict(), "full": agg_full.as_dict()},
        "resolver": {
            "unresolved_rate": unresolved_rate,
            "lane_counts": lane_counts,
            "n_referents_emitted": n_referents,
        },
    }
    (out_dir / "verdict.json").write_text(json.dumps(card, indent=2))
    card["out_dir"] = str(out_dir)
    print(f"[ambname-spike] verdict: {verdict}")
    print(f"[ambname-spike] block any-member={agg_block.any_member_rate} "
          f"full any-member={agg_full.any_member_rate} "
          f"(BioMapper anchor {BIOMAPPER_ANCHOR})")
    print(f"[ambname-spike] saved run to {out_dir}")
    return card


def main() -> None:
    p = argparse.ArgumentParser(description="Ambiguous-name difficulty spike (naive-model KILL filter).")
    p.add_argument("--seed", type=int, required=True, help="NEW recorded seed for the subset draw (not 42).")
    p.add_argument("--n", type=int, default=75)
    p.add_argument("--stratum", default="non_lipid", choices=["non_lipid", "lipid", "both"])
    p.add_argument("--model", default=probe_mod.DEFAULT_MODEL)
    p.add_argument("--artifact", default=str(subset_mod.DEFAULT_ARTIFACT))
    p.add_argument("--out", default=None, help="override output dir (default: timestamped runs/)")
    args = p.parse_args()

    run(
        seed=args.seed,
        n=args.n,
        stratum=None if args.stratum == "both" else args.stratum,
        model=args.model,
        artifact=Path(args.artifact),
        out_dir=Path(args.out) if args.out else None,
    )


if __name__ == "__main__":
    main()
