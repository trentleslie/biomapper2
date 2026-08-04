from studies.northstar_e2e import kegg


def test_parse_links_maps_compound_to_pathways():
    raw = (
        b"cpd:C00031\tpath:map00010\n"
        b"cpd:C00031\tpath:map00500\n"
        b"cpd:C00183\tpath:map00280\n"
        b"cpd:C00183\tpath:ko00280\n"  # non-map (ko) links are dropped
    )
    m = kegg.parse_links(raw)
    assert m["C00031"] == ("map00010", "map00500")
    assert m["C00183"] == ("map00280",)


def test_load_membership_from_disk_has_gold_compounds():
    m = kegg.load_membership()
    from studies.northstar_e2e.gold import GOLD_METABOLITES

    # Every gold metabolite must appear in the membership file (verification gate).
    for g in GOLD_METABOLITES:
        assert g.kegg_compound in m, f"{g.kegg_compound} missing from KEGG membership"
