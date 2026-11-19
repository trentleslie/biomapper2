"""Tests for the pure 16S taxon label parser (core/taxon_label.py)."""

import pytest

from biomapper2.core.taxon_label import LABEL_CLASSES, parse_taxon_label

# --------------------------------------------------------------------------------------------- formats


@pytest.mark.parametrize(
    "label, name, rank",
    [
        (
            "k__Bacteria;p__Firmicutes;c__Clostridia;o__Clostridiales;f__Lachnospiraceae;g__Dorea",
            "Dorea",
            "genus",
        ),
        (
            "D_0__Bacteria;D_1__Actinobacteria;D_2__Actinobacteria;D_3__Bifidobacteriales;"
            "D_4__Bifidobacteriaceae;D_5__Bifidobacterium",
            "Bifidobacterium",
            "genus",
        ),
        (
            "sk__Bacteria;k__;p__Bacteroidetes;c__Bacteroidia;o__Bacteroidales;f__Rikenellaceae;g__Alistipes",
            "Alistipes",
            "genus",
        ),
        (
            "Root;p__Bacteroidetes;c__Bacteroidia;o__Bacteroidales;f__Rikenellaceae;g__Alistipes",
            "Alistipes",
            "genus",
        ),
    ],
)
def test_baseline_formats_give_query_name_and_rank(label, name, rank):
    parse = parse_taxon_label(label)
    assert parse.is_16s_format
    assert parse.query_name == name
    assert parse.query_rank == rank
    assert parse.label_class == "latin"


def test_silva_rank_is_a_hint_and_gg_rank_is_not():
    silva = parse_taxon_label("D_0__Bacteria;D_5__Bifidobacterium")
    gg = parse_taxon_label("k__Bacteria;g__Bifidobacterium")
    assert silva.rank_is_hint is True
    assert gg.rank_is_hint is False


# ------------------------------------------------------------------------------------------ edge cases


def test_empty_trailing_genus_gives_family_query():
    parse = parse_taxon_label("k__Bacteria;p__Firmicutes;c__Clostridia;o__Clostridiales;f__Ruminococcaceae;g__")
    assert (parse.query_name, parse.query_rank) == ("Ruminococcaceae", "family")


def test_silva_placeholder_genus_falls_back_to_phylum():
    parse = parse_taxon_label("D_0__Bacteria;D_1__Firmicutes;D_5__uncultured")
    assert (parse.query_name, parse.query_rank) == ("Firmicutes", "phylum")


def test_silva_padded_repeat_is_dropped():
    parse = parse_taxon_label(
        "D_0__Bacteria;D_1__Firmicutes;D_2__Clostridia;D_3__Clostridiales;D_4__Peptococcaceae;D_5__Peptococcaceae"
    )
    assert (parse.query_name, parse.query_rank) == ("Peptococcaceae", "family")
    assert [lv.rank for lv in parse.levels][-1] == "family"


def test_mgnify_k_is_kingdom_when_sk_present():
    parse = parse_taxon_label("sk__Bacteria;k__Bacillati;p__Bacillota")
    ranks = {lv.name: lv.rank for lv in parse.levels}
    assert ranks == {"Bacteria": "domain", "Bacillati": "kingdom", "Bacillota": "phylum"}


def test_k_is_domain_without_sk():
    parse = parse_taxon_label("k__Bacteria;p__Firmicutes")
    assert parse.levels[0].rank == "domain"


def test_d_prefix_is_domain():
    parse = parse_taxon_label("d__Bacteria;p__Firmicutes_A;c__Clostridia")
    assert parse.levels[0].rank == "domain"
    assert parse.query_rank == "class"


@pytest.mark.parametrize(
    "label, name",
    [
        (
            "k__Bacteria;p__Firmicutes;c__Clostridia;o__Clostridiales;f__Lachnospiraceae;g__Blautia;"
            "s__[Ruminococcus]_gnavus",
            "Blautia",
        ),
        (
            "D_0__Bacteria;D_1__Firmicutes;D_2__Bacilli;D_3__Lactobacillales;D_4__Lactobacillaceae;"
            "D_5__Lactobacillus;D_6__Lactobacillus reuteri",
            "Lactobacillus",
        ),
        ("d__denovo15445;k__Bacteria;g__Dorea", None),
        ("k__Bacteria;g__Dorea;t__strainX", "Dorea"),
    ],
)
def test_species_like_levels_are_truncated(label, name):
    parse = parse_taxon_label(label)
    assert parse.query_name == name


def test_candidatus_underscore_is_normalized():
    parse = parse_taxon_label("k__Bacteria;p__Candidatus_Saccharibacteria")
    assert parse.query_name == "Candidatus Saccharibacteria"
    assert parse.label_class == "latin"


def test_glued_candidatus_is_split():
    assert parse_taxon_label("k__Bacteria;g__CandidatusSolibacter").query_name == "Candidatus Solibacter"


def test_binomial_in_silva_genus_slot_is_truncated_to_genus():
    parse = parse_taxon_label("D_0__Bacteria;D_4__Enterobacteriaceae;D_5__Enterobacter cancerogenus")
    assert (parse.query_name, parse.query_rank, parse.label_class) == ("Enterobacter", "genus", "latin")


@pytest.mark.parametrize(
    "label",
    [
        "Bacteria;Proteobacteria;Gammaproteobacteria;Enterobacterales;Enterobacteriaceae;Escherichia;"
        "Escherichia coli",
        "Bacteria;Proteobacteria;Gammaproteobacteria;Enterobacterales;Enterobacteriaceae;Escherichia coli",
        "Root;Bacteria;Proteobacteria;Enterobacteriaceae;Escherichia;Escherichia coli;strain K-12",
    ],
)
def test_plain_lineage_species_slot_is_truncated_to_genus(label):
    parse = parse_taxon_label(label)
    assert parse.is_16s_format
    assert (parse.query_name, parse.query_rank, parse.rank_is_hint) == ("Escherichia", "genus", True)
    assert parse.label_class == "latin"
    assert [lv.name for lv in parse.levels].count("Escherichia") == 1


def test_plain_lineage_without_species_keeps_unranked_deepest():
    parse = parse_taxon_label("Bacteria;Firmicutes;Clostridia;Clostridiales;Lachnospiraceae;Dorea")
    assert (parse.query_name, parse.query_rank) == ("Dorea", None)


def test_explicit_rank_repeating_its_parent_is_kept():
    parse = parse_taxon_label("k__Bacteria;p__Actinobacteria;c__Actinobacteria;o__;f__;g__")
    assert (parse.query_name, parse.query_rank) == ("Actinobacteria", "class")
    assert [lv.rank for lv in parse.levels] == ["domain", "phylum", "class"]


def test_trailing_unprefixed_placeholder_is_ignored():
    parse = parse_taxon_label(
        "D_0__Bacteria;D_1__Firmicutes;D_2__Clostridia;D_3__Clostridiales;D_4__Lachnospiraceae;"
        "D_5__Roseburia;Ambiguous_taxa"
    )
    assert (parse.query_name, parse.query_rank) == ("Roseburia", "genus")


# --------------------------------------------------------------------------------------------- classes


@pytest.mark.parametrize(
    "label, cls",
    [
        ("k__Bacteria;f__Lachnospiraceae;g__Ruminococcus2", "informal"),
        ("k__Bacteria;f__Lachnospiraceae;g__Lachnospiracea_incertae_sedis", "incertae_sedis"),
        ("k__Bacteria;f__Enterobacteriaceae;g__Escherichia/Shigella", "merged"),
        ("D_0__Bacteria;D_4__Enterobacteriaceae;D_5__Escherichia-Shigella", "merged"),
        ("D_0__Bacteria;D_4__Prevotellaceae;D_5__Prevotella_9", "superset"),
        ("d__Bacteria;f__Ruminococcaceae;g__Faecalibacterium_A_123", "superset"),
        ("D_0__Bacteria;D_4__Ruminococcaceae;D_5__Ruminococcus 1", "superset"),
        ("k__Bacteria;f__Lachnospiraceae;g__Clostridium_XlVb", "superset"),
        ("D_0__Bacteria;D_4__Clostridiaceae;D_5__Clostridium_sensu_stricto_1", "superset"),
        ("k__Bacteria;f__Lachnospiraceae;g__[Ruminococcus]", "bracketed"),
        ("D_0__Bacteria;D_4__Ruminococcaceae;D_5__[Eubacterium] coprostanoligenes group", "bracketed"),
        ("Root;p__TM7;c__TM7-3;o__EW055;f__AKIW659", "informal"),
        ("sk__Eukaryota;k__Metazoa;p__Chordata", "eukaryote"),
        ("k__Bacteria;p__Cyanobacteria;c__Chloroplast;o__Streptophyta;f__;g__", "organelle"),
        ("k__Bacteria;p__Proteobacteria;c__Alphaproteobacteria;o__Rickettsiales;f__mitochondria;g__", "organelle"),
        ("Unclassified", "empty"),
        ("k__;p__;c__", "empty"),
        ("k__Bacteria;p__Cyanobacteria/Chloroplast;c__Cyanobacteria;o__;f__;g__", "latin"),
    ],
)
def test_label_classes(label, cls):
    assert cls in LABEL_CLASSES
    assert parse_taxon_label(label).label_class == cls


def test_superset_query_is_the_base_genus():
    assert parse_taxon_label("D_0__Bacteria;D_5__Prevotella_9").query_name == "Prevotella"
    assert parse_taxon_label("d__Bacteria;g__Faecalibacterium_A_123").query_name == "Faecalibacterium"
    assert parse_taxon_label("D_0__Bacteria;D_5__Ruminococcus 1").query_name == "Ruminococcus"
    assert parse_taxon_label("k__Bacteria;g__Clostridium_XlVb").query_name == "Clostridium"


def test_informal_latin_token_is_reported():
    assert parse_taxon_label("k__Bacteria;g__Ruminococcus2").has_latin_token is True
    assert parse_taxon_label("Root;p__TM7;c__TM7-3;o__EW055;f__AKIW659").has_latin_token is False


def test_placeholder_is_never_the_query():
    parse = parse_taxon_label("k__Bacteria;p__Firmicutes;c__Clostridia;o__unidentified;f__uncultured bacterium")
    assert (parse.query_name, parse.query_rank) == ("Clostridia", "class")


# ------------------------------------------------------------------------------------------ bare names


@pytest.mark.parametrize("label", ["Bacteroides", "Homo sapiens", "E. coli", "mouse"])
def test_bare_names_are_not_16s_format(label):
    parse = parse_taxon_label(label)
    assert parse.is_16s_format is False
    assert parse.query_rank is None
    assert parse.query_name == label


def test_bare_name_whitespace_is_trimmed():
    assert parse_taxon_label("  Bacteroides ").query_name == "Bacteroides"


@pytest.mark.parametrize("label", ["", "   ", None])
def test_empty_input_is_empty_class(label):
    parse = parse_taxon_label(label)
    assert parse.label_class == "empty"
    assert parse.query_name is None


def test_parse_is_deterministic_and_hashable():
    label = "k__Bacteria;p__Firmicutes;g__Dorea"
    assert parse_taxon_label(label) == parse_taxon_label(label)
    hash(parse_taxon_label(label))
