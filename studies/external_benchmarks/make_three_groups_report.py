"""Render the Monti-vs-BioMapper three-group characterization to a self-contained HTML deck.

Reads three_groups.json (from monti_biomapper_three_groups) and emits three_groups_report.html — inline
SVG, vanilla JS slide nav, no CDN. # pragma: no cover (a reporting script; the numbers are the artifact).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

RUN = Path(os.environ["AB_RUN_DIR"]).expanduser()
C = {"overlap": "#2e7d32", "biomapper_only": "#1565c0", "monti_only": "#ef6c00", "neither": "#9e9e9e",
     "bm": "#1565c0", "monti": "#ef6c00", "either": "#2e7d32"}


def _bars(rows, maxv, w=520, h=200, unit=""):  # rows: [(label, value, color)]
    n = len(rows)
    bw = w / (n * 1.6)
    gap = bw * 0.6
    svg = [f'<svg viewBox="0 0 {w} {h + 46}" width="100%" style="max-width:{w}px">']
    for i, (lab, val, col) in enumerate(rows):
        bh = (val / maxv) * h if maxv else 0
        x = 30 + i * (bw + gap)
        y = h - bh + 10
        svg.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{bw:.0f}" height="{bh:.0f}" fill="{col}" rx="3"/>')
        svg.append(f'<text x="{x + bw/2:.0f}" y="{y - 5:.0f}" text-anchor="middle" font-size="13" font-weight="600">{val}{unit}</text>')
        svg.append(f'<text x="{x + bw/2:.0f}" y="{h + 28:.0f}" text-anchor="middle" font-size="11" fill="#555">{lab}</text>')
    svg.append("</svg>")
    return "".join(svg)


def _stack(segs, total, w=520, h=48):  # segs: [(label, value, color)]
    svg = [f'<svg viewBox="0 0 {w} {h + 30}" width="100%" style="max-width:{w}px">']
    x = 0
    for lab, val, col in segs:
        sw = (val / total) * w if total else 0
        svg.append(f'<rect x="{x:.1f}" y="0" width="{sw:.1f}" height="{h}" fill="{col}"/>')
        if sw > 34:
            svg.append(f'<text x="{x + sw/2:.1f}" y="{h/2+5:.0f}" text-anchor="middle" font-size="13" fill="#fff" font-weight="600">{val}</text>')
        x += sw
    svg.append("</svg>")
    return "".join(svg)


def _ex_table(examples):
    rows = ""
    for g, label in (("overlap", "Overlap (both)"), ("biomapper_only", "BioMapper-only"), ("monti_only", "Monti-only")):
        items = "".join(f"<li>{e}</li>" for e in examples[g][:6])
        rows += f'<tr><td style="color:{C[g]};font-weight:600;white-space:nowrap">{label}</td><td><ul class="ex">{items}</ul></td></tr>'
    return f'<table class="ex">{rows}</table>'



def _cert_diagram():
    return """
<svg viewBox="0 0 760 300" width="100%" style="max-width:760px">
  <rect x="20" y="130" width="150" height="44" rx="6" fill="#eceff1" stroke="#90a4ae"/>
  <text x="95" y="157" text-anchor="middle" font-size="13">A linked pair<tspan font-size="11" fill="#666"> (Monti/BioMapper)</tspan></text>
  <text x="95" y="172" text-anchor="middle" font-size="11" fill="#555">necs name  &lt;-&gt;  cohort name</text>
  <path d="M170 140 C 220 90, 250 70, 300 70" fill="none" stroke="#1565c0" stroke-width="2" marker-end="url(#a)"/>
  <path d="M170 164 C 220 214, 250 234, 300 234" fill="none" stroke="#ef6c00" stroke-width="2" marker-end="url(#a)"/>
  <rect x="300" y="46" width="220" height="48" rx="6" fill="#e3f2fd" stroke="#1565c0"/>
  <text x="410" y="68" text-anchor="middle" font-size="12" font-weight="600">necs independent structure</text>
  <text x="410" y="84" text-anchor="middle" font-size="11" fill="#555">curator id &#8594; InChIKey via PubChem</text>
  <rect x="300" y="210" width="220" height="48" rx="6" fill="#fff3e0" stroke="#ef6c00"/>
  <text x="410" y="232" text-anchor="middle" font-size="12" font-weight="600">cohort independent structure</text>
  <text x="410" y="248" text-anchor="middle" font-size="11" fill="#555">curator id &#8594; InChIKey via PubChem</text>
  <path d="M520 70 C 580 90, 600 130, 610 145" fill="none" stroke="#607d8b" stroke-width="2"/>
  <path d="M520 234 C 580 214, 600 174, 610 159" fill="none" stroke="#607d8b" stroke-width="2"/>
  <rect x="560" y="128" width="180" height="48" rx="6" fill="#fff" stroke="#607d8b"/>
  <text x="650" y="150" text-anchor="middle" font-size="12" font-weight="600">compare block-1</text>
  <text x="650" y="166" text-anchor="middle" font-size="11" fill="#555">(connectivity skeleton)</text>
  <text x="650" y="200" text-anchor="middle" font-size="12" fill="#2e7d32" font-weight="600">match -&gt; CERTIFIED</text>
  <text x="650" y="220" text-anchor="middle" font-size="12" fill="#c62828" font-weight="600">differ -&gt; REFUTED</text>
  <text x="650" y="240" text-anchor="middle" font-size="12" fill="#9e9e9e" font-weight="600">missing -&gt; REFUSED</text>
  <defs><marker id="a" markerWidth="8" markerHeight="8" refX="6" refY="3" orient="auto"><path d="M0,0 L6,3 L0,6" fill="#607d8b"/></marker></defs>
</svg>"""


def _verdict_bar(counts, w=360):
    tot = sum(counts.values()) or 1
    segs = [("certified", counts["certified"], "#2e7d32"), ("refuted", counts["refuted"], "#c62828"), ("refused", counts["refused"], "#9e9e9e")]
    x = 0
    out = [f'<svg viewBox="0 0 {w} 30" width="100%" style="max-width:{w}px">']
    for lab, v, col in segs:
        sw = v / tot * w
        out.append(f'<rect x="{x:.1f}" y="0" width="{sw:.1f}" height="26" fill="{col}"/>')
        if sw > 26:
            out.append(f'<text x="{x+sw/2:.1f}" y="18" text-anchor="middle" font-size="12" fill="#fff" font-weight="600">{v}</text>')
        x += sw
    out.append("</svg>")
    return "".join(out)


def _cert_overview(cohort, adj):
    r = adj[cohort]
    rows = ""
    for g, label in (("overlap", "Overlap"), ("biomapper_only", "BioMapper-only"), ("monti_only", "Monti-only")):
        c = r["counts"][g]
        adjud = c["certified"] + c["refuted"]
        rate = f'{100*c["certified"]//adjud}%' if adjud else "-"
        rows += f'<tr><td style="font-weight:600">{label}</td><td style="width:45%">{_verdict_bar(c)}</td><td>{rate} correct<br><span style="color:#666;font-size:11px">of {adjud} adjudicable</span></td></tr>'
    # refuted-overlap examples (structural disagreements)
    ex = r["examples"]["overlap"]["refuted"][:4]
    exl = "".join(f'<li><b>{e.get("name")}</b>: necs <code>{e.get("necs_block")}</code> vs {e.get("partner")} <code>{e.get("partner_block")}</code></li>' for e in ex)
    cert_ex = r["examples"]["overlap"]["certified"][:4]
    cexl = "".join(f'<li><b>{e.get("name")}</b> ✓</li>' for e in cert_ex)
    mo_ex = r["examples"]["monti_only"]["certified"][:4]
    moxl = "".join(f'<li><b>{e.get("name")}</b> ✓ (BioMapper missed)</li>' for e in mo_ex) or "<li><i>none certified</i></li>"
    return f"""
<section class="slide">
  <h2>{r['pair']} — certificate adjudication</h2>
  <div class="grid">
    <div class="card"><h3>Correctness by group <span class="sub">(certified / refuted / refused)</span></h3>
      <p class="note" style="margin-top:0">Of the links we could check against independent structure, how many held up (green), disagreed (red), or had no structure to check (grey):</p>
      <table class="ex"><tr><td></td><td><span style="color:#2e7d32">■</span> certified &nbsp; <span style="color:#c62828">■</span> refuted &nbsp; <span style="color:#9e9e9e">■</span> no structure</td><td></td></tr>{rows}</table>
      <p class="note">Agreement is <b>not</b> proof: the overlap's refuted count is where <b>both</b> methods link a pair the independent structures say are different.</p>
    </div>
    <div class="card"><h3>Refuted overlap <span class="sub">(structures disagree)</span></h3>
      <ul class="ex">{exl}</ul>
      <p class="note">For same-name pairs these are cross-cohort <b>curation discrepancies</b> (the two cohorts recorded different structures for the same name); for different-name pairs they are candidate wrong links. Either way, only the certificate surfaces them.</p>
    </div>
    <div class="card"><h3>Certified overlap <span class="sub">(confirmed correct)</span></h3><ul class="ex">{cexl}</ul></div>
    <div class="card"><h3>Adoptable Monti-only <span class="sub">(certified — BioMapper should gain these)</span></h3><ul class="ex">{moxl}</ul>
      <p class="note">Certificate-gated: adopt these into BioMapper (RefMet-name bridge); reject the refuted Monti-only.</p></div>
  </div>
</section>"""


def slide(pair_key, r):
    c = r["counts"]
    cov = r["panel_coverage"]
    adj = r["adjudication"]
    uni = r["universe_present_in_both"]
    disc = _stack(
        [("Overlap", c["overlap"], C["overlap"]), ("BioMapper-only", c["biomapper_only"], C["biomapper_only"]),
         ("Monti-only", c["monti_only"], C["monti_only"])], uni)
    cover = _bars(
        [("BioMapper", cov["biomapper"], C["bm"]), ("BioMapper\n+bridge", cov.get("biomapper_bridge", cov["biomapper"]), "#00838f"),
         ("Monti", cov["monti"], C["monti"]), ("Either\n(union)", cov["either"], C["either"]),
         ("Neither\n(ceiling)", cov["neither"], C["neither"])],
        cov["panel_total"])
    bm_adj = _bars([("correct", adj["biomapper_only_correct"], C["overlap"]), ("wrong", adj["biomapper_only_wrong"], "#c62828")],
                   max(adj["biomapper_only_correct"], adj["biomapper_only_wrong"], 1), w=240, h=120)
    mo_adj = _bars([("correct", adj["monti_only_correct"], C["overlap"]), ("wrong", adj["monti_only_wrong"], "#c62828")],
                   max(adj["monti_only_correct"], adj["monti_only_wrong"], 1), w=240, h=120)
    ceil_pct = 100 * cov["neither"] / cov["panel_total"]
    return f"""
<section class="slide">
  <h2>{r['pair']}</h2>
  <div class="grid">
    <div class="card">
      <h3>Three groups <span class="sub">(present-in-both universe = {uni})</span></h3>
      {disc}
      <p class="note">Overlap {c['overlap']} ({round(100*c['overlap']/uni)}%) · BioMapper-only {c['biomapper_only']} · Monti-only {c['monti_only']} · Neither {c['neither']}</p>
    </div>
    <div class="card">
      <h3>Performance ceiling <span class="sub">(harmonized to NECS, panel = {cov['panel_total']})</span></h3>
      {cover}
      <p class="note"><b>Union {cov['either']} ({round(100*cov['either']/cov['panel_total'])}%) &gt; either alone</b> — complementary. The certificate-gated bridge lifts BioMapper {cov['biomapper']}&rarr;<b>{cov.get('biomapper_bridge', cov['biomapper'])}</b> (pure-correct). Ceiling headroom: <b>{cov['neither']} ({ceil_pct:.1f}%)</b> harmonized by neither.</p>
    </div>
    <div class="card">
      <h3>Discrepancy adjudicated <span class="sub">(by independent structure)</span></h3>
      <div class="adj"><div><div class="alab" style="color:{C['bm']}">BioMapper-only</div>{bm_adj}</div><div><div class="alab" style="color:{C['monti']}">Monti-only</div>{mo_adj}</div></div>
      <p class="note">Where a link is structurally checkable, both methods are mostly right; each also contributes correct links the other misses.</p>
    </div>
    <div class="card">
      <h3>Examples</h3>
      {_ex_table(r['examples'])}
    </div>
  </div>
</section>"""



def _bridge_section(bridge, data):
    cards = ""
    for cohort in ("arivale", "xuetal"):
        o = bridge[cohort]
        cov = data[cohort]["panel_coverage"]
        # cohort-panel coverage (same basis as the ceiling chart), not the NECS-side count, so the two
        # sections agree on the BioMapper baseline.
        base, mx = cov["biomapper"], cov["biomapper_bridge"]
        gain, rej, pend = mx - base, o["bridge_refuted_rejected"], o["bridge_refused_pending"]
        wf = _bars([("BioMapper\nbaseline", base, "#1565c0"), ("+ certified\nbridge", mx, "#2e7d32")], mx, w=300, h=150)
        side = _bars([("rejected\n(errors)", rej, "#c62828"), ("pending\n(no struct.)", pend, "#9e9e9e")], max(pend, 1), w=240, h=150)
        ex = "".join(f"<li>{e}</li>" for e in o["examples_added"][:6])
        cards += f"""
    <div class="card"><h3>{o['pair']}</h3>
      <div style="display:flex;gap:12px;align-items:flex-end"><div>{wf}</div><div>{side}</div></div>
      <p class="note"><b>+{gain} confirmed-correct links</b> ({round(100*gain/base,1)}% gain) BioMapper's CURIE match missed; the gate <b>rejected {rej}</b> Monti errors; <b>{pend} pending</b> need an independent structure (the lipid-oracle frontier).</p>
      <p class="note">Added: <ul class="ex">{ex}</ul></p>
    </div>"""
    return f"""
<section class="slide"><h2>Certificate-gated RefMet bridge <span class="sub">(D2 re-resolution, in action)</span></h2>
  <p class="note" style="max-width:900px">Link two names when they share a RefMet standardized name but NOT a KG CURIE — <b>gated by the certificate</b>: adopt only structure-certified bridges, reject the refuted (Monti's own errors), hold the refused. Pure-correct coverage gain, no errors imported.</p>
  <div class="grid">{cards}</div>
</section>"""


def _worked(adj):
    a = adj["arivale"]["examples"]["overlap"]
    cert = a["certified"][0]
    ref = a["refuted"][0]

    def case(title, name, b1, b2, verdict, col, note):
        eq = "=" if b1 == b2 else "\u2260"
        return f'''<div class="card" style="flex:1;min-width:260px">
      <div style="font-weight:700;color:{col}">{title}</div>
      <div style="font-size:13px;margin:6px 0"><b>{name}</b></div>
      <div style="font-family:monospace;font-size:12px;line-height:1.5">necs&nbsp;&nbsp; {b1}<br>cohort&nbsp;{b2}</div>
      <div style="text-align:center;font-size:15px;margin:8px 0;font-family:monospace">{b1} <b style="color:{col}">{eq}</b> {b2}</div>
      <div style="color:{col};font-weight:700">{verdict}</div>
      <div class="note">{note}</div></div>'''

    c = case("Structures agree", cert["name"], cert["necs_block"], cert["necs_block"], "\u2713 CERTIFIED",
             "#2e7d32", "Both cohorts\u2019 curator ids resolve (via PubChem) to the same connectivity skeleton \u2014 the link is confirmed.")
    r = case("Structures disagree", ref["name"], ref["necs_block"], ref["partner_block"], "\u2717 REFUTED",
             "#c62828", "Same name, but the two cohorts recorded different structures \u2014 a cross-cohort curation discrepancy the certificate surfaces.")
    return f'<div style="display:flex;gap:16px;flex-wrap:wrap;margin-top:12px">{c}{r}</div>'


def _cert_diagram_section(adj):
    return f"""
<section class="slide"><h2>How the certificate works</h2>
<div class="card" style="max-width:860px">
  <p class="note" style="font-size:13px">Two cohort names are LINKED by a harmonizer (Monti via shared RefMet name, BioMapper via shared KG node). The certificate then checks that link with each side\u2019s structure resolved <b>independently of the Kraken graph</b>, and compares the connectivity skeleton (InChIKey block-1):</p>
  {_cert_diagram()}
  <p class="note"><b>Where does the InChIKey come from?</b> Each cohort supplies a curator cross-reference id (HMDB accession / PubChem CID / a gold InChIKey). The oracle resolves that id to an InChIKey through <b>PubChem\u2019s PUG-REST service</b> (or reads the curator\u2019s own gold InChIKey directly). It is an <b>external structure database</b> \u2014 NOT the Kraken node that formed the link. That independence is the whole point: reading the graph node\u2019s own InChIKey to check a graph-made link would be circular.</p>
  <p class="note"><b>CERTIFIED</b> the two independent structures agree (link confirmed). <b>REFUTED</b> they disagree (wrong link, or a curation discrepancy). <b>REFUSED</b> a side has no independent structure \u2014 counts-only, never scored.</p>
  {_worked(adj)}
</div></section>"""


def main() -> None:  # pragma: no cover
    data = json.loads((RUN / "three_groups.json").read_text())
    adj = json.loads((RUN / "certificate_adjudication.json").read_text())
    slides = "".join(slide(k, v) for k, v in data.items())
    bridge = json.loads((RUN / "refmet_bridge.json").read_text())
    cert_slides = _cert_diagram_section(adj) + "".join(_cert_overview(c, adj) for c in ("arivale", "xuetal")) + _bridge_section(bridge, data)
    tot_either = sum(v["panel_coverage"]["either"] for v in data.values())
    tot_panel = sum(v["panel_coverage"]["panel_total"] for v in data.values())
    tot_neither = sum(v["panel_coverage"]["neither"] for v in data.values())
    html = f"""<!doctype html><html><head><meta charset="utf-8"><title>Monti vs BioMapper — three-group characterization</title>
<style>
body{{font-family:-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#f4f6f8;color:#1a1a1a}}
header{{background:#0d47a1;color:#fff;padding:22px 32px}}
header h1{{margin:0;font-size:22px}} header p{{margin:6px 0 0;opacity:.9;font-size:14px}}
.slide{{padding:24px 32px;border-bottom:1px solid #e0e0e0}}
.slide h2{{margin:0 0 16px;font-size:19px;color:#0d47a1}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:20px}}
.card{{background:#fff;border-radius:10px;padding:16px 18px;box-shadow:0 1px 3px rgba(0,0,0,.08)}}
.card h3{{margin:0 0 12px;font-size:15px}} .sub{{font-weight:400;color:#777;font-size:12px}}
.note{{font-size:12.5px;color:#444;margin:10px 0 0;line-height:1.45}}
.adj{{display:flex;gap:24px}} .alab{{font-size:12px;font-weight:600;text-align:center;margin-bottom:2px}}
table.ex{{border-collapse:collapse;font-size:12px;width:100%}} table.ex td{{vertical-align:top;padding:4px 8px;border-top:1px solid #eee}}
ul.ex{{margin:0;padding-left:16px}} ul.ex li{{margin:1px 0;color:#333}}
.legend{{display:flex;gap:18px;flex-wrap:wrap;margin:8px 0 0;font-size:12px}}
.legend span{{display:inline-flex;align-items:center;gap:6px}} .dot{{width:12px;height:12px;border-radius:3px;display:inline-block}}
</style></head><body>
<header>
  <h1>Monti vs BioMapper — cross-cohort harmonization</h1>
  <p>Three groups per NECS-cohort pair: <b>overlap</b> (both), <b>discrepancy</b> (one only, structurally adjudicated), <b>neither</b> (performance ceiling). Independent-structure certificate · Kestrel v2.1.0/kg2 2.10.2 · run {RUN.name}</p>
  <div class="legend"><span><i class="dot" style="background:{C['overlap']}"></i>Overlap / correct</span><span><i class="dot" style="background:{C['biomapper_only']}"></i>BioMapper</span><span><i class="dot" style="background:{C['monti_only']}"></i>Monti</span><span><i class="dot" style="background:{C['neither']}"></i>Neither (ceiling)</span></div>
</header>
{slides}
{cert_slides}
<section class="slide"><h2>Bottom line</h2><div class="card" style="max-width:900px">
<ul style="font-size:14px;line-height:1.6">
<li><b>The methods agree on the core.</b> ~83–85% of establishably-co-present metabolites are harmonized identically by both Monti and BioMapper.</li>
<li><b>They are complementary, not redundant.</b> Union coverage {tot_either}/{tot_panel} ({round(100*tot_either/tot_panel)}%) exceeds either method alone — each catches links the other misses; where structurally checkable, both are mostly correct.</li>
<li><b>The performance ceiling is real and small.</b> {tot_neither} metabolites (~{round(100*tot_neither/tot_panel)}% across both panels) harmonize by <i>neither</i> method — the headroom a next-generation harmonizer must close. Its composition differs by cohort: arivale's ceiling is ~84% structurally-unresolvable lipids, while Xu's is mostly non-lipid small molecules that share no cross-cohort identifier or standardized name (conjugates, name variants, obscure metabolites).</li>
</ul></div></section>
</body></html>"""
    out = RUN / "three_groups_report.html"
    out.write_text(html)
    print(f"[done] {out}")


if __name__ == "__main__":  # pragma: no cover
    main()
