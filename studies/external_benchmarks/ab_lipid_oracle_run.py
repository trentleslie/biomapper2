"""Unit 4 (operator) — the live 2x2 A/B that produces the sprint number. SUPERVISED; ``# pragma: no cover``.

The falsifiable logic (transition matrix, provenance guard, oracle) is unit-tested in the pure modules;
this driver only wires them to the live dev APIs and is never run in pytest.

The 2x2 = {Kestrel fix off/on} x {provided-id oracle off/on}, over the two viable pairs (necs<->arivale,
necs<->xuetal; llfs/blsa are coverage-limited, Unit 0). It differs on exactly two axes:

  - fix axis  : which biomapper instance resolves the NAME-only panels — BASELINE_API (unpatched) vs
                TREATMENT_API (Unit-3-patched). BioMapper is run name-only (Arm M), never fed the
                HMDB/PubChem ids the oracle uses (KD3 disjointness).
  - oracle axis: how each side's INDEPENDENT structure map is built — ``block_for_name`` only
                (oracle-off; lipids refuse) vs ``block_for_provided`` from the curator ids (oracle-on).

Env: BASELINE_API / TREATMENT_API (full /api/v1/map/batch URLs), key file /tmp/.bmk (header only, never
persisted). Persists by default (R23) to ~/external_benchmark_runs/ab_lipid_oracle_<ts>/ with a
version-pinned manifest; the oracle cache is namespaced per arm; the run ABORTS if any block feeding the
metric is untagged (the certify_links_tagged canary).
"""

from __future__ import annotations

# pragma: no cover  — every path below is a supervised live operator step; pytest must not import-run it.


def provided_id_kwargs(gold_row: dict[str, str]) -> dict[str, str | None]:
    """Pure: map a cohort/NECS source row to the ``block_for_provided`` kwargs (KD1 order).

    Prefers the offline gold InChIKey, then HMDB, then PubChem CID. Empty/absent columns -> None so the
    resolver falls through. This is the only piece the tests exercise; the resolution + live loop are
    operator-gated below.
    """
    def _clean(v: str | None) -> str | None:
        s = (v or "").strip()
        return s or None

    return {
        "inchikey": _clean(gold_row.get("gold_inchikey")),
        "hmdb": _clean(gold_row.get("gold_hmdb") or gold_row.get("HMDB_ID")),
        "pubchem": _clean(gold_row.get("gold_pubchem") or gold_row.get("PubChem_ID")),
    }


def main() -> None:  # pragma: no cover
    raise SystemExit(
        "Operator step. Run under supervision with BASELINE_API/TREATMENT_API set and /tmp/.bmk present; "
        "stand up the two local uvicorn instances (baseline + Unit-3-patched treatment) first, verify the "
        "treatment emits category/prefix, then this driver resolves the 2 viable pairs name-only through "
        "each, builds provided-id ProvidedBlock maps (oracle-on) vs name-only (oracle-off), certifies via "
        "certify_links_tagged (aborting on any untagged block), and writes the build_report 2x2 + manifest."
    )


if __name__ == "__main__":  # pragma: no cover
    main()
