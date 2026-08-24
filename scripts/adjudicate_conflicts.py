"""Third-party adjudication of the 11 name-match conflicts.

The conflict set was built by comparing NECS's curated gold InChIKey against Arivale's vendor
identifiers resolved through PubChem. That tells us the two sides disagree; it does NOT tell us
which side is wrong. Unit 0 needs to know, because the precision claim assumes the NECS gold is the
reliable side.

So: resolve the COMPOUND NAME independently through PubChem (a third path, used by neither side of
the original comparison) and see which side it agrees with.
"""

import csv
import os
import socket
import time
import urllib.parse
import urllib.request

_real = socket.getaddrinfo
socket.getaddrinfo = lambda h, p, f=0, t=0, pr=0, fl=0: _real(h, p, socket.AF_INET, t, pr, fl)

PUG = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
SRC = os.path.expanduser("~/external_benchmark_runs/necs_arivale_baseline_20260804/name_match_precision.csv")


def name_to_keys(name):
    """All InChIKeys PubChem returns for this NAME. Empty body is retried, never a negative."""
    url = f"{PUG}/compound/name/{urllib.parse.quote(name)}/property/InChIKey/TXT"
    for attempt in range(1, 5):
        try:
            with urllib.request.urlopen(url, timeout=45) as r:
                body = r.read().decode("utf-8", "replace").strip()
            if body:
                return [ln.strip() for ln in body.splitlines() if ln.strip()], "ok"
            time.sleep(1.5 * attempt)  # empty body: throttle, not absence
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return [], "no-match"
            time.sleep(1.5 * attempt)
        except Exception:
            time.sleep(1.5 * attempt)
    return [], "THROTTLED"


rows = [r for r in csv.DictReader(open(SRC)) if r["verdict"] == "CONFLICT"]
print(f"adjudicating {len(rows)} conflicts via an INDEPENDENT third path (PubChem name lookup)\n")
print(f"{'compound':34s} {'NECS gold':16s} {'Arivale ids':16s} {'PubChem(name)':16s} verdict")
print("-" * 104)

tally = {"arivale_right": 0, "necs_right": 0, "neither": 0, "unresolved": 0}
detail = []
for r in rows:
    name = r["necs_name"]
    keys, status = name_to_keys(name)
    blocks = {k.split("-")[0] for k in keys}
    necs_b = r["necs_block"]
    ariv_b = set(x for x in r["arivale_blocks"].split("|") if x)
    if not blocks:
        v = f"UNRESOLVED({status})"
        tally["unresolved"] += 1
    elif necs_b in blocks and not (ariv_b & blocks):
        v = "NECS right"
        tally["necs_right"] += 1
    elif (ariv_b & blocks) and necs_b not in blocks:
        v = "ARIVALE right, NECS GOLD WRONG"
        tally["arivale_right"] += 1
    elif necs_b in blocks and (ariv_b & blocks):
        v = "both present (multi-form)"
        tally["neither"] += 1
    else:
        v = "neither matches PubChem"
        tally["neither"] += 1
    shown = sorted(blocks)[0] if blocks else "-"
    print(f"{name[:33]:34s} {necs_b:16s} {sorted(ariv_b)[0] if ariv_b else '-':16s} {shown:16s} {v}")
    detail.append(
        {
            "name": name,
            "necs": necs_b,
            "arivale": "|".join(sorted(ariv_b)),
            "pubchem_name": "|".join(sorted(blocks)),
            "verdict": v,
        }
    )

print()
for k, n in tally.items():
    print(f"  {k:16s} {n}")
print()
print("  >>> 'ARIVALE right, NECS GOLD WRONG' means the conflict is a GOLD DEFECT,")
print("  >>> not a name-matching error. Those rows cannot count toward the precision claim.")

out = os.path.expanduser("~/external_benchmark_runs/cohort_panels_20260804/conflict_adjudication.csv")
with open(out, "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(detail[0]))
    w.writeheader()
    w.writerows(detail)
print(f"\nsaved -> {out}")
