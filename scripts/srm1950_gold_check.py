"""Is the silently-wrong-gold defect Metabolon-specific, or a property of curated gold generally?

NECS gold (Metabolon) is wrong at ~1.6%: well-formed InChIKeys naming the wrong molecule. SRM1950 is
NIST Standard Reference Material 1950, curated by a different party entirely. If its gold shows the
same defect, the finding is about curation practice. If it is clean, the finding narrows to Metabolon
and the "about the field" framing is not earned.

Same third-path method: resolve the metabolite NAME through PubChem, a route used by neither the
resolver nor the gold, and see whether it agrees with the gold's InChIKey.
"""
import csv, json, os, re, socket, time, urllib.error, urllib.parse, urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_r = socket.getaddrinfo
socket.getaddrinfo = lambda h, p, f=0, t=0, pr=0, fl=0: _r(h, p, socket.AF_INET, t, pr, fl)

PUG = "https://pubchem.ncbi.nlm.nih.gov/rest/pug"
SRC = Path(os.path.expanduser(
    "~/external_benchmark_runs/srm1950_dev_rerun_20260722/srm1950_CHEBI_MAPPED.tsv"))
OUT = Path(os.path.expanduser("~/external_benchmark_runs/cohort_panels_20260804"))
CACHE = OUT / "srm1950_name_lookup_cache.json"
SAMPLE = 150  # bounded sample; enough to distinguish "clean" from "~1.6%" is not, but see note below


def variants(n):
    out, seen = [], set()
    for v in (n, n.rstrip("*").strip(), re.sub(r"\s*\([^)]*\)\s*$", "", n.rstrip("*")).strip()):
        v = v.strip()
        if v and v not in seen:
            seen.add(v); out.append(v)
    return out


def one(q):
    url = f"{PUG}/compound/name/{urllib.parse.quote(q)}/property/InChIKey/TXT"
    for a in range(1, 6):
        try:
            with urllib.request.urlopen(url, timeout=45) as r:
                b = r.read().decode("utf-8", "replace").strip()
            if b:
                return [l.strip() for l in b.splitlines() if l.strip()], "ok"
            time.sleep(1.5 * a)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return [], "no-match"
            time.sleep(1.5 * a)
        except Exception:
            time.sleep(1.5 * a)
    return [], "THROTTLED"


def resolve(n, cache):
    for q in variants(n):
        if q in cache:
            keys, st = cache[q]["keys"], cache[q]["status"]
        else:
            keys, st = one(q)
            if st in ("ok", "no-match"):
                cache[q] = {"keys": keys, "status": st}
        if keys:
            return {k.split("-")[0] for k in keys}
    return set()


rows = [r for r in csv.DictReader(open(SRC, encoding="utf-8"), delimiter="\t")
        if len((r.get("gold_inchikey") or "").split("-")) >= 2
        and len((r.get("gold_inchikey") or "").split("-")[0]) == 14]
print(f"SRM1950 rows with a well-formed gold InChIKey: {len(rows)}")
rows = rows[:SAMPLE]
print(f"checking a bounded sample of {len(rows)} via PubChem name lookup, 4 workers...\n", flush=True)

cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
with ThreadPoolExecutor(max_workers=4) as ex:
    got = list(ex.map(lambda r: resolve(r["metabolite_name"], cache), rows))
CACHE.write_text(json.dumps(cache, indent=1))

t = Counter()
bad = []
for r, blocks in zip(rows, got):
    g = r["gold_inchikey"].split("-")[0]
    if not blocks:
        t["UNRESOLVED"] += 1
    elif g in blocks:
        t["GOLD_OK"] += 1
    else:
        t["GOLD_DISAGREES"] += 1
        bad.append((r["metabolite_name"], g, "|".join(sorted(blocks))[:44]))

for k, n in t.most_common():
    print(f"  {k:16s} {n:4d}")
adj = t["GOLD_OK"] + t["GOLD_DISAGREES"]
if adj:
    print(f"\n  adjudicable        : {adj}")
    print(f"  gold disagrees with an independent name lookup: {t['GOLD_DISAGREES']} "
          f"({t['GOLD_DISAGREES']/adj:.1%})")
    print(f"  NECS/Metabolon comparable rate                : 1.6%")
print("\n  disagreements (gold block vs PubChem-by-name):")
for n, g, p in bad[:20]:
    print(f"    {n[:40]:42s} gold={g}  pubchem={p}")
