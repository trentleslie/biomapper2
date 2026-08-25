"""Generate a self-contained HTML update: BioMapper vs Monti cross-cohort harmonization benchmark.

Inline SVG only (no CDN/JS) so the report opens reliably offline in any browser. Every number is
pinned from the verified 2026-08-25 run; the Arm-M results carry the RefMet-outage caveat.
"""

from __future__ import annotations

import html
from pathlib import Path

# --- verified data (2026-08-25 session) ----------------------------------------------------------
COHORTS = [
    # name, platform, source, panel_used, raw, vendor_ids, monti_overlap, role
    ("NECS", "Metabolon", "spreadsheet + MOESM5", 1213, 1495, "partial (MOESM5)", None, "anchor cohort"),
    ("Arivale", "Metabolon", "Watanabe 2023 (CC BY)", 659, 766, "CAS/KEGG/HMDB/PubChem", 615, "reproduction control"),
    ("Xu et al. '22", "Metabolon", "spreadsheet", 821, 821, "none (names only)", 432, "recovery — same-vendor"),
    ("LLFS", "MS", "spreadsheet (RefMet subset)", 364, 408, "none (names only)", 163, "recovery — cross-platform"),
    ("BLSA", "Biocrates", "spreadsheet", 468, 468, "none (names only)", 99, "counts-only context"),
]

# pair -> (monti_published, arm_b_locked, arm_m_preliminary, necs_resolved, cohort_resolved, cohort_total)
RESULTS = {
    "Arivale": (615, 583, 546, 1182, 617, 659),
    "Xu": (432, 470, 687, 1182, 795, 821),
    "LLFS": (163, 144, 90, 1182, 364, 364),
    "BLSA": (99, 79, 65, 1182, 453, 468),
}

# (what differs in the InChIKey, verdict, verdict-class, meaning, example)
CERTIFICATE_VERDICTS = [
    ("Block 1 — connectivity", "REFUTED", "refute", "Wrong molecule — different molecular skeleton", "DPA (22:5) vs DHA (22:6); indolebutyrate vs indolepropionate"),
    ("Block 2 — stereo (block 1 matches)", "REFUTED", "refute", "Stereoisomer — same skeleton, different stereochemistry", "D- vs L-glucose"),
    ("Only block 3 — protonation", "CERTIFIED", "certify", "Same molecule — acid vs conjugate base", "trans-urocanate acid vs anion (the RefMet-latch splits)"),
    ("Nothing — both blocks match", "CERTIFIED", "certify", "Confirmed same molecule", "—"),
    ("No independent structure on a side", "REFUSED", "refuse", "Cannot be checked — not a disagreement", "BLSA sum-composition lipids; PubChem lookup failure"),
]

ARIVALE_BREAKDOWN = [
    ("BioMapper agrees with name-match", 501, "#2e7d32"),
    ("Same molecule, sibling ChEBI (structure-recoverable)", 36, "#f9a825"),
    ("Different / missing structure", 24, "#ef6c00"),
    ("Both unresolved (coverage)", 20, "#90a4ae"),
    ("Wrong-sense resolution (e.g. glucose→drug)", 2, "#c62828"),
]

KG = "Kraken 2.1.0 · kg2 2.10.2 · biolink 4.2.5 · public keyless endpoint"


def esc(s: object) -> str:
    return html.escape(str(s))


def grouped_bar_svg() -> str:
    pairs = list(RESULTS)
    series = [("Monti published", 0, "#546e7a"), ("Monti re-derived (Arm-B, locked)", 1, "#26a69a"),
              ("BioMapper (Arm-M, preliminary)", 2, "#5c6bc0")]
    W, H, pad_l, pad_b, pad_t = 720, 320, 45, 60, 30
    plot_w, plot_h = W - pad_l - 20, H - pad_b - pad_t
    vmax = 720
    gw = plot_w / len(pairs)
    bw = gw / (len(series) + 1)
    bars, labels = [], []
    for gi, p in enumerate(pairs):
        vals = RESULTS[p]
        x0 = pad_l + gi * gw
        for name, idx, color in series:
            v = vals[idx]
            bh = plot_h * v / vmax
            x = x0 + bw * (idx + 0.5)
            y = pad_t + plot_h - bh
            bars.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" fill="{color}"><title>{esc(name)}: {v}</title></rect>')
            bars.append(f'<text x="{x + bw/2:.1f}" y="{y - 4:.1f}" font-size="11" text-anchor="middle" fill="#333">{v}</text>')
        labels.append(f'<text x="{x0 + gw/2:.1f}" y="{pad_t + plot_h + 18:.1f}" font-size="13" text-anchor="middle" font-weight="600">{esc(p)}</text>')
    # y gridlines
    grid = []
    for gy in range(0, vmax + 1, 120):
        y = pad_t + plot_h - plot_h * gy / vmax
        grid.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{W-20}" y2="{y:.1f}" stroke="#eee"/>')
        grid.append(f'<text x="{pad_l-6}" y="{y+4:.1f}" font-size="10" text-anchor="end" fill="#999">{gy}</text>')
    legend = []
    lx = pad_l
    for name, _idx, color in series:
        legend.append(f'<rect x="{lx}" y="6" width="12" height="12" fill="{color}"/>')
        legend.append(f'<text x="{lx+16}" y="16" font-size="11" fill="#333">{esc(name)}</text>')
        lx += 12 + 8 + len(name) * 6.4 + 18
    return f'<svg viewBox="0 0 {W} {H}" width="100%" style="max-width:760px">{"".join(grid)}{"".join(bars)}{"".join(labels)}{"".join(legend)}</svg>'


def stacked_breakdown_svg() -> str:
    total = sum(n for _, n, _ in ARIVALE_BREAKDOWN)
    W, H, x0 = 720, 74, 10
    plot_w = W - 2 * x0
    segs, leg, cursor, ly = [], [], x0, 0
    for label, n, color in ARIVALE_BREAKDOWN:
        w = plot_w * n / total
        segs.append(f'<rect x="{cursor:.1f}" y="10" width="{w:.1f}" height="30" fill="{color}"><title>{esc(label)}: {n}</title></rect>')
        if w > 26:
            segs.append(f'<text x="{cursor + w/2:.1f}" y="30" font-size="12" text-anchor="middle" fill="#fff" font-weight="600">{n}</text>')
        cursor += w
    for label, n, color in ARIVALE_BREAKDOWN:
        leg.append(f'<span class="chip"><span class="sw" style="background:{color}"></span>{esc(label)} ({n})</span>')
    return f'<svg viewBox="0 0 {W} 50" width="100%" style="max-width:760px">{"".join(segs)}</svg><div class="legend">{"".join(leg)}</div>'


def cohort_size_svg() -> str:
    rows = [(c[0], c[3]) for c in COHORTS]
    W, rowh, x0 = 720, 30, 150
    vmax = max(v for _, v in rows)
    bars = []
    for i, (name, v) in enumerate(rows):
        y = 10 + i * rowh
        w = (W - x0 - 60) * v / vmax
        bars.append(f'<text x="{x0-8}" y="{y+16}" font-size="13" text-anchor="end" font-weight="600">{esc(name)}</text>')
        bars.append(f'<rect x="{x0}" y="{y+3}" width="{w:.1f}" height="18" fill="#5c6bc0"/>')
        bars.append(f'<text x="{x0+w+6:.1f}" y="{y+17}" font-size="12" fill="#333">{v}</text>')
    return f'<svg viewBox="0 0 {W} {10 + len(rows)*rowh}" width="100%" style="max-width:760px">{"".join(bars)}</svg>'


def cohort_table() -> str:
    head = "<tr><th>Cohort</th><th>Platform</th><th>Source</th><th>Panel used</th><th>Vendor IDs</th><th>Monti overlap w/ NECS</th><th>Role</th></tr>"
    rows = []
    for name, plat, src, used, raw, ids, ov, role in COHORTS:
        used_s = f"{used}" + (f" <span class='muted'>(of {raw})</span>" if raw != used else "")
        rows.append(f"<tr><td><b>{esc(name)}</b></td><td>{esc(plat)}</td><td>{esc(src)}</td><td>{used_s}</td><td>{esc(ids)}</td><td>{'—' if ov is None else ov}</td><td>{esc(role)}</td></tr>")
    return f"<table>{head}{''.join(rows)}</table>"


def results_table() -> str:
    head = "<tr><th>Pair (NECS↔)</th><th>Monti published</th><th>Arm-B re-derived</th><th>BioMapper Arm-M*</th><th>BioMapper resolved</th></tr>"
    rows = []
    for p, (pub, b, m, _nr, cr, ct) in RESULTS.items():
        arrow = "▲" if m > b else "▼"
        cls = "up" if m > b else "down"
        rows.append(f"<tr><td><b>{esc(p)}</b></td><td>{pub}</td><td>{b}</td><td class='{cls}'>{m} {arrow}</td><td>{cr}/{ct}</td></tr>")
    return f"<table>{head}{''.join(rows)}</table>"


def inchikey_anatomy_svg() -> str:
    return (
        '<div class="inchi">'
        '<span class="blk b1">WQZGKKKJIJFFOK</span><span class="dash">-</span>'
        '<span class="blk b2">GASJEMHN</span><span class="blk b2b">SA</span><span class="dash">-</span>'
        '<span class="blk b3">N</span>'
        '</div>'
        '<div class="inchi-key"><span class="sw" style="background:#1e88e5"></span>Block 1 — connectivity (skeleton)'
        '<span class="sw" style="background:#f9a825;margin-left:14px"></span>Block 2[:8] — stereochemistry'
        '<span class="sw" style="background:#cfd8dc;margin-left:14px"></span>Block 3 — protonation (ignored)</div>'
        '<p class="sub" style="margin-top:6px">Certificate key = <b>block 1 + block 2[:8]</b> — enforces connectivity &amp; stereo, '
        '<b>ignores protonation</b> (so acid/base variants certify as the same molecule).</p>'
    )


def certificate_verdict_table() -> str:
    head = "<tr><th>What differs in the InChIKey</th><th>Verdict</th><th>Meaning</th><th>Example</th></tr>"
    rows = []
    for diff, verdict, cls, meaning, ex in CERTIFICATE_VERDICTS:
        rows.append(f"<tr><td>{esc(diff)}</td><td><span class='pill {cls}'>{verdict}</span></td><td>{esc(meaning)}</td><td class='muted'>{esc(ex)}</td></tr>")
    return f"<table>{head}{''.join(rows)}</table>"


def build() -> str:
    css = """
    body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#222;max-width:860px;margin:24px auto;padding:0 18px;line-height:1.5}
    h1{font-size:26px;margin:0 0 2px} h2{font-size:19px;margin:30px 0 8px;border-bottom:2px solid #eee;padding-bottom:4px}
    h3{font-size:15px;margin:18px 0 6px;color:#37474f}
    .sub{color:#607d8b;margin:0 0 14px} table{border-collapse:collapse;width:100%;font-size:13px;margin:10px 0}
    th,td{border:1px solid #e0e0e0;padding:6px 8px;text-align:left} th{background:#f5f5f7} .muted{color:#999;font-weight:400}
    .up{color:#2e7d32;font-weight:600} .down{color:#c62828;font-weight:600}
    .callout{border-left:4px solid #f9a825;background:#fff8e1;padding:10px 14px;border-radius:4px;margin:14px 0}
    .callout.warn{border-color:#c62828;background:#ffebee} .callout.ok{border-color:#2e7d32;background:#e8f5e9}
    .legend{margin-top:8px;font-size:12px} .chip{display:inline-block;margin:2px 10px 2px 0} .sw{display:inline-block;width:11px;height:11px;border-radius:2px;margin-right:4px;vertical-align:middle}
    .pipe{display:flex;gap:8px;align-items:center;flex-wrap:wrap;font-size:13px;margin:10px 0}
    .box{border:1px solid #cfd8dc;border-radius:6px;padding:8px 10px;background:#fafafa} .arw{color:#90a4ae;font-weight:700}
    code{background:#f0f0f3;padding:1px 4px;border-radius:3px;font-size:12px} .tag{display:inline-block;background:#eceff1;border-radius:10px;padding:1px 9px;font-size:12px;color:#455a64;margin-left:6px}
    .pill{display:inline-block;border-radius:10px;padding:1px 10px;font-size:12px;font-weight:700;color:#fff}
    .pill.certify{background:#2e7d32} .pill.refute{background:#c62828} .pill.refuse{background:#78909c}
    .inchi{font-family:ui-monospace,Menlo,Consolas,monospace;font-size:22px;letter-spacing:1px;margin:8px 0 4px}
    .blk{padding:2px 4px;border-radius:3px;color:#fff} .b1{background:#1e88e5} .b2{background:#f9a825} .b2b{background:#f9a825;opacity:.5} .b3{background:#cfd8dc;color:#37474f} .dash{color:#90a4ae;padding:0 2px}
    .inchi-key{font-size:12px;color:#455a64;margin-bottom:2px}
    """
    pipe = """
    <div class="pipe">
      <span class="box">Cohort names<br><span class="muted">(spreadsheet columns)</span></span><span class="arw">→</span>
      <span class="box">BioMapper<br><span class="muted">name → KG node</span></span><span class="arw">→</span>
      <span class="box">Kraken node<br><span class="muted">+ cross-refs</span></span><span class="arw">→</span>
      <span class="box"><b>Arm-M link</b><br><span class="muted">same node, NECS↔cohort</span></span>
    </div>
    <div class="pipe">
      <span class="box">Cohort names</span><span class="arw">→</span>
      <span class="box">name / RefMet-name match<br><span class="muted">Monti's method</span></span><span class="arw">→</span>
      <span class="box"><b>Arm-B link</b> (baseline)</span>
    </div>
    """
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>BioMapper vs Monti — Cross-Cohort Harmonization</title><style>{css}</style></head><body>
<h1>BioMapper vs Monti — Cross-Cohort Metabolite Harmonization</h1>
<p class="sub">Benchmark update · 2026-08-25 · <span class="tag">first live run</span><span class="tag">coverage-first</span></p>

<div class="callout"><b>One-line status.</b> The benchmark instrument is built and validated; the locked Monti baseline reproduces the paper exactly; the first live BioMapper run completed but a <b>client-side circuit breaker latched RefMet off for the whole run</b>, so the BioMapper numbers below are <b>preliminary, not yet a verdict</b>.</div>

<h2>1 · Data sources &amp; cohorts</h2>
<p>Monti et al. 2026 (GeroScience) harmonized the New England Centenarian Study (NECS) against four other cohorts. We compare BioMapper's harmonization against Monti's published overlaps, pair by pair.</p>
<h3>Spreadsheets in use</h3>
<ul>
<li><b>4-cohort metabolite spreadsheet</b> (<code>datasets_metabolites.xlsx</code>) — one sheet, four columns, <b>names only</b>: <code>blsa</code> 468, <code>llfs</code> 364, <code>necs</code> 1495 (1213 named), <code>xuetal</code> 821.</li>
<li><b>Arivale panel</b> (Watanabe 2023, <b>CC BY</b>) — 766 metabolites (659 named) <b>with vendor IDs</b> (CAS/KEGG/HMDB/PubChem). Not in the 4-cohort spreadsheet; it is the only cohort carrying identifiers for later structural work.</li>
<li><b>NECS annotation</b> (Monti MOESM5) — the 1,495-row Metabolon annotation with curated InChIKey/SMILES; used for the structure oracle (deferred certificate work), not the coverage arms.</li>
</ul>
<h3>Cohorts covered</h3>
{cohort_table()}
<h3>Panel sizes (metabolites used)</h3>
{cohort_size_svg()}

<h2>2 · Approach</h2>
<p>Each cohort's metabolite <b>names</b> are the query. We score three arms on the same pairs; today's report covers Arm-B and Arm-M (coverage). Structure certification is built but parked.</p>
{pipe}
<ul>
<li><b>Arm-B — Monti's method (baseline to beat):</b> name-string match for same-vendor pairs (Arivale, Xu), RefMet standardized-name join for cross-platform pairs (LLFS, BLSA). <b>Locked</b> as a characterization test — it reproduces Monti's replication exactly.</li>
<li><b>Arm-M — BioMapper:</b> each name resolves to a Kraken knowledge-graph node; two metabolites link when they resolve to the <b>same node</b>. Identifier-based, structure excluded from linking.</li>
<li><b>Deferred — structural certificate:</b> validate each link by InChIKey connectivity from a KG-independent source. This is also the right <i>comparison vocabulary</i>: it unifies acid/base ChEBI variants that identifier strings split.</li>
</ul>
<div class="callout"><b>KG snapshot pinned:</b> {esc(KG)}.</div>

<h2>3 · Current results</h2>
<p>Distinct NECS metabolites linked to each cohort — Monti published vs our re-derived Monti baseline vs BioMapper.</p>
{grouped_bar_svg()}
{results_table()}
<p class="sub">*BioMapper Arm-M = distinct NECS metabolites resolving to the <b>same Kraken node</b> as a cohort metabolite. Strict (same-node), not loose cross-ref sharing.</p>
<div class="callout warn"><b>Why these are preliminary (verified).</b> The RefMet API is <b>up</b> (single calls 200/0.25s; a 30-call burst is 30/30 clean) — this was <b>not</b> a server outage. Instead, ~3 transient early failures tripped BioMapper's RefMet <b>circuit breaker</b> (<code>failure_threshold=3, recovery_timeout=300s</code>), which then <b>latched open and skipped RefMet for the rest of the run</b> — RefMet resolved 15% of NECS and <b>0% of every cohort</b>. Cohorts fell back to a secondary annotator that picks different (acid- vs base-form) ChEBI nodes, so true matches split across sibling nodes and were missed. <b>Fix is entirely client-side</b> (RefMet cache / force-IPv4 / saner retry); a re-run should recover most of the gap.</div>

<h2>4 · Deep dive: the Arivale gap</h2>
<p>On the 583 name-matched Arivale pairs, BioMapper agrees on <b>501 (86%)</b>. The rest is systematic, not noise:</p>
{stacked_breakdown_svg()}
<ul>
<li><b>36 of the misses are the same molecule</b> resolved to sibling ChEBI nodes (e.g. <i>trans</i>-urocanate CHEBI:30817 vs 17771) — a structure check recovers them, and the split traces directly to the RefMet circuit-breaker latch (NECS via RefMet → base node; cohorts via fallback → acid node).</li>
<li><b>2 wrong-sense resolutions</b> (e.g. <code>glucose</code> → a drug node) — a real resolution bug worth a look.</li>
<li><b>20 coverage misses</b> — names that did not resolve at all.</li>
</ul>

<h2>5 · The structure certificate — how disagreements are adjudicated</h2>
<p>Coverage counts <i>which</i> pairs link; the certificate decides <i>whether a link is real</i> by comparing the two metabolites' structures — each resolved from a source <b>independent of the knowledge graph</b> — at the level of the InChIKey blocks. This is the mechanism that separates the genuine part of BioMapper's Xu <b>+217</b> from the over-links.</p>
{inchikey_anatomy_svg()}
<p>When the two structures <b>disagree</b>, the link is <b>refuted</b>, and <i>which block</i> differs classifies the reason:</p>
{certificate_verdict_table()}
<div class="callout"><b>Why this is the spine, not an add-on.</b> The same rule that <span class="pill certify">CERTIFIED</span> recovers the RefMet-latch acid/base splits on Arivale (protonation-only difference) also <span class="pill refute">REFUTED</span> the Xu near-isomer over-links (DPA 22:5 vs DHA 22:6 differ at block 1). A refuted link is not discarded — it becomes a <b>certificate-triaged discrepancy</b> routed to expert review (the EITL campaign).</div>
<p class="sub">Caveats: when one side resolves to a first-block-only InChIKey, the check runs at connectivity and flags stereo as unverified; InChIKey block 1 is not invariant to ring-chain tautomerism (e.g. xylose), a documented edge case.</p>

<h2>6 · Status &amp; next steps</h2>
<div class="callout ok"><b>Done:</b> instrument built (5 offline units, 48 tests, no regressions); Monti baseline locked &amp; reproduced (583/470/144/79); first live BioMapper run executed end-to-end with pinned provenance; failure mode diagnosed.</div>
<ul>
<li><b>Re-run Arm-M with RefMet restored</b> (cache the RefMet responses / rate-limit) — the honest number should rise materially above 546.</li>
<li><b>Record per-annotator health in the manifest</b> so a degraded run can't masquerade as valid.</li>
<li><b>Decide the comparison vocabulary</b> — evidence points to InChIKey connectivity (structure), which also unifies acid/base splits.</li>
<li><b>Then layer the structural certificate</b> — turns "coverage" into "certified recovery," the preprint's spine.</li>
</ul>
<p class="sub">Generated 2026-08-25 · self-contained · numbers pinned to run <code>cross_cohort_arm_m_20260825T165544Z</code>.</p>
</body></html>"""


if __name__ == "__main__":
    out = Path.home() / "external_benchmark_runs" / "biomapper_vs_monti_report_20260825.html"
    out.write_text(build())
    print(f"wrote {out}  ({out.stat().st_size} bytes)")
