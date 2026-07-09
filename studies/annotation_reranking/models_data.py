from dataclasses import dataclass, field


@dataclass
class Candidate:
    id: str                       # CURIE, e.g. "CHEBI:28683"
    score: float                  # Kestrel hybrid score (0-5)
    name: str
    synonyms: list[str] = field(default_factory=list)
    prefixes: list[str] = field(default_factory=list)
    equivalent_ids: list[str] = field(default_factory=list)  # enriched via get-nodes

    def has_refmet(self) -> bool:
        return any(e.startswith("RM:") for e in self.equivalent_ids)


@dataclass
class EvalCase:
    name: str
    level: str
    refmet_id: str
    refmet_name: str
    biomapper_ids: list[str]
    biomapper_name: str
    category: str
    correct_id: str | None
    label_source: str
    inchikey_block_correct: str | None = None
    retrievable: bool | None = None


@dataclass
class RerankResult:
    case_name: str
    reranker: str
    model: str | None
    selected_id: str | None
    correct_id: str | None
    label_source: str
    regime: str
    is_correct: bool | None       # None when label_source == "refmet_agreement"
    cost_usd: float
    latency_s: float
    error: str | None = None      # off-list / parse / api failure marker
    review_flag: str | None = None
