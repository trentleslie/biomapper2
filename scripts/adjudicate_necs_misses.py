"""Adjudicate the NECS benchmark misses against an INDEPENDENT third path.

Every NECS number shipped on 2026-08-04 (662/796 correct, the 134-miss disposition triage, the EITL
campaign sizing) is scored against the panel's curated ``gold_inchikey``. Unit 0 of the cross-cohort
benchmark established that this column is silently wrong at ~1.6%: well-formed InChIKeys naming the
wrong molecule, which pass validation, score confidently, and penalize the resolver for being right.

A "miss" is a row where BioMapper's predicted structure disagrees with that gold. If the gold can be
wrong, some misses are not resolver errors at all. This asks a third party:

    resolve the COMPOUND NAME through PubChem, a path neither BioMapper nor the gold used,
    and see which side it agrees with.

  GOLD_DEFECT      PubChem matches BioMapper's prediction, NOT the gold -> BioMapper was right.
  GOLD_CONFIRMED   PubChem matches the gold, NOT the prediction        -> a genuine miss.
  BOTH             PubChem returns both blocks (multi-form record)     -> not adjudicable this way.
  NEITHER          PubChem matches neither                             -> both may be wrong.
  UNRESOLVED       PubChem cannot resolve the name, or throttled       -> excluded from the rate.

Discipline (per docs/solutions/best-practices/calibrating-external-crosswalk-null-results):
an empty HTTP body is a THROTTLE, retried, and never counted as a no-match. Results are cached to
disk so a re-run costs nothing. IPv4 is forced.
"""

from __future__ import annotations

import csv
import json
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_real = socket.getaddrinfo
socket.getaddrinfo = lambda h, p, f=0, t=0, pr=0, fl=0: _real(h, p, socket.AF_INET, t, pr, fl)

PUG = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
RUNS = Path(os.path.expanduser("~/external_benchmark_runs"))
SRC = RUNS / "necs_characterization_20260804" / "miss_dispositions.csv"
OUT = RUNS / "cohort_panels_20260804"
CACHE = OUT / "necs_miss_name_lookup_cache.json"
WORKERS = 4  # the UniChem episode: 10 concurrent workers produced 53% empty bodies


def query_names(name: str) -> list[str]:
    """Metabolon name variants worth trying, most faithful first.

    Trailing ``*`` marks a tentative identification and is not part of the name. A parenthetical
    suffix is usually a chain/position annotation the registry does not carry.
    """
    out, seen = [], set()
    for v in (name, name.rstrip("*").strip(), re.sub(r"\s*\([^)]*\)\s*$", "", name.rstrip("*")).strip()):
        v = v.strip()
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _lookup_one(q: str) -> tuple[list[str], str]:
    url = f"{PUG}/compound/name/{urllib.parse.quote(q)}/property/InChIKey/TXT"
    for attempt in range(1, 6):
        try:
            with urllib.request.urlopen(url, timeout=45) as r:
                body = r.read().decode("utf-8", "replace").strip()
            if body:
                return [ln.strip() for ln in body.splitlines() if ln.strip()], "ok"
            time.sleep(1.5 * attempt)  # empty body is a throttle, never a negative
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return [], "no-match"
            time.sleep(1.5 * attempt)
        except Exception:
            time.sleep(1.5 * attempt)
    return [], "THROTTLED"


def resolve(name: str, cache: dict) -> tuple[set[str], str]:
    """First variant that resolves wins. Only complete successes are cached."""
    for q in query_names(name):
        if q in cache:
            keys, status = cache[q]["keys"], cache[q]["status"]
        else:
            keys, status = _lookup_one(q)
            if status in ("ok", "no-match"):  # never persist a throttle
                cache[q] = {"keys": keys, "status": status}
        if keys:
            return {k.split("-")[0] for k in keys}, status
    return set(), status


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    rows = list(csv.DictReader(open(SRC, encoding="utf-8")))
    # the 10 corrupt-gold rows are already known bad; adjudicating them proves nothing new
    todo = [r for r in rows if r["disposition"] != "DATA_DEFECT_corrupt_gold"]
    print(f"misses: {len(rows)} total, adjudicating {len(todo)} (10 known-corrupt excluded)")
    print(f"resolving names via PubChem, {WORKERS} workers...", flush=True)

    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        resolved = list(ex.map(lambda r: resolve(r["name"], cache), todo))
    CACHE.write_text(json.dumps(cache, indent=1))

    tally, per_disp, out_rows = Counter(), {}, []
    for r, (blocks, status) in zip(todo, resolved):
        pred, gold = r["predicted_block"], r["gold_block"]
        if not blocks:
            v = "UNRESOLVED"
        elif pred and pred in blocks and gold not in blocks:
            v = "GOLD_DEFECT"
        elif gold in blocks and (not pred or pred not in blocks):
            v = "GOLD_CONFIRMED"
        elif pred and pred in blocks and gold in blocks:
            v = "BOTH"
        else:
            v = "NEITHER"
        tally[v] += 1
        per_disp.setdefault(r["disposition"], Counter())[v] += 1
        out_rows.append({**r, "pubchem_blocks": "|".join(sorted(blocks)), "adjudication": v})

    print()
    for k, n in tally.most_common():
        print(f"  {k:16s} {n:4d}")
    adjudicable = tally["GOLD_DEFECT"] + tally["GOLD_CONFIRMED"]
    print()
    if adjudicable:
        print(f"  adjudicable misses          : {adjudicable}")
        print(f"  of those, GOLD was WRONG    : {tally['GOLD_DEFECT']} " f"({tally['GOLD_DEFECT']/adjudicable:.0%})")
        print(
            f"  of those, BioMapper was wrong: {tally['GOLD_CONFIRMED']} "
            f"({tally['GOLD_CONFIRMED']/adjudicable:.0%})"
        )

    print("\n  by shipped disposition:")
    hdr = ["GOLD_DEFECT", "GOLD_CONFIRMED", "BOTH", "NEITHER", "UNRESOLVED"]
    print(f"    {'disposition':30s} " + " ".join(f"{h[:12]:>12s}" for h in hdr))
    for d, c in sorted(per_disp.items(), key=lambda kv: -sum(kv[1].values())):
        print(f"    {d:30s} " + " ".join(f"{c[h]:>12d}" for h in hdr))

    print("\n  examples where the GOLD was wrong and BioMapper was right:")
    for r in [x for x in out_rows if x["adjudication"] == "GOLD_DEFECT"][:12]:
        print(
            f"    {r['name'][:34]:36s} gold={r['gold_block']}  biomapper={r['predicted_block']}"
            f"  [{r['disposition']}]"
        )

    with open(OUT / "necs_miss_adjudication.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out_rows[0]))
        w.writeheader()
        w.writerows(out_rows)
    (OUT / "necs_miss_adjudication.json").write_text(
        json.dumps(
            {
                "n_misses_total": len(rows),
                "n_adjudicated": len(todo),
                "tally": dict(tally),
                "by_disposition": {d: dict(c) for d, c in per_disp.items()},
                "source": str(SRC),
                "method": "PubChem name lookup, independent of both BioMapper and gold",
            },
            indent=2,
        )
    )
    print(f"\nsaved -> {OUT}")


if __name__ == "__main__":
    main()
