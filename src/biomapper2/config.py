"""
Configuration settings for biomapper2.

Customize these values to change API endpoints, model versions, and logging behavior.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # Load environmental variables (secrets)


# Set up our general cache directory (e.g., for requests cache, biolink)
PROJECT_ROOT = Path(__file__).parents[2]
CACHE_DIR = PROJECT_ROOT / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# KG API configuration — override via KESTREL_API_URL in .env
KESTREL_API_URL = os.getenv("KESTREL_API_URL", "https://kestrel.nathanpricelab.com/api")

# Biolink model version
BIOLINK_VERSION_DEFAULT = "4.2.5"

# Level of logging messages to display (DEBUG, INFO, WARNING, ERROR, or CRITICAL)
LOG_LEVEL = "INFO"

# Secrets (from environment variables)
_kestrel_api_key: str | None = None


def get_kestrel_api_key() -> str:
    global _kestrel_api_key
    if _kestrel_api_key is None:
        _kestrel_api_key = os.getenv("KESTREL_API_KEY")
        if not _kestrel_api_key:
            raise ValueError("KESTREL_API_KEY environment variable is not set")
    return _kestrel_api_key


# Batching for Kestrel API requests (to prevent timeouts on large datasets)
KESTREL_BATCHING_ENABLED = True  # Set to False to disable batching (for performance testing)
KESTREL_BATCH_SIZE_SEARCH = 1000  # For text-search, vector-search, hybrid-search
KESTREL_BATCH_SIZE_CANONICALIZE = 2000  # For canonicalize endpoint

# Structure (InChIKey) fallback services for the resolver's connectivity test. Used only on the
# small-molecule ChEBI conflict path when a node carries no KG InChIKey (see StructureResolver).
MW_INCHIKEY_URL = "https://www.metabolomicsworkbench.org/rest/refmet/name"  # /{name}/inchi_key
PUBCHEM_INCHIKEY_URL = "https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/name"  # /{name}/property/InChIKey/JSON
STRUCTURE_LOOKUP_TIMEOUT_S = 3  # per external structure call; mirrors the RefMet /match timeout

# Human-preference re-ranking for gene/protein resolution (see docs/plans HGNC plan).
# When prefer_human is active, hybrid-search retrieves this many candidates (instead of 1) so the
# human node — which often ranks below the wrong-species ortholog — is actually returned. Live spike
# (2026-06-15) found recoverable human nodes at rank ~#4; 20 gives ample margin.
HYBRID_SEARCH_LIMIT = 20
# Human-only CURIE prefixes. HGNC assigns IDs only to human genes, so its presence in a hybrid-search
# row's `prefixes` marks the human node. Any prefix added here must itself be human-exclusive.
HUMAN_MARKER_PREFIXES = {"HGNC"}

# Kill switch for the curated gene-symbol fallback bridge (see core/gene_symbol_resolver.py). When True
# (default), gene/protein resolution misses for the curated drug-conflated symbols are resolved via the
# deterministic non-search fallback. Set False to disable the bridge without a code revert.
GENE_SYMBOL_FALLBACK_ENABLED = True

# Per-category preferred (canonical) namespace prefixes for the prefer_canonical re-ranking. Within a
# Biolink category, hybrid-search ranks across all namespaces at once, so a non-canonical same-text node
# (UMLS/ICD/KEGG/PANTHER) frequently outranks the canonical one. These prefixes mark the canonical node so
# the annotator can prefer it (see core/annotators/kestrel_hybrid.py:_select_canonical). Keys are Biolink
# categories; the engine expands each via get_descendants so subcategories inherit the policy. Gene/protein
# are intentionally absent — they use HUMAN_MARKER_PREFIXES / prefer_human instead.
#
# Prefix strings are the *actual* Kestrel KG prefixes, verified live 2026-06-18 against hybrid-search rows
# (e.g. RefMet is "RM", not "REFMET"). A wrong string is a silent no-op (the filter matches nothing).
CATEGORY_PREFERRED_NAMESPACES: dict[str, set[str]] = {
    "biolink:SmallMolecule": {"CHEBI", "HMDB", "RM"},
    "biolink:Disease": {"MONDO"},
}

# Per-category Biolink acceptance root for the category *validator* (see
# core/annotators/kestrel_hybrid.py:_is_on_category). Hybrid search ranks across categories as well as
# namespaces, so a metabolite query can commit a node that is not a molecule at all — measured over the
# pinned baseline, 1,148 of 12,605 metabolite-arm commits (9.1%) carried no chemical category, led by
# 692 biolink:PhenotypicFeature (EFO "…measurement" nodes) and 362 Protein/Gene. Of that 1,148, the
# validator refuses 1,138 — the other 10 are pure-NamedThing typing gaps that fail open below.
#
# These numbers are not an assertion: regenerate them with `studies/analysis/off_category_audit.py`
# (artifact: studies/analysis/results/off_category_audit_suite_20260805T033340Z.json). That audit also
# measures what the guard *costs*: of the 1,138 refusals, 0 were the right compound under a wrong type
# (132 adjudicable, all wrong; 1,001 committed to nodes carrying no chemical identifier in any
# namespace). The peptide-metabolite worry — glutathione/carnosine/gamma-glutamyl-X being the right
# molecule typed as a Protein — does not materialize here: every such name in the suite committed to a
# biolink:SmallMolecule node and is never seen by this guard.
#
# Semantics, and note the two sides are expanded *separately*:
#   - The KEY is expanded via get_descendants so subcategories of a configured job category inherit the
#     same policy (mirrors CATEGORY_PREFERRED_NAMESPACES).
#   - The VALUE is the acceptance ROOT and is expanded via get_descendants on its own. It is deliberately
#     one level up from the key: descendants('biolink:ChemicalEntity') is 12 categories, so a legitimately
#     broader typing (ChemicalEntity, MolecularMixture, Drug) survives while Protein/Polypeptide/
#     PhenotypicFeature/Pathway/MolecularActivity do not.
#
# Gene/protein are intentionally absent: 93.8% of HGNC commits are off-category relative to any chemical
# root and the HGNC baseline is 0/4476 suspect, so the gene path must stay unfiltered. Any category with
# no entry here is likewise unfiltered — including the biolink:NamedThing that standardize_entity_type
# falls back to for an unrecognized entity type.
CATEGORY_ACCEPTED_ROOTS: dict[str, str] = {
    "biolink:SmallMolecule": "biolink:ChemicalEntity",
}
