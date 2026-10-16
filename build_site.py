"""
Builds a static copy of the dashboard (docs/index.html) from the data the agent saved.
Cloudflare Pages publishes the "docs" folder after every agent run. It never sleeps, loads fast,
and keeps working even if the Streamlit site is down.
"""
import html
import json
from pathlib import Path

from agent.summary import build, inr_cr, pct

OUT = Path(__file__).parent / "docs"

def site_links():
    from agent.settings import load_settings
    st = load_settings()
    return [(label, st.get(key)) for label, key in (("Interactive (Streamlit)", "SITE_STREAMLIT"),
                                                   ("Interactive backup (Hugging Face)", "SITE_HUGGINGFACE"),
                                                   ("Fast copy (Cloudflare)", "SITE_CLOUDFLARE")) if st.get(key)]


def e(x):
    return html.escape(str(x)) if x is not None else ""


def pill(word):
    w = (word or "").lower()
    cls = "pos" if w in ("positive", "raised", "introduced") else "neg" if w in ("negative", "cut") else \
        "mid" if w in ("neutral", "mixed", "retained") else "na"
    return f"<span class='pill {cls}'>{e(word or 'n/a')}</span>" if word else ""


def company_card(r):
    i = r["insight"] or {}
    m = (i.get("metrics") or {}) if i.get("results_found") else {}
    status = f"<span class='pos'>{e(i.get('quarter'))} results out</span>" if r["reported"] else \
        "<span class='na'>awaiting results" + (f" · due {e(r['due'])}" if r["due"] else "") + "</span>"
    filed = f"<p class='sub'>📄 Filed on the exchange {e(r['filed_at'])} IST</p>" if r["filed_at"] else ""
    tiles = [("Revenue", inr_cr(r["revenue"])), ("Revenue YoY", pct(r["rev_yoy"])),
             ("CC growth YoY", pct(m.get("cc_growth_yoy_pct"))), ("Op. margin", pct(r["op_margin"], False)),
             ("Net profit", inr_cr(r["net_profit"])),
             ("Deal wins", f"${m['deal_wins_usd_bn']:,.2f} bn" if m.get("deal_wins_usd_bn") else "—")]
    tiles_html = "".join(f"<div class='mini'><span>{e(a)}</span><b>{e(b)}</b></div>" for a, b in tiles)
    lists = ""
    for title, key in (("Highlights", "highlights"), ("Risks", "risks")):
        items = i.get(key) or []
        if items:
            lists += f"<h4>{title}</h4><ul>" + "".join(f"<li>{e(x)}</li>" for x in items) + "</ul>"
    guid = f"<h4>Guidance {pill(i.get('guidance_change'))}</h4><p>{e(i.get('guidance'))}</p>" if i.get("guidance") else ""
    srcs = i.get("sources") or []
    src_html = "<h4>Sources</h4><ul class='src'>" + "".join(
        f"<li>{'📄 ' if s.get('official') else ''}<a href='{e(s.get('link'))}' target='_blank' rel='noopener'>{e(s.get('title'))}</a>"
        f" <span class='sub'>{e(s.get('source'))} · {e((s.get('published') or '')[:10])}</span></li>" for s in srcs) + "</ul>" if srcs else ""
    head = f"<p class='lead'>{e(i.get('headline'))} {pill(i.get('sentiment'))}</p>" if i.get("headline") else ""
    return f"""<details class='card co' style='border-left-color:{r["color"]}'>
<summary><b>{e(r['name'])}</b> <span class='sub'>· {e(r['data_quarter'] or '')}</span> · {status}</summary>
{filed}{head}<div class='minis'>{tiles_html}</div>{guid}{lists}{src_html}</details>"""


def page(s):
    k = s["kpi"]
    sec = s["sector"] or {}
    rows = s["rows"]
    chips = "".join(
        f"<span class='chip' style='border-color:{r['color']}'><i style='background:{r['color']}'></i>{e(r['company'])} · "
        + (f"<span class='pos'>{e(s['quarter'])} out{' ✓ filed' if r['official'] else ''}</span>" if r["reported"]
           else "<span class='na'>awaiting" + (f" · due {e(r['due'])}" if r["due"] else "") + "</span>") + "</span>"
        for r in rows)
    cols = [("Company", "company", None), ("Data quarter", "data_quarter", None), ("Revenue", "revenue", "cr"),
            ("QoQ", "rev_qoq", "s"), ("YoY", "rev_yoy", "s"), ("Op. margin", "op_margin", "p"),
            ("Net margin", "net_margin", "p"), ("Net profit", "net_profit", "cr"), ("CC YoY", "cc_yoy", "s"),
            ("Deals $bn", "deals", "n"), ("Guidance", "guidance", None), ("Mood", "mood", None),
            ("Mkt cap", "mcap", "cr"), ("1Y return", "ret_1y", "s"), ("P/E", "pe", "n")]

    def cell(r, key, kind):
        v = r[key]
        if v is None or v == "":
            return "<td data-v=''>—</td>"
        if kind == "cr":
            return f"<td data-v='{v}' class='num'>{inr_cr(v)}</td>"
        if kind == "s":
            return f"<td data-v='{v}' class='num'>{pct(v)}</td>"
        if kind == "p":
            return f"<td data-v='{v}' class='num'>{pct(v, False)}</td>"
        if kind == "n":
            return f"<td data-v='{v}' class='num'>{v:,.2f}</td>" if isinstance(v, float) else f"<td data-v='{v}'>{e(v)}</td>"
        if key == "company":
            return f"<td data-v='{e(v)}'><i class='dot' style='background:{r['color']}'></i>{e(v)}</td>"
        return f"<td data-v='{e(v)}'>{e(v)}</td>"

    table = "<table id='sc'><thead><tr>" + "".join(f"<th class='{'num' if kind in ('cr', 's', 'p', 'n') else ''}'>{c}</th>" for c, _, kind in cols) + "</tr></thead><tbody>" + \
        "".join("<tr>" + "".join(cell(r, key, kind) for _, key, kind in cols) + "</tr>" for r in rows) + "</tbody></table>"

    themes = "".join(f"<div class='card'><h4>{e(t.get('title'))}</h4><p>{e(t.get('detail'))}</p>"
                     f"<p class='sub'>{e(', '.join(t.get('companies') or []))}</p></div>" for t in (sec.get("themes") or [])[:6])
    leaders = "".join(f"<li><b>{e(x.get('company'))}</b> – {e(x.get('why'))}</li>" for x in sec.get("leaders") or [])
    laggards = "".join(f"<li><b>{e(x.get('company'))}</b> – {e(x.get('why'))}</li>" for x in sec.get("laggards") or [])
    outlook = "".join(f"<div class='card'><h4>{e(o.get('domain'))} {pill(o.get('signal'))}</h4><p>{e(o.get('note'))}</p></div>"
                      for o in sec.get("domain_outlook") or [])
    vrows = "".join(f"<tr><td>{e(v.get('company'))}</td><td>{e(v.get('quarter'))}</td><td>{e(v.get('vertical'))}</td>"
                    f"<td class='num'>{e(v.get('revenue_share_pct') or '—')}</td><td class='num'>{e(v.get('growth_cc_yoy_pct') or v.get('growth_yoy_pct') or '—')}</td>"
                    f"<td>{e(v.get('commentary'))}</td></tr>" for v in s["verticals"])
    news = "".join(f"<li><a href='{e(n.get('link'))}' target='_blank' rel='noopener'>{e(n.get('title'))}</a> "
                   f"<span class='sub'>{e(n.get('company'))} · {e(n.get('source'))} · {e((n.get('published') or '')[:10])}</span></li>"
                   for n in s["news"])
    links = " · ".join(f"<a href='{u}' target='_blank' rel='noopener'>{e(t)}</a>" for t, u in site_links())
    cards = "".join(company_card(r) for r in rows)
    data = json.dumps({"rows": [{k: r[k] for k in ("company", "color", "revenue", "rev_yoy", "rev_qoq", "op_margin", "mcap")} for r in rows],
                       "history": s["history"]}, ensure_ascii=False)

    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Indian IT Results</title>
<meta name='description' content='Quarterly results, AI insights and news for the top 10 Indian IT companies.'>
<link rel='preconnect' href='https://fonts.googleapis.com'>
<link href='https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Source+Serif+4:wght@600&display=swap' rel='stylesheet'>
<script src='https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js'></script>
<style>
:root{{--bg:#F6F7FB;--panel:#fff;--ink:#16213E;--muted:#5B6475;--line:#E4E7EC;--pos:#0A7F0A;--neg:#C62828;--mid:#9A6700;--accent:#2A78D6}}
@media (prefers-color-scheme:dark){{:root:not([data-theme='light']){{--bg:#121417;--panel:#1B1E23;--ink:#ECEDEF;--muted:#A3A9B4;--line:#2B3038;--pos:#4CC24C;--neg:#F07171;--mid:#E0B341;--accent:#5A9BE6}}}}
:root[data-theme='dark']{{--bg:#121417;--panel:#1B1E23;--ink:#ECEDEF;--muted:#A3A9B4;--line:#2B3038;--pos:#4CC24C;--neg:#F07171;--mid:#E0B341;--accent:#5A9BE6}}
*{{box-sizing:border-box}} body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 Inter,system-ui,sans-serif}}
.wrap{{max-width:1240px;margin:0 auto;padding:24px 16px 60px}}
h1{{font-family:'Source Serif 4',Georgia,serif;font-size:2rem;margin:0 0 4px}} h2{{margin:34px 0 12px;font-size:1.3rem}}
h4{{margin:10px 0 4px}} a{{color:var(--accent)}} .sub{{color:var(--muted);font-size:.84rem}}
.lead{{font-size:1.05rem;margin:8px 0 12px}}
.kpis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:12px;margin:16px 0}}
.kpi,.card{{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:14px 16px}}
.kpi span{{color:var(--muted);font-size:.75rem;text-transform:uppercase;letter-spacing:.04em}}
.kpi b{{display:block;font-family:'Source Serif 4',Georgia,serif;font-size:1.8rem;margin-top:4px}}
.chips{{display:flex;flex-wrap:wrap;gap:8px}} .chip{{background:var(--panel);border:1px solid var(--line);border-left-width:4px;border-radius:10px;padding:5px 10px;font-size:.82rem}}
.chip i,.dot{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px}}
.pos{{color:var(--pos)}} .neg{{color:var(--neg)}} .mid{{color:var(--mid)}} .na{{color:var(--muted)}}
.pill{{border:1px solid currentColor;border-radius:999px;padding:1px 9px;font-size:.72rem;font-weight:600;white-space:nowrap}}
.scroll{{overflow-x:auto;background:var(--panel);border:1px solid var(--line);border-radius:14px}}
table{{border-collapse:collapse;width:100%;font-size:.86rem}} th,td{{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}}
th{{cursor:pointer;color:var(--muted);font-weight:600;position:sticky;top:0;background:var(--panel)}} td.num,th.num{{text-align:right;font-variant-numeric:tabular-nums}}
.grid2{{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:12px}}
.grid3{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}}
.chart{{background:var(--panel);border:1px solid var(--line);border-radius:14px;min-height:380px}}
details.co{{border-left:5px solid var(--accent);margin-bottom:10px}} details.co summary{{cursor:pointer;font-size:1rem}}
.minis{{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin:10px 0}}
.mini{{border:1px solid var(--line);border-radius:10px;padding:8px 10px}} .mini span{{color:var(--muted);font-size:.72rem;display:block}}
ul{{margin:4px 0 8px;padding-left:20px}} ul.src li,.news li{{margin:4px 0}} .news{{list-style:none;padding:0}}
.news li{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:8px 12px}}
header .sub a{{white-space:nowrap}}
</style></head><body><div class='wrap'>
<header><h1>Indian IT · Quarterly Results</h1>
<p class='sub'>Quarter in focus <b>{e(s['quarter'])}</b> · last agent run {e(s['last_run'])} · page built {e(s['generated'])}<br>
Other copies: {links}</p>
{f"<p class='lead'>{e(sec.get('headline'))}</p>" if sec.get('headline') else ''}</header>
<div class='kpis'>
<div class='kpi'><span>Results out</span><b>{k['reported']}/{k['total']}</b><div class='sub'>for {e(s['quarter'])}</div></div>
<div class='kpi'><span>Combined quarterly revenue</span><b>{inr_cr(k['combined_revenue'])}</b><div class='sub'>{e(k['combined_note'])}</div></div>
<div class='kpi'><span>Median revenue growth</span><b>{pct(k['median_yoy'])}</b><div class='sub'>year on year</div></div>
<div class='kpi'><span>Median operating margin</span><b>{pct(k['median_margin'], False)}</b><div class='sub'>latest quarter</div></div>
</div>
<div class='chips'>{chips}</div>
<h2>Scorecard</h2><p class='sub'>Click a column to sort. Official filings and hand-checked results where available, Yahoo Finance otherwise.</p>
<div class='scroll'>{table}</div>
<div class='grid2' style='margin-top:12px'><div id='bubble' class='chart'></div><div id='rev' class='chart'></div></div>
<div class='grid2' style='margin-top:12px'><div id='trend' class='chart'></div><div id='margin' class='chart'></div></div>
<h2>Sector view</h2>
{f"<div class='card'><p>{e(sec.get('summary'))}</p></div>" if sec.get('summary') else "<p class='sub'>Appears once results are analysed.</p>"}
<div class='grid2' style='margin-top:12px'><div class='card'><h4>Leading</h4><ul>{leaders or '<li>—</li>'}</ul></div>
<div class='card'><h4>Under pressure</h4><ul>{laggards or '<li>—</li>'}</ul></div></div>
<h2>Big themes</h2><div class='grid3'>{themes or "<p class='sub'>—</p>"}</div>
<h2>Media, gaming, education & publishing</h2><div class='grid3'>{outlook or "<p class='sub'>—</p>"}</div>
<div class='scroll' style='margin-top:12px'><table><thead><tr><th>Company</th><th>Quarter</th><th>Segment</th><th class='num'>Share %</th><th class='num'>YoY %</th><th>What was said</th></tr></thead>
<tbody>{vrows or "<tr><td colspan='6'>Fills in as companies report.</td></tr>"}</tbody></table></div>
<h2>Companies</h2><p class='sub'>Click a company to open its details.</p>{cards}
<h2>Latest news</h2><ul class='news'>{news}</ul>
<p class='sub' style='margin-top:30px'>Built automatically by a free AI agent from Yahoo Finance, stock-exchange filings and news.
AI-extracted figures should be checked against company releases. Not investment advice.</p>
</div>
<script>
const D={data};
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const L=(t,extra)=>Object.assign({{title:{{text:t,font:{{size:15}}}},paper_bgcolor:css('--panel'),plot_bgcolor:css('--panel'),
 font:{{family:'Inter, sans-serif',color:css('--ink'),size:12}},margin:{{l:60,r:20,t:48,b:48}},showlegend:false,
 xaxis:{{gridcolor:css('--line'),zerolinecolor:css('--line')}},yaxis:{{gridcolor:css('--line'),zerolinecolor:css('--line')}}}},extra||{{}});
const cfg={{displayModeBar:false,responsive:true}};
if(window.Plotly){{
 const b=D.rows.filter(r=>r.op_margin!=null&&(r.rev_yoy??r.rev_qoq)!=null);
 const mx=Math.max(...b.map(r=>r.mcap||1));
 Plotly.newPlot('bubble',[{{x:b.map(r=>r.rev_yoy??r.rev_qoq),y:b.map(r=>r.op_margin),text:b.map(r=>r.company),mode:'markers+text',textposition:'top center',
  marker:{{size:b.map(r=>10+40*Math.sqrt((r.mcap||mx*0.1)/mx)),color:b.map(r=>r.color),opacity:.8,line:{{color:'white',width:2}}}},
  hovertemplate:'<b>%{{text}}</b><br>Growth %{{x:+.1f}}%<br>Margin %{{y:.1f}}%<extra></extra>'}}],
  L('Growth vs margin (bubble = market cap)',{{xaxis:{{title:'Revenue growth YoY (%)',ticksuffix:'%',gridcolor:css('--line')}},yaxis:{{title:'Operating margin (%)',ticksuffix:'%',gridcolor:css('--line')}}}}),cfg);
 const r=D.rows.filter(r=>r.revenue).sort((a,b)=>a.revenue-b.revenue);
 Plotly.newPlot('rev',[{{type:'bar',orientation:'h',x:r.map(x=>x.revenue),y:r.map(x=>x.company),marker:{{color:r.map(x=>x.color)}},
  text:r.map(x=>'₹'+Math.round(x.revenue).toLocaleString('en-IN')+' cr'),textposition:'outside',cliponaxis:false,
  hovertemplate:'%{{y}}: ₹%{{x:,.0f}} cr<extra></extra>'}}],L('Quarterly revenue, latest quarter',{{xaxis:{{showticklabels:false,gridcolor:css('--line')}},margin:{{l:110,r:90,t:48,b:30}}}}),cfg);
 const tr=[],mg=[];
 for(const row of D.rows){{const h=D.history[row.company]||[];const base=(h.find(p=>p.revenue)||{{}}).revenue;
  tr.push({{x:h.map(p=>p.quarter),y:h.map(p=>p.revenue&&base?p.revenue/base*100:null),name:row.company,mode:'lines+markers',line:{{color:row.color,width:2}},marker:{{size:6}},
   hovertemplate:row.company+' · %{{x}}: %{{y:.1f}}<extra></extra>'}});
  mg.push({{x:h.map(p=>p.quarter),y:h.map(p=>p.op_margin),name:row.company,mode:'lines+markers',line:{{color:row.color,width:2}},marker:{{size:6}},
   hovertemplate:row.company+' · %{{x}}: %{{y:.1f}}%<extra></extra>'}});}}
 const leg={{showlegend:true,legend:{{orientation:'h',y:-0.2}}}};
 Plotly.newPlot('trend',tr,L('Revenue, indexed (first quarter shown = 100)',leg),cfg);
 Plotly.newPlot('margin',mg,L('Operating margin by quarter',Object.assign({{yaxis:{{ticksuffix:'%',gridcolor:css('--line')}}}},leg)),cfg);
}} else {{ for(const id of ['bubble','rev','trend','margin']) document.getElementById(id).innerHTML="<p class='sub' style='padding:16px'>Charts need an internet connection.</p>"; }}
document.querySelectorAll('#sc th').forEach((th,i)=>th.addEventListener('click',()=>{{
 const tb=th.closest('table').tBodies[0];const asc=th.dataset.asc!=='1';th.dataset.asc=asc?'1':'0';
 [...tb.rows].sort((a,b)=>{{const x=a.cells[i].dataset.v,y=b.cells[i].dataset.v;const nx=parseFloat(x),ny=parseFloat(y);
  if(x==='')return 1;if(y==='')return -1;return (!isNaN(nx)&&!isNaN(ny)?nx-ny:x.localeCompare(y))*(asc?1:-1);}}).forEach(tr=>tb.appendChild(tr));}}));
</script></body></html>"""


def main():
    s = build()
    OUT.mkdir(exist_ok=True)
    (OUT / "index.html").write_text(page(s), encoding="utf-8")
    (OUT / "_headers").write_text("/*\n  Cache-Control: public, max-age=300\n", encoding="utf-8")  # Cloudflare: refresh within 5 min
    print(f"Static dashboard written: {OUT / 'index.html'}")


if __name__ == "__main__":
    main()
