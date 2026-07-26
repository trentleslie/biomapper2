"""Offline re-score of the MetaboliteAnnotator id-concordance with the fixed gold namespacer.
No Kestrel, no BioMapper re-run — reads the saved per-vocab MAPPED TSVs from the cli_suite run."""
from __future__ import annotations
import sys
import pandas as pd
from pathlib import Path

# Repo root on sys.path so `studies.*` imports resolve when run directly (mirrors the repo's
# pytest `pythonpath = ["."]` setting, which only applies under pytest, not a bare script).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studies.external_benchmarks.config import METABOLITEANNOTATOR_POS, METABOLITEANNOTATOR_NEG
from studies.external_benchmarks.scorers.name_hit_scorer import merge_vocab_runs, score_name_hit

RUN = Path("/home/trentleslie/external_benchmark_runs/cli_suite_20260723/metaboliteannotator")
VOCABS = ("CHEBI", "HMDB", "PUBCHEM", "KEGG")

for mode, cfg in (("positive", METABOLITEANNOTATOR_POS), ("negative", METABOLITEANNOTATOR_NEG)):
    dfs = [pd.read_csv(RUN / mode / f"metaboliteannotator-{mode}_{v}_MAPPED.tsv", sep="\t", dtype=str).fillna("")
           for v in VOCABS]
    merged = merge_vocab_runs(dfs, cfg)
    res = score_name_hit(merged, cfg, vocab="+".join(VOCABS), oracle=None)
    idc = res["id_concordance"]
    print(f"[{mode}] id-concordance: {idc['concordant']}/{idc['scored']} "
          f"= {(idc['concordance_rate'] or 0):.1%}  "
          f"(excluded non-chemical: {idc.get('excluded_nonchemical')})")
