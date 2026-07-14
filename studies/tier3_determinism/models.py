"""Type-safe data models for the Tier-3 determinism-vs-LLM experiment (WS-E).

Two arms:
  Arm A -- a well-engineered LLM-only baseline (no tools, no BioMapper).
  Arm B -- the BioMapper deterministic 5-step pipeline.

Every model is a frozen/validated Pydantic model so raw runs round-trip to JSON
losslessly and the manifest pins everything needed to reproduce a run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

EntityType = Literal["metabolite", "gene", "protein"]
Provider = Literal["openai", "anthropic", "openrouter"]


class Query(BaseModel):
    """One held-out entity-resolution query with a known gold answer.

    ``gold_curie`` may be ``None`` for expert-unadjudicated cases carried in a
    swapped-in gold set; such queries contribute to answer-stability metrics but
    are excluded from accuracy.
    """

    query_id: str
    query_name: str
    entity_type: EntityType
    target_namespace: str  # e.g. "CHEBI", "HGNC", "UniProtKB"
    gold_curie: str | None = None
    source: str = "held_out_v1"

    model_config = {"frozen": True}


class ModelSpec(BaseModel):
    """Identifies one model behind one provider. ``model_id`` is pinned verbatim.

    ``supports_temperature`` records whether the provider accepts a caller-set
    ``temperature`` on this model. Frontier Anthropic models (Opus 4.8/4.7) have
    **removed** the sampling controls entirely -- ``temperature`` and ``top_p`` both
    return HTTP 400 -- so a temperature sweep is not expressible for them; the call
    layer omits the parameter and the run collapses to the model's native setting.
    """

    provider: Provider
    model_id: str
    label: str  # short display label, e.g. "gpt-5.5" / "opus-4.8" / "qwen3-8b"
    supports_temperature: bool = True

    model_config = {"frozen": True}


class DecodingParams(BaseModel):
    """Decoding parameters for one Arm-A call. Pinned into the manifest verbatim."""

    temperature: float
    top_p: float = 1.0
    max_tokens: int = 256
    seed: int | None = None

    model_config = {"frozen": True}


class ArmACall(BaseModel):
    """One raw LLM call (Arm A). Every repeat produces exactly one of these and is
    persisted -- nothing is discarded."""

    query_id: str
    model_label: str
    model_id: str
    provider: Provider
    # None (native sentinel) for models that reject a caller-set temperature
    # (``supports_temperature=False``, e.g. Opus 4.8): the call omits the parameter,
    # so labelling these 0.0 would misreport the headline condition. None == "ran at
    # the model's native, no-sampling-control setting", which is NOT temperature 0.
    temperature: float | None
    top_p: float
    max_tokens: int
    seed: int | None
    repeat_index: int
    raw_text: str  # verbatim model output
    parsed_curie: str | None  # normalized top-1 answer, or None for "unknown"/unparseable
    is_correct: bool | None  # None when the query has no gold_curie
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    latency_s: float | None = None
    error: str | None = None  # transport/parse failure marker; call still persisted


class ArmBCall(BaseModel):
    """One BioMapper pipeline run (Arm B) for one query. Repeated N times to
    *demonstrate* byte-identical output rather than assert it."""

    query_id: str
    repeat_index: int
    chosen_kg_id: str | None
    is_correct: bool | None
    latency_s: float | None = None
    error: str | None = None


class ExperimentConfig(BaseModel):
    """A single Tier-3 run's configuration. Drives both arms and the manifest."""

    dataset_path: Path
    models: list[ModelSpec]
    temperatures: list[float]
    n_repeats: int  # Arm A (LLM) repeats -- needs to be large to capture the answer-distribution spread
    n_repeats_arm_b: int | None = None  # Arm B repeats; None -> reuse n_repeats. Arm B is
    # deterministic given pinned refs, so a handful of repeats is enough to *demonstrate* variance=0
    # while keeping the ~2-3 min/call Kestrel pipeline from dominating wall-clock (asymmetric-N design).
    top_p: float = 1.0
    max_tokens: int = 256
    seed: int | None = None
    seed_policy: str = "fixed seed passed to providers that support it; API LLMs may ignore it"
    run_arm_b: bool = True
    limit: int | None = None  # cap the query set (cheap smoke runs); None = full set
    arm_a_workers: int = 8  # concurrent Arm-A LLM calls (independent); 1 = sequential

    @property
    def arm_b_repeats(self) -> int:
        """Effective Arm-B repeat count (falls back to the Arm-A n_repeats when unset)."""
        return self.n_repeats_arm_b if self.n_repeats_arm_b is not None else self.n_repeats


class RunManifest(BaseModel):
    """Everything needed to reproduce a run (artifact-hygiene SOP). Written once per
    run alongside the raw calls."""

    generated_utc: str
    git_commit: str | None
    dataset_source: str
    dataset_sha256: str
    n_queries: int
    n_repeats: int  # Arm A repeats
    n_repeats_arm_b: int | None = None  # Arm B repeats (asymmetric-N); None when Arm B not run
    temperatures: list[float]
    top_p: float
    max_tokens: int
    seed_policy: str
    models: list[ModelSpec]
    prompt_sha256: str
    prompt_verbatim: str
    kestrel_api_url: str | None = None
    biolink_version: str | None = None
    reference_db_versions: dict[str, str] = Field(default_factory=dict)
    endpoint_note: str = ""
    hardware_note: str = ""
