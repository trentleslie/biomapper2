"""Controlled competitor head-to-head for the gene/protein arm.

The *first-of-its-kind* comparison the preprint headline needs: run the incumbent
gene/protein identifier-mapping web services (g:Convert, bioDBnet, UniProt ID Mapping) on the
**same input rows** BioMapper was benchmarked on, and score every tool with the **identical**
``curie_scorer`` rule and gold. That yields a genuine same-protocol head-to-head instead of
comparing BioMapper against numbers a paper produced under a different protocol.

Design pillars (harness learnings folded in):

  - **One comparable metric across tools.** Every tool is scored by the SAME
    ``scorers.curie_scorer.score_curie`` (Top-1 CURIE-equality accuracy on the rows carrying a
    held-out gold cross-ref). Nothing is renormalized per tool.
  - **A no-mapping is a MISS, not an error.** A row a tool simply can't map counts against its
    coverage/accuracy honestly. Only a genuine *outage* (network/5xx after retries) is an error —
    and it is fail-loud (``CompetitorOutageError``), never silently scored as 0%.
  - **Representation alignment, applied uniformly.** Each tool's returned local IDs are packed
    into the SAME CURIE convention the gold uses (canonical prefix; Ensembl/RefSeq version
    suffixes stripped) so a tool is never penalized for a formatting convention rather than a real
    mapping capability. This is done in how the prediction cell is *built* — the scorer itself is
    reused verbatim.
  - **Protocol deltas are recorded, not hidden.** A target namespace a tool cannot express (e.g.
    the source/target scope a hosted service natively supports) is recorded as an
    ``unsupported_target`` on the run and surfaced in the head-to-head, so the reader can see where
    a tool's native scope differs from the benchmark's.

These are hosted, deterministic web services (NOT Kestrel/LLM), so cost is low. None of the three
requires an API key at time of build (all public REST); see ``ACCESS_NOTES``. The live head-to-head
is a separate, gated step — this package builds and unit-tests the machinery only.
"""

from __future__ import annotations

# API access needs, surfaced for the gated run (no secrets are hardcoded anywhere).
ACCESS_NOTES: dict[str, str] = {
    "gconvert": "Public g:Profiler REST API (biit.cs.ut.ee/gprofiler/api). No API key/account.",
    "biodbnet": "Public bioDBnet db2db REST API (biodbnet-abcc.ncifcrf.gov). No API key/account.",
    "uniprot_idmapping": "Public UniProt REST idmapping (rest.uniprot.org/idmapping). No API key/account.",
}
