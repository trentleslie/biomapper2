"""Offline re-score of the MetaboliteAnnotator run with the independent ID-equivalence judge.

NO BioMapper re-run: reads the persisted per-vocab mapped TSVs, rebuilds the merged per-mode frame
(``merge_vocab_runs``), and re-grades id-concordance three ways — strict exact-ID (sanity guard),
UniChem-UCI equivalence (a), InChIKey first-block bridge (b) — plus the gold-vs-chosen namespace
confusion matrix. Fails loud if the run dir is absent (the run must be on disk / restored).

Provenance pinned in the output: source SHA, biomapper2 commit, UniChem API version, timestamp.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .config import METABOLITEANNOTATOR_NEG, METABOLITEANNOTATOR_POS
from .scorers.name_hit_scorer import merge_vocab_runs, score_name_hit

_SOURCE_SHA = "d45fa683"
_BIOMAPPER2_COMMIT = "226a8710"
_UNICHEM_API = "v1 (UniChem 2.0)"
_MODES = (("positive", METABOLITEANNOTATOR_POS), ("negative", METABOLITEANNOTATOR_NEG))


def _mapped_tsvs(mode_dir: Path) -> list[Path]:
    """Per-vocab mapped TSVs, case-insensitive on the ``_mapped``/``_MAPPED`` suffix.

    The synthetic test fixtures use ``<VOCAB>_mapped.tsv``; the real ``cli_suite_20260723`` run uses
    ``metaboliteannotator-{mode}_{VOCAB}_MAPPED.tsv``. Glob both, de-duplicate, and sort for a stable
    merge order.
    """
    seen: dict[str, Path] = {}
    for pat in ("*_mapped.tsv", "*_MAPPED.tsv"):
        for p in mode_dir.glob(pat):
            seen[p.name] = p
    return [seen[name] for name in sorted(seen)]


def _load_merged(mode_dir: Path, config: Any) -> pd.DataFrame:
    """Rebuild the merged per-mode frame from the persisted per-vocab mapped TSVs."""
    tsvs = _mapped_tsvs(mode_dir)
    if not tsvs:
        raise FileNotFoundError(f"no *_mapped.tsv under {mode_dir}")
    dfs = [pd.read_csv(t, sep="\t", dtype=str, keep_default_na=False) for t in tsvs]
    return merge_vocab_runs(dfs, config)


def _summarize(result: dict[str, Any], persisted_strict: dict[str, Any] | None) -> dict[str, Any]:
    strict = result["id_concordance"]
    uci = result["id_concordance_uci_equivalence"]
    bridge = result["id_concordance_inchikey_bridge"]
    sanity = None
    if persisted_strict is not None:
        # A faithful reproduction must match BOTH the scored population and the concordant
        # count — matching concordant alone would certify a changed strict rate as identical.
        sanity = (
            int(persisted_strict.get("scored", -1)) == int(strict["scored"])
            and int(persisted_strict.get("concordant", -1)) == int(strict["concordant"])
        )
    return {
        "strict": {k: strict[k] for k in ("scored", "concordant", "concordance_rate")},
        "uci_equivalence": uci,
        "inchikey_bridge": bridge,
        "namespace_confusion": result["namespace_confusion"],
        "strict_sanity_ok": sanity,
    }


def rescore(run_dir: str | Path, out_dir: str | Path, *, judge: Any = None) -> dict[str, Any]:
    run_dir = Path(run_dir)
    base = run_dir / "metaboliteannotator"
    if not base.exists():
        raise FileNotFoundError(
            f"run dir {base} not found — restore the cli_suite_20260723 run to disk before re-scoring."
        )
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    summary: dict[str, Any] = {
        "provenance": {
            "source_sha": _SOURCE_SHA,
            "biomapper2_commit": _BIOMAPPER2_COMMIT,
            "unichem_api": _UNICHEM_API,
            "generated": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "run_dir": str(run_dir),
        }
    }
    for mode, config in _MODES:
        mode_dir = base / mode
        if not mode_dir.exists():
            continue
        merged = _load_merged(mode_dir, config)
        result = score_name_hit(merged, config, id_equivalence_judge=judge)
        persisted = None
        p = mode_dir / "name_hit_results.json"
        if p.exists():
            persisted = json.loads(p.read_text()).get("id_concordance")
        summary[mode] = _summarize(result, persisted)

    if judge is not None and hasattr(judge, "_client") and hasattr(judge._client, "cache_stats"):
        summary["cache_stats"] = judge._client.cache_stats()

    (out_dir / "id_equivalence_rescore.json").write_text(json.dumps(summary, indent=2))
    (out_dir / "id_equivalence_rescore.md").write_text(_render_md(summary))
    return summary


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def _render_md(summary: dict[str, Any]) -> str:
    lines = ["# ID-equivalence re-score (offline, cli_suite_20260723)", ""]
    prov = summary["provenance"]
    lines.append(
        f"> source_sha={prov['source_sha']} · biomapper2={prov['biomapper2_commit']} · "
        f"unichem={prov['unichem_api']} · {prov['generated']}"
    )
    lines.append("")
    lines.append("| Mode | strict exact-ID | UniChem-UCI (a) | InChIKey-bridge (b) | needs-verif (a/b) | sanity |")
    lines.append("|---|---|---|---|---|---|")
    for mode in ("positive", "negative"):
        m = summary.get(mode)
        if not m:
            continue
        s, a, b = m["strict"], m["uci_equivalence"], m["inchikey_bridge"]
        # Tri-state: True->OK, False->MISMATCH, None (no persisted baseline)->n/a. A truthiness
        # collapse would mislabel absent baseline data as a scoring discrepancy.
        sanity_cell = {True: "OK", False: "MISMATCH", None: "n/a"}[m["strict_sanity_ok"]]
        # Equivalence fractions are concordant/evaluable (evaluable = scored - needs), matching
        # the rate; strict has no unresolved rows so its denominator stays the full scored count.
        lines.append(
            f"| {mode} | {_pct(s['concordance_rate'])} ({s['concordant']}/{s['scored']}) | "
            f"{_pct(a['concordance_rate'])} ({a['concordant']}/{a['evaluable']}) | "
            f"{_pct(b['concordance_rate'])} ({b['concordant']}/{b['evaluable']}) | "
            f"{a['needs_verification']}/{b['needs_verification']} | "
            f"{sanity_cell} |"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Offline ID-equivalence re-score (no BioMapper re-run).")
    ap.add_argument(
        "--run-dir",
        default="/home/trentleslie/external_benchmark_runs/cli_suite_20260723",
        help="run dir containing metaboliteannotator/{positive,negative}/metaboliteannotator-{mode}_{VOCAB}_MAPPED.tsv",
    )
    ap.add_argument("--out", default=None, help="output dir (default: <run-dir>/id_equivalence_rescore)")
    ap.add_argument("--cache", default="studies/external_benchmarks/.unichem_cache.json")
    args = ap.parse_args(argv)

    from .scorers.id_equivalence import UniChemClient, UniChemIdEquivalenceJudge
    from .scorers.independent_inchikey import PubChemInChIKeyResolver

    client = UniChemClient(cache_path=args.cache)
    judge = UniChemIdEquivalenceJudge(client, pubchem_resolver=PubChemInChIKeyResolver())
    out = args.out or str(Path(args.run_dir) / "id_equivalence_rescore")
    summary = rescore(args.run_dir, out, judge=judge)
    print(f"[id-equivalence] wrote {out}/id_equivalence_rescore.json")
    for mode in ("positive", "negative"):
        if mode in summary:
            a = summary[mode]["uci_equivalence"]
            b = summary[mode]["inchikey_bridge"]
            print(f"  {mode}: strict={_pct(summary[mode]['strict']['concordance_rate'])} "
                  f"UCI={_pct(a['concordance_rate'])} bridge={_pct(b['concordance_rate'])}")


if __name__ == "__main__":
    main()
