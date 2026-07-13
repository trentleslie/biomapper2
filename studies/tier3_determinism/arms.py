"""Arm-A (LLM-only) and Arm-B (BioMapper deterministic) drivers.

Both drivers are dependency-injected: Arm A takes a ``call_fn`` (default: the real
``call_model``) and Arm B takes a ``resolve_fn`` (default: a lazily-built BioMapper
``Mapper``). This keeps the orchestration fully unit-testable with no network, and
lets the runner swap in live callables for the smoke/full run.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from studies.tier3_determinism import call_model, prompt
from studies.tier3_determinism.call_model import ModelResponse
from studies.tier3_determinism.models import ArmACall, ArmBCall, DecodingParams, ModelSpec, Query

CallFn = Callable[[ModelSpec, list[dict[str, str]], DecodingParams], ModelResponse]
ResolveFn = Callable[[Query], str | None]


def _curie_eq(a: str | None, b: str | None) -> bool:
    if a is None or b is None:
        return False
    return a.strip() == b.strip()


def run_arm_a(
    queries: list[Query],
    models: list[ModelSpec],
    decodings: list[DecodingParams],
    n_repeats: int,
    call_fn: CallFn | None = None,
) -> list[ArmACall]:
    """Run the LLM-only arm: model x decoding x query x repeat. Every call is kept.

    Models that don't accept a caller-set temperature (``supports_temperature=False``,
    e.g. Opus 4.8) can't express a temperature sweep -- every temperature bucket would
    be the byte-identical native request. For those we collapse to a single decoding so
    the model runs N times at its one native setting rather than emitting duplicate,
    mislabeled panels.
    """
    call = call_fn or call_model.call_model
    out: list[ArmACall] = []
    for spec in models:
        spec_decodings = decodings if spec.supports_temperature else decodings[:1]
        for decode in spec_decodings:
            for query in queries:
                messages = prompt.build_messages(query)
                for repeat in range(n_repeats):
                    resp = call(spec, messages, decode)
                    parsed = prompt.parse_answer(resp.text) if resp.error is None else None
                    is_correct = None if query.gold_curie is None else _curie_eq(parsed, query.gold_curie)
                    out.append(
                        ArmACall(
                            query_id=query.query_id,
                            model_label=spec.label,
                            model_id=spec.model_id,
                            provider=spec.provider,
                            temperature=decode.temperature,
                            top_p=decode.top_p,
                            max_tokens=decode.max_tokens,
                            seed=decode.seed,
                            repeat_index=repeat,
                            raw_text=resp.text,
                            parsed_curie=parsed,
                            is_correct=is_correct,
                            prompt_tokens=resp.prompt_tokens,
                            completion_tokens=resp.completion_tokens,
                            latency_s=resp.latency_s,
                            error=resp.error,
                        )
                    )
    return out


def run_arm_b(queries: list[Query], n_repeats: int, resolve_fn: ResolveFn | None = None) -> list[ArmBCall]:
    """Run BioMapper N times per query to *demonstrate* byte-identical output."""
    resolve = resolve_fn or _make_default_resolver()
    out: list[ArmBCall] = []
    for query in queries:
        for repeat in range(n_repeats):
            error: str | None = None
            chosen: str | None = None
            try:
                chosen = resolve(query)
            except Exception as exc:  # noqa: BLE001 -- capture network/pipeline failure
                error = f"{type(exc).__name__}: {exc}"
            is_correct = None if query.gold_curie is None else _curie_eq(chosen, query.gold_curie)
            out.append(
                ArmBCall(
                    query_id=query.query_id,
                    repeat_index=repeat,
                    chosen_kg_id=chosen,
                    is_correct=is_correct,
                    error=error,
                )
            )
    return out


# Maps our entity types to BioMapper's target vocab hint.
_ENTITY_VOCAB = {"metabolite": "chebi", "gene": "hgnc", "protein": "uniprot"}


def _make_default_resolver() -> ResolveFn:
    """Build a BioMapper-backed resolver.

    The ``Mapper`` is constructed lazily on first use and memoized, so a missing
    ``KESTREL_API_KEY`` or import/network failure surfaces as a per-call captured
    error (via ``run_arm_b``'s try/except) rather than crashing the whole run.
    """
    cache: dict[str, Any] = {}

    def _mapper() -> Any:
        if "mapper" not in cache:
            from biomapper2.mapper import Mapper

            cache["mapper"] = Mapper()
        return cache["mapper"]

    def resolve(query: Query) -> str | None:
        mapper = _mapper()
        item: dict[str, Any] = {"name": query.query_name}
        result = mapper.map_entity_to_kg(
            item=item,
            name_field="name",
            provided_id_fields=[],
            entity_type=query.entity_type,
            vocab=_ENTITY_VOCAB.get(query.entity_type),
        )
        chosen = result.get("chosen_kg_id") if isinstance(result, dict) else result["chosen_kg_id"]
        return chosen  # type: ignore[no-any-return]

    return resolve
