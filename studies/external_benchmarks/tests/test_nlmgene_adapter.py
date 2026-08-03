"""NLM-Gene adapter + config (offline; in-memory BioC XML, no network)."""

from __future__ import annotations

from studies.external_benchmarks.config import (
    NLMGENE,
    NLMGENE_AMBIGUOUS_MIN_GENES,
    NLMGENE_REGISTRY,
)


def test_nlmgene_config_shape():
    assert NLMGENE.key == "nlm-gene"
    assert NLMGENE.arm == "gene"
    assert NLMGENE.entity_type == "gene"
    assert NLMGENE.input_type == "name"
    assert NLMGENE.name_column == "mention"
    assert NLMGENE.target_vocabs == ("NCBIGene",)
    assert NLMGENE.gold_curie_columns == (("NCBIGene", "gold_ncbigene"),)
    # Gold is the human-curated corpus, addressed at the per-mention NCBI Gene id — NOT an xref table.
    assert "ftp.ncbi.nlm.nih.gov/pub/lu/NLMGene" in NLMGENE.source_url
    assert NLMGENE_AMBIGUOUS_MIN_GENES == 2
    assert NLMGENE_REGISTRY["nlm-gene"] is NLMGENE


from studies.external_benchmarks.adapters import nlmgene
from studies.external_benchmarks.adapters.nlmgene import GeneMention, parse_bioc_documents

# Minimal BioC XML doc: one Gene mention, one multi-gene (ambiguous) Gene mention, one GeneRIF
# (must be skipped), one Gene mention with a blank id (skipped).
_BIOC_DOC = """<?xml version='1.0' encoding='UTF-8'?>
<collection><source>PubTator</source><document><id>111</id>
<passage><infon key="type">title</infon><offset>0</offset><text>TP53 and CCR7 study of the chemokine receptor.</text>
<annotation id="0"><infon key="NCBI Gene identifier">7157</infon><infon key="type">Gene</infon><location offset="0" length="4"/><text>TP53</text></annotation>
<annotation id="1"><infon key="NCBI Gene identifier">12775</infon><infon key="type">Gene</infon><location offset="9" length="4"/><text>CCR7</text></annotation>
<annotation id="2"><infon key="NCBI Gene identifier">12458,12772,12775</infon><infon key="type">Gene</infon><location offset="27" length="18"/><text>chemokine receptor</text></annotation>
<annotation id="3"><infon key="NCBI Gene identifier">7157</infon><infon key="type">GeneRIF</infon><location offset="0" length="4"/><text>TP53</text></annotation>
<annotation id="4"><infon key="NCBI Gene identifier"></infon><infon key="type">Gene</infon><location offset="0" length="0"/><text>ghost</text></annotation>
</passage></document></collection>"""


def test_parse_bioc_extracts_gene_mentions_skips_generif_and_blank():
    mentions = list(parse_bioc_documents([("111", _BIOC_DOC)]))
    # GeneRIF ("TP53") and blank-id ("ghost") are dropped; the 3 type=Gene id-bearing spans remain.
    assert [(m.mention, m.gene_ids) for m in mentions] == [
        ("TP53", ("7157",)),
        ("CCR7", ("12775",)),
        ("chemokine receptor", ("12458", "12772", "12775")),  # comma list -> multi-gene span
    ]


def test_parse_bioc_multiple_documents():
    doc2 = _BIOC_DOC.replace("<id>111</id>", "<id>222</id>")
    mentions = list(parse_bioc_documents([("111", _BIOC_DOC), ("222", doc2)]))
    assert sum(1 for m in mentions if m.mention == "TP53") == 2


from studies.external_benchmarks.adapters.nlmgene import (
    AMBIGUOUS,
    UNAMBIGUOUS,
    aggregate_surface_forms,
    build_nlmgene_input_df,
)

# "IL" appears mapped to two different genes across occurrences (corpus-level ambiguity);
# "TP53" is single-gene (unambiguous); "chemokine receptor" is a single multi-id span (ambiguous).
_MENTIONS = [
    GeneMention("TP53", ("7157",)),
    GeneMention("TP53", ("7157",)),  # repeat -> deduped, still one referent
    GeneMention("IL", ("3552",)),
    GeneMention("IL", ("3553",)),  # same surface form, different gene -> ambiguous
    GeneMention("chemokine receptor", ("12458", "12772", "12775")),
]


def test_aggregate_unions_gene_ids_per_surface_form():
    ref = aggregate_surface_forms(_MENTIONS)
    assert ref["TP53"] == {"7157"}
    assert ref["IL"] == {"3552", "3553"}
    assert ref["chemokine receptor"] == {"12458", "12772", "12775"}


def test_build_input_df_dedupes_labels_partition_and_prefixes_curies():
    df = build_nlmgene_input_df(_MENTIONS)
    assert list(df.columns) == ["mention", "gold_ncbigene", "partition"]
    rows = {r["mention"]: r for _, r in df.iterrows()}
    # unambiguous single-gene form -> accuracy partition, single NCBIGene CURIE
    assert rows["TP53"]["gold_ncbigene"] == "NCBIGene:7157"
    assert rows["TP53"]["partition"] == UNAMBIGUOUS
    # corpus-level homonym -> ambiguous partition, |-joined CURIEs
    assert rows["IL"]["partition"] == AMBIGUOUS
    assert set(rows["IL"]["gold_ncbigene"].split("|")) == {"NCBIGene:3552", "NCBIGene:3553"}
    # single multi-id span -> ambiguous
    assert rows["chemokine receptor"]["partition"] == AMBIGUOUS
    # deterministic: sorted by mention, one row per surface form
    assert list(df["mention"]) == sorted(df["mention"])
    assert df["mention"].is_unique


from studies.external_benchmarks.adapters.nlmgene import (
    NlmGeneBundle,
    load_nlmgene,
    persist_input_df,
    read_local_corpus,
)


def test_load_nlmgene_builds_bundle_and_card():
    bundle = load_nlmgene([("111", _BIOC_DOC)])
    assert isinstance(bundle, NlmGeneBundle)
    card = bundle.card
    assert card["dataset"] == "nlm-gene"
    assert card["arm"] == "gene"
    assert card["gold_curie_columns"] == {"NCBIGene": "gold_ncbigene"}
    assert card["n_documents"] == 1
    # 3 type=Gene mentions in the fixture: TP53, CCR7 (unambiguous), "chemokine receptor" (ambiguous)
    assert card["n_surface_forms"] == 3
    assert card["n_ambiguous"] == 1
    assert card["n_unambiguous"] == 2
    assert card["ambiguous_min_genes"] == 2
    assert card["subsample_sha256"]  # SHA over the exact deduped input_df CSV (reproducibility pin)
    # honesty note about context stripping / gold independence is recorded on the card
    assert "human-curated" in card["independence_note"]


def test_persist_input_df_roundtrips_sha(tmp_path):
    bundle = load_nlmgene([("111", _BIOC_DOC)])
    path = persist_input_df(bundle, tmp_path)
    assert path.exists()
    # persisted bytes re-hash to the card's recorded SHA (reconstructable regardless of upstream drift)
    from studies.external_benchmarks.adapters.backbones import sha256_bytes
    assert sha256_bytes(path.read_bytes()) == bundle.card["subsample_sha256"]


def test_read_local_corpus_reads_bioc_files(tmp_path):
    (tmp_path / "111.BioC.XML").write_text(_BIOC_DOC, encoding="utf-8")
    docs = list(read_local_corpus(tmp_path))
    assert len(docs) == 1 and docs[0][0] == "111"


def test_fetch_corpus_is_the_network_seam():
    # The only network entry is fetch_corpus; parse/aggregate/card never call it.
    assert hasattr(nlmgene, "fetch_corpus")
