"""Difficulty-probe spike for benchmark candidate #2 — lipid shorthand -> structure.

A cheap lower-bound probe of whether the LMSD lipid-shorthand name->structure task
(published Top-1 = 5.4% at exact-InChIKey) is a *well-specified, meaningfully hard*
TB-Science task once graded at the resolution the shorthand actually specifies — the
SUM COMPOSITION (head group + total carbons + total double bonds + functional groups)
— rather than as an exact-sn-isomer lottery.

The crux that keeps #2 out of the #3 ambiguous-name "completeness trap": a shorthand
such as ``TG 57:6`` denotes a SINGLE, well-defined thing at species resolution. The
valid answer is that one sum-composition identity, not an open enumeration of every
acyl-chain / sn-position isomer. So this is a single-answer-per-shorthand task; there
is no referent catalogue to be incomplete against.

Neutral gold + grader, never BioMapper:
  * ``pygoslin`` (LIPID MAPS shorthand grammar, third-party) parses the shorthand to a
    normalized species-level form and its sum formula  -> the answer key at the right
    resolution, plus a gold-quality GATE (the neutral name->formula must agree with the
    LMSD structure->formula, else the row is dropped as ungradeable).
  * ``RDKit`` computes molecular formula + InChIKey from the model's SMILES (offline,
    deterministic) — the same thing a ``no-network`` terminal agent would do.

Units (each independently testable; mirrors ``spike_ambname``):
  subset.py     - draw the shorthand pool (LMSD ``query_source == abbreviation``)
  reference.py  - NEUTRAL sum-composition reference (pygoslin) + structure->formula/key (RDKit)
  score.py      - pure scoring: gold-quality gate, species-match, strict-match, failure taxonomy
  probe.py      - the naive one-shot model probe (a strict lower bound)
  run_spike.py  - orchestrator; save-by-default, timestamped, pins seed/model/source SHA
"""
