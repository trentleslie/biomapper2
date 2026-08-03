"""Deliverable #2: the too-easy PROXY for the real Harbor container run.

This is a PROXY, not the real thing. The real TB-Science solver is a tool-using terminal
agent that can WRITE AND RUN CODE in a container; it is strictly stronger than anything
callable here without Docker. This runner instead escalates the naive probe along the one
axis we CAN vary without new infra: it turns EXTENDED THINKING ON (the 13.2% baseline was
thinking-disabled). A reasoning-enabled one-shot model is a strictly-tighter LOWER BOUND
on the tool-using agent than the naive probe -- it still cannot execute code.

Read:
  * proxy species-match jumps well past 20%  -> strong evidence a code-writing agent finds
    the task too easy (TOO-EASY).
  * proxy stays in-band (<=~20%)              -> INCONCLUSIVE: a code-executing agent is
    still strictly stronger and needs the real Harbor run to settle it.

Grades with the SAME species-composition scorer the Harbor verifier uses (pygoslin gate +
RDKit formula), on the SAME seed-8617 gradeable subset, so the number is directly
comparable to the 13.2% thinking-disabled baseline. Matched contrast: it also re-grades
the naive probe's own emitted SMILES on the identical name subset.

SOP: saves by default to a timestamped runs/ dir; pins seed, model, thinking budget,
source SHA, and the subset. Bounded spend (default n=35, one call each).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import sys
from pathlib import Path

# reuse the validated task grader + neutral adapter
TASK_TESTS = Path(__file__).resolve().parents[1] / "lipid-shorthand-structure" / "tests"
sys.path.insert(0, str(TASK_TESTS))
import harbor_grade  # noqa: E402
import reference_lipid as R  # noqa: E402
from grade import LipidAdapter  # noqa: E402

MODEL = "claude-opus-4-8"
GOLD_PATH = TASK_TESTS / "gold.jsonl"
# the naive thinking-disabled run artifact (for the matched-subset contrast)
NAIVE_RUN = (
    Path(__file__).resolve().parents[1]
    / "spike_lipid"
    / "runs"
    / "lipid_spike_20260722T064105Z"
    / "raw_outputs.jsonl"
)

PROMPT = (
    "You are given a lipid named in LIPID MAPS shorthand notation. Determine the chemical "
    "structure it denotes and return it as a SMILES string.\n\n"
    "Answer from your own knowledge only -- do not use any external tools, lookups, or "
    "network. Think carefully about the head-group class, the total acyl carbon count, the "
    "total number of double bonds, and any functional-group modifiers, then assemble a "
    "chemically valid structure.\n\n"
    "Return ONLY a single JSON object on the last line, of the form "
    '{{"smiles": "<SMILES>"}} -- no prose after it.\n\n'
    "Lipid shorthand: {name}"
)

_JSON_RE = re.compile(r"\{[^{}]*\"smiles\"[^{}]*\}")


def extract_smiles(text: str) -> str | None:
    matches = _JSON_RE.findall(text or "")
    for m in reversed(matches):
        try:
            obj = json.loads(m)
            s = obj.get("smiles")
            if s:
                return s.strip()
        except Exception:
            continue
    return None


def probe_thinking(client, name: str, *, effort: str, max_tokens: int) -> dict:
    # opus-4-8: extended thinking = adaptive + output_config.effort (budget_tokens 400s).
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            messages=[{"role": "user", "content": PROMPT.format(name=name)}],
        )
        text = "".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        )
        return {"smiles": extract_smiles(text), "stop_reason": getattr(resp, "stop_reason", None), "text": text}
    except Exception as exc:  # noqa: BLE001
        return {"smiles": None, "error": f"{type(exc).__name__}: {exc}"}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=8617)  # provenance only; subset is pinned
    p.add_argument("--n", type=int, default=35)
    p.add_argument("--effort", default="high", choices=["low", "medium", "high", "max"])
    p.add_argument("--max-tokens", type=int, default=12000)
    p.add_argument("--out", default=None)
    args = p.parse_args()

    gold = harbor_grade.load_gold(GOLD_PATH)[: args.n]
    subset_names = [c["name"] for c in gold]

    out_dir = Path(args.out) if args.out else (
        Path(__file__).resolve().parent
        / "runs"
        / f"lipid_proxy_thinking_{_dt.datetime.now(_dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)

    import anthropic

    client = anthropic.Anthropic()

    raw = []
    preds: dict[str, str] = {}
    for c in gold:
        r = probe_thinking(
            client, c["name"], effort=args.effort, max_tokens=args.max_tokens
        )
        if r.get("smiles"):
            preds[c["name"]] = r["smiles"]
        raw.append({"name": c["name"], **r})
    (out_dir / "raw_outputs.jsonl").write_text("\n".join(json.dumps(x) for x in raw) + "\n")

    adapter = LipidAdapter()
    res = harbor_grade.grade(gold=gold, predictions=preds, adapter=adapter, pass_threshold=0.40)
    agg = res.aggregate

    # matched contrast: re-grade the naive (thinking-disabled) SMILES on the SAME names
    naive_species = None
    if NAIVE_RUN.exists():
        naive_rows = {json.loads(l)["name"]: json.loads(l) for l in NAIVE_RUN.read_text().splitlines() if l.strip()}
        naive_preds = {}
        for n in subset_names:
            nr = naive_rows.get(n)
            sm = (nr.get("emitted") or {}).get("smiles") if nr else None
            if sm:
                naive_preds[n] = sm
        nres = harbor_grade.grade(gold=gold, predictions=naive_preds, adapter=adapter, pass_threshold=0.40)
        naive_species = nres.aggregate.species_match_rate

    def source_sha():
        card = R.__file__  # not used; pin the LMSD sha from the naive run card if present
        vc = NAIVE_RUN.parent / "verdict.json"
        if vc.exists():
            return json.loads(vc.read_text()).get("pins", {}).get("subsample_sha256")
        return None

    card = {
        "experiment": "lipid #2 too-easy PROXY (thinking ENABLED one-shot; NOT the real Harbor run)",
        "model": MODEL,
        "thinking": {"type": "adaptive", "effort": args.effort},
        "pins": {
            "seed": args.seed,
            "n": args.n,
            "subset_source": str(GOLD_PATH),
            "subsample_sha256": source_sha(),
        },
        "proxy_thinking_enabled": {
            "species_match_rate": agg.species_match_rate,
            "n_gradeable": agg.n_gradeable,
            "n_drawn": agg.n_drawn,
            "strict_block_rate": agg.strict_block_rate,
            "failure_taxonomy": agg.failure_taxonomy,
        },
        "baseline_thinking_disabled_same_subset": naive_species,
        "full_baseline_thinking_disabled_all_gradeable": 0.1323529411764706,  # 9/68, deduped
        "band": "TB-Science target solve rate 10-20%",
    }

    def read(rate):
        if rate is None:
            return "INCONCLUSIVE (no gradeable)"
        if rate > 0.40:
            return "TOO-EASY signal: a reasoning-only model already >40% -> a code-writing agent almost certainly scripts past the band."
        if rate > 0.20:
            return "ABOVE-BAND signal: reasoning-only pushes past 20%; a code agent (strictly stronger) likely TOO-EASY -> needs real Harbor run to confirm."
        return "IN-BAND / INCONCLUSIVE: reasoning-only stays <=20%; a code-executing agent is strictly stronger, so the too-easy question needs the real Harbor container run."
    card["verdict"] = read(agg.species_match_rate)

    (out_dir / "verdict.json").write_text(json.dumps(card, indent=2))
    print(f"[proxy] thinking-ENABLED species-match={agg.species_match_rate} "
          f"(gradeable {agg.n_gradeable}/{agg.n_drawn})")
    print(f"[proxy] SAME-subset thinking-DISABLED baseline={naive_species}")
    print(f"[proxy] full deduped baseline (9/68) = 0.1324")
    print(f"[proxy] verdict: {card['verdict']}")
    print(f"[proxy] saved to {out_dir}")


if __name__ == "__main__":
    main()
