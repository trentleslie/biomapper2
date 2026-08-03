"""Ambiguous-name difficulty spike (#3 viability probe).

A cheap early-KILL filter that decides whether the ambiguous-name metabolite
resolution task is hard enough (TB-Science's 10-20% solve band) to build as a
full Harbor task. See the spec:

    Active 🎯/Work/Projects/Terminal-Bench Science/
        TB-Science - Ambiguous-Name Difficulty Spike.md

Design invariants (do not violate — they are what make the number valid):

* Grading NEVER uses BioMapper. A BioMapper-adjacent task graded with BioMapper
  is circular. All resolvers here are neutral third parties: direct InChIKey
  emission, RDKit (offline, deterministic) from an emitted SMILES, and PubChem
  name -> CID -> InChIKey (network). ``resolve.py`` owns this.
* The probe is a naive one-shot model (no tools, no network for the model), a
  strict LOWER BOUND on the real tool-using terminal agent. High any-member
  score => KILL/change-scoring. Low => ESCALATE, never a greenlight.
* Subset is drawn from the 887 MetaNetX-cap-PubChem AGREEMENT cases with a NEW
  recorded seed, NOT the seed-42 draw that defines the 1,500 eval set.
* Results persist by default to a timestamped path; the source-data SHA, seed,
  and model id/version are pinned alongside.
"""

from __future__ import annotations

__all__ = ["subset", "resolve", "score", "probe", "run_spike"]
