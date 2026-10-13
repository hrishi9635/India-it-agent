"""
Indian IT Results Dashboard
---------------------------
Draws everything the agent saved in the "data" folder. You don't need to edit this file.
Start it with:  python -m streamlit run app.py
"""
import csv
import html
import json
import statistics
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

ROOT = Path(__file__).parent
DATA = ROOT / "data"

st.set_page_config(page_title="Indian IT Results Dashboard", page_icon="📈", layout="wide",
                   initial_sidebar_state="expanded")

# ---------------------------------------------------------------- look & feel
INK, MUTED, LINE, PANEL = "#16213E", "#5B6475", "#E4E7EC", "#FFFFFF"
GOOD, BAD, WARN, ACCENT = "#0F9D58", "#D93025", "#E37400", "#2F5BEA"
PALETTE = ["#2F5BEA", "#E8590C", "#0CA678", "#7048E8", "#D6336C",
           "#1098AD", "#F59F00", "#5C940D", "#AE3EC9", "#495057"]

st.markdown(f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Source+Serif+4:wght@500;600&display=swap');
html, body, [class*="css"], .stMarkdown, .stDataFrame {{ font-family: 'Inter', system-ui, sans-serif; }}
.block-container {{ padding-top: 1.6rem; padding-bottom: 3rem; max-width: 1360px; }}
h1, h2, h3 {{ color: {INK}; letter-spacing: -0.015em; }}
h1 {{ font-family: 'Source Serif 4', Georgia, serif; font-weight: 600; }}
.lead {{ font-size: 1.08rem; color: {INK}; line-height: 1.55; max-width: 64rem; margin: -0.2rem 0 0.4rem; }}
.sub {{ color: {MUTED}; font-size: 0.84rem; }}
.kpi {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 14px; padding: 16px 18px; height: 100%; }}
.kpi .lab {{ color: {MUTED}; font-size: 0.78rem; font-weight: 500; text-transform: uppercase; letter-spacing: .04em; }}
.kpi .big {{ font-family: 'Source Serif 4', Georgia, serif; font-size: 2.0rem; color: {INK}; line-height: 1.15; margin-top: 6px; }}
.kpi .note {{ color: {MUTED}; font-size: 0.78rem; margin-top: 4px; }}
.card {{ background: {PANEL}; border: 1px solid {LINE}; border-radius: 14px; padding: 16px 18px; margin-bottom: 12px; }}
.card h4 {{ margin: 0 0 6px; font-size: 1rem; color: {INK}; display: flex; justify-content: space-between; gap: 8px; align-items: center; }}
.card p, .card li {{ font-size: 0.9rem; color: {INK}; line-height: 1.5; margin: 4px 0; }}
.callout {{ border-left: 4px solid {ACCENT}; background: #F3F6FF; padding: 12px 16px; border-radius: 8px; color: {INK}; font-size: 1rem; margin: 6px 0 14px; }}
.pill {{ display: inline-block; font-size: 0.72rem; font-weight: 600; border-radius: 999px; padding: 2px 10px; border: 1px solid currentColor; white-space: nowrap; }}
.pos {{ color: {GOOD}; }} .neg {{ color: {BAD}; }} .mid {{ color: {WARN}; }} .na {{ color: {MUTED}; }}
.chips {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 4px 0 8px; }}
.chip {{ border: 1px solid {LINE}; background: {PANEL}; border-radius: 10px; padding: 6px 10px; font-size: 0.82rem; color: {INK}; }}
.chip b {{ font-weight: 600; }}
.news a {{ color: {INK}; text-decoration: none; font-weight: 500; }}
.news a:hover {{ text-decoration: underline; }}
.news div {{ padding: 8px 0; border-bottom: 1px solid {LINE}; font-size: 0.9rem; }}
.news span {{ color: {MUTED}; font-size: 0.78rem; }}
section[data-testid="stSidebar"] {{ background: #F7F8FB; }}
</style>""", unsafe_allow_html=True)


def esc(x):
    return html.escape(str(x)) if x is not None else ""


def tone_class(word):
    w = (word or "").lower()
    if w in ("positive", "raised", "introduced"):
        return "pos"
    if w in ("negative", "cut"):
        return "neg"
    if w in ("mixed", "neutral", "retained"):
        return "mid"
    return "na"


def pill(word):
    return f"<span class='pill {tone_class(word)}'>{esc(word or 'n/a')}</span>"


def inr_cr(v):
    if v is None or pd.isna(v):
        return "—"
    return f"₹{v / 1e5:,.2f} lakh cr" if abs(v) >= 1e5 else f"₹{v:,.0f} cr"


def pct(v, signed=True):
    if v is None or pd.isna(v):
        return "—"
    return f"{v:+.1f}%" if signed else f"{v:.1f}%"


def style(fig, height=380, title=None, legend=True):
    fig.update_layout(
        height=height, title=dict(text=title, font=dict(size=15, color=INK)) if title else None,
        margin=dict(l=8, r=16, t=48 if title else 16, b=8), paper_bgcolor="white", plot_bgcolor="white",
        font=dict(family="Inter, system-ui, sans-serif", color=INK, size=12),
        hoverlabel=dict(bgcolor="white", font_size=12), showlegend=legend,
        legend=dict(orientation="h", yanchor="top", y=-0.12, x=0, title=None),
    )
    fig.update_xaxes(showgrid=False, linecolor=LINE, tickcolor=LINE)
    fig.update_yaxes(gridcolor="#EEF0F4", zerolinecolor="#C9CED6", linecolor=LINE)
    return fig


def show_chart(fig):
    try:
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
    except Exception:  # older Streamlit versions
        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})


def show_table(df, **kw):
    try:
        st.dataframe(df, width="stretch", hide_index=True, **kw)
    except Exception:  # older Streamlit versions
        st.dataframe(df, use_container_width=True, hide_index=True, **kw)


def kpi(col, label, value, note=""):
    col.markdown(f"<div class='kpi'><div class='lab'>{esc(label)}</div><div class='big'>{esc(value)}</div>"
                 f"<div class='note'>{esc(note)}</div></div>", unsafe_allow_html=True)


# ---------------------------------------------------------------- data
def stamp():
    return tuple(p.stat().st_mtime for p in sorted(DATA.glob("*")) if p.is_file())


@st.cache_data(ttl=1800)
def load(data_version):
    def rj(name, default):
        p = DATA / name
        try:
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
        except json.JSONDecodeError:
            return default

    def rc(name):
        p = DATA / name
        return pd.read_csv(p, encoding="utf-8-sig") if p.exists() and p.stat().st_size > 0 else pd.DataFrame()

    with open(ROOT / "companies.csv", encoding="utf-8-sig", newline="") as fh:
        comps = [r for r in csv.DictReader(fh) if (r.get("name") or "").strip()]
    return {
        "companies": comps, "fin": rc("financials.csv"), "market": rc("market.csv"), "prices": rc("prices.csv"),
        "insights": rj("insights.json", {}), "sector": rj("sector.json", {}), "news": rj("news.json", {}),
        "runs": rj("run_log.json", []), "filings": rj("filings.json", {}),
    }


D = load(stamp())
ORDER = [c["short_name"] or c["name"] for c in D["companies"]]
NAMES = {(c["short_name"] or c["name"]): c["name"] for c in D["companies"]}
COLOR = {n: PALETTE[i % len(PALETTE)] for i, n in enumerate(ORDER)}
COLOR["Nifty IT"] = "#868E96"
INS, SECTOR, FIL = D["insights"], D["sector"], D["filings"]

if D["fin"].empty and not INS:
    st.title("Indian IT Results Dashboard")
    st.info("No data yet. Run the agent first: double-click **2 - Run the agent** in the project folder "
            "(or type `python run_agent.py`), then refresh this page.")
    st.stop()


def quarter_key(q):
    try:
        return (int(q.split("FY")[1]), int(q[1]))
    except Exception:  # noqa: BLE001
        return (0, 0)


# wide financial table: one row per company per quarter
fin = D["fin"]
if not fin.empty:
    wide = fin.pivot_table(index=["company", "period_end", "quarter"], columns="metric", values="value_inr_cr").reset_index()
    wide = wide.sort_values(["company", "period_end"])
    for m in ("revenue", "operating_income", "net_income"):
        if m not in wide:
            wide[m] = float("nan")
    wide["op_margin"] = wide["operating_income"] / wide["revenue"] * 100
    wide["net_margin"] = wide["net_income"] / wide["revenue"] * 100
    wide["rev_qoq"] = wide.groupby("company")["revenue"].pct_change(fill_method=None) * 100
    wide["rev_yoy"] = wide.groupby("company")["revenue"].pct_change(4, fill_method=None) * 100
    wide["np_yoy"] = wide.groupby("company")["net_income"].pct_change(4, fill_method=None) * 100
    latest = wide.groupby("company").tail(1).set_index("company")
else:
    wide = pd.DataFrame()
    latest = pd.DataFrame()
mkt = D["market"].set_index("company") if not D["market"].empty else pd.DataFrame()

target_q = SECTOR.get("quarter") or max((i.get("quarter") for i in INS.values() if i), key=quarter_key, default="")
reported = [n for n in ORDER if (INS.get(n) or {}).get("quarter") == target_q and (INS.get(n) or {}).get("results_found")]


def m_ai(name, key):
    ins = INS.get(name) or {}
    return (ins.get("metrics") or {}).get(key) if ins.get("results_found") else None


def latest_val(name, col):
    try:
        v = latest.loc[name, col]
        return None if pd.isna(v) else float(v)
    except (KeyError, TypeError):
        return None


def mkt_val(name, col):
    try:
        v = mkt.loc[name, col]
        return None if pd.isna(v) else float(v)
    except (KeyError, TypeError, ValueError):
        return None


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.markdown("### 📈 Indian IT Results")
    st.markdown(f"<div class='sub'>Quarter in focus: <b>{esc(target_q or '—')}</b><br>"
                f"Results out: <b>{len(reported)}</b> of {len(ORDER)} companies</div>", unsafe_allow_html=True)
    page = st.radio("Go to", ["Overview", "Sector view", "Company deep-dive", "Financial trends",
                              "Share price & valuation", "Media · Gaming · EdTech · Publishing", "News", "About & data"],
                    label_visibility="collapsed")
    if D["runs"]:
        st.markdown(f"<div class='sub'>Last agent run: {esc(D['runs'][0].get('finished', '')[:16].replace('T', ' '))} UTC</div>",
                    unsafe_allow_html=True)
    st.markdown("<div class='sub'>Free & open source: yfinance, Google/Bing News, an open AI model, Streamlit.</div>",
                unsafe_allow_html=True)


# ---------------------------------------------------------------- scorecard (shared)
def fresher_numbers(n):
    """Yahoo can take days to add a new quarter. If the company has already filed its results on the
    exchange and the AI read them, use those numbers for the scorecard until Yahoo catches up."""
    ins = INS.get(n) or {}
    yq = latest.loc[n, "quarter"] if n in latest.index else None
    if not (ins.get("results_found") and ins.get("official") and ins.get("quarter") == target_q) or yq == target_q:
        return None
    m = ins.get("metrics") or {}
    rev, np_ = m.get("revenue_inr_cr"), m.get("net_profit_inr_cr")
    if rev is None:
        return None
    prev = latest_val(n, "revenue")
    return {
        "Data quarter": f"{target_q} (filing)",
        "Revenue (₹ cr)": rev,
        "Revenue QoQ %": round((rev / prev - 1) * 100, 1) if prev else None,
        "Revenue YoY %": m.get("revenue_growth_yoy_pct"),
        "Op. margin %": m.get("operating_margin_pct"),
        "Net margin %": round(np_ / rev * 100, 1) if np_ is not None and rev else None,
        "Net profit (₹ cr)": np_,
    }


def scorecard():
    rows = []
    for n in ORDER:
        ins = INS.get(n) or {}
        row = {
            "Company": n,
            "Data quarter": latest.loc[n, "quarter"] if n in latest.index else None,
            "Revenue (₹ cr)": latest_val(n, "revenue"),
            "Revenue QoQ %": latest_val(n, "rev_qoq"),
            "Revenue YoY %": latest_val(n, "rev_yoy"),
            "Op. margin %": latest_val(n, "op_margin"),
            "Net margin %": latest_val(n, "net_margin"),
            "Net profit (₹ cr)": latest_val(n, "net_income"),
            "CC growth YoY %": m_ai(n, "cc_growth_yoy_pct"),
            "Deal wins ($ bn)": m_ai(n, "deal_wins_usd_bn"),
            "Guidance": ins.get("guidance_change") if ins.get("results_found") else None,
            "Mood": ins.get("sentiment") if ins.get("results_found") else None,
            "Market cap (₹ cr)": mkt_val(n, "market_cap_cr"),
            "1Y return %": mkt_val(n, "return_1y"),
            "P/E": mkt_val(n, "pe_ttm"),
        }
        row.update(fresher_numbers(n) or {})
        rows.append(row)
    return pd.DataFrame(rows)


SC_CONFIG = {
    "Revenue (₹ cr)": st.column_config.NumberColumn(format="%.0f"),
    "Revenue QoQ %": st.column_config.NumberColumn(format="%+.1f"),
    "Revenue YoY %": st.column_config.NumberColumn(format="%+.1f"),
    "Op. margin %": st.column_config.ProgressColumn(format="%.1f", min_value=0, max_value=35),
    "Net margin %": st.column_config.NumberColumn(format="%.1f"),
    "Net profit (₹ cr)": st.column_config.NumberColumn(format="%.0f"),
    "CC growth YoY %": st.column_config.NumberColumn(format="%+.1f"),
    "Deal wins ($ bn)": st.column_config.NumberColumn(format="%.2f"),
    "Market cap (₹ cr)": st.column_config.NumberColumn(format="%.0f"),
    "1Y return %": st.column_config.NumberColumn(format="%+.1f"),
    "P/E": st.column_config.NumberColumn(format="%.1f"),
}


def page_header(title, sub=None):
    st.title(title)
    if sub:
        st.markdown(f"<p class='sub'>{esc(sub)}</p>", unsafe_allow_html=True)


# ================================================================ pages
if page == "Overview":
    page_header("Indian IT · Quarterly Results Dashboard",
                f"Top {len(ORDER)} Indian IT companies · quarter in focus {target_q} · "
                "reported numbers from Yahoo Finance, insights read from the news by an AI agent")
    if SECTOR.get("headline"):
        st.markdown(f"<p class='lead'>{esc(SECTOR['headline'])}</p>", unsafe_allow_html=True)

    sc = scorecard()
    tot_rev = sc["Revenue (₹ cr)"].sum(min_count=1)
    yoy = [v for v in sc["Revenue YoY %"] if pd.notna(v)]
    mar = [v for v in sc["Op. margin %"] if pd.notna(v)]
    nifty = D["prices"][D["prices"]["company"] == "Nifty IT"]["close"] if not D["prices"].empty else pd.Series(dtype=float)
    nifty_ret = (nifty.iloc[-1] / nifty.iloc[0] - 1) * 100 if len(nifty) > 1 else None
    k = st.columns(5)
    kpi(k[0], "Results out", f"{len(reported)}/{len(ORDER)}", f"for {target_q}")
    kpi(k[1], "Combined quarterly revenue", inr_cr(tot_rev), "latest quarter in data")
    kpi(k[2], "Median revenue growth", pct(statistics.median(yoy)) if yoy else "—", "year on year, ₹ reported")
    kpi(k[3], "Median operating margin", pct(statistics.median(mar), False) if mar else "—", "latest quarter")
    kpi(k[4], "Nifty IT, 1 year", pct(nifty_ret), "share-price index")

    def chip(n):
        f = FIL.get(n) or {}
        if n in reported:
            tag = f"<span class='pos'>{esc(target_q)} out</span>"
            if (INS.get(n) or {}).get("official"):
                tag += " <span class='sub'>✓ filed</span>"
        else:
            due = f.get("next_results_date")
            tag = "<span class='na'>awaiting" + (f" · due {esc(pd.Timestamp(due).strftime('%d %b'))}" if due else "") + "</span>"
        return f"<div class='chip'><b>{esc(n)}</b> · {tag}</div>"
    chips = "".join(chip(n) for n in ORDER)
    st.markdown(f"<div class='chips' style='margin-top:14px'>{chips}</div>", unsafe_allow_html=True)

    st.subheader("Scorecard")
    st.caption("Click a column to sort. Revenue, margins and profit come from Yahoo Finance, or from the company's "
               "stock-exchange filing when Yahoo hasn't caught up yet (marked '(filing)'). CC growth, deal wins, "
               "guidance and mood are read by the AI from the filing and the news (blank = not found).")
    show_table(sc, column_config=SC_CONFIG)

    c1, c2 = st.columns([1.15, 1])
    with c1:
        d = sc.dropna(subset=["Op. margin %"]).copy()
        d["x"] = d["Revenue YoY %"].fillna(d["Revenue QoQ %"])
        d = d.dropna(subset=["x"])
        size = d["Market cap (₹ cr)"].fillna(d["Market cap (₹ cr)"].median() if d["Market cap (₹ cr)"].notna().any() else 1)
        fig = go.Figure(go.Scatter(
            x=d["x"], y=d["Op. margin %"], mode="markers+text", text=d["Company"], textposition="top center",
            marker=dict(size=size, sizemode="area", sizeref=2.0 * max(size.max(), 1) / (55 ** 2), sizemin=8,
                        color=[COLOR.get(n, ACCENT) for n in d["Company"]], opacity=0.8, line=dict(color="white", width=1)),
            customdata=d[["Market cap (₹ cr)"]],
            hovertemplate="<b>%{text}</b><br>Growth %{x:+.1f}%<br>Margin %{y:.1f}%<br>Mcap ₹%{customdata[0]:,.0f} cr<extra></extra>"))
        fig.update_xaxes(title="Revenue growth, year on year (%)", ticksuffix="%")
        fig.update_yaxes(title="Operating margin (%)", ticksuffix="%")
        show_chart(style(fig, 420, "Growth vs margin (bubble = market cap)", legend=False))
    with c2:
        d = sc.dropna(subset=["Revenue (₹ cr)"]).sort_values("Revenue (₹ cr)")
        fig = go.Figure(go.Bar(x=d["Revenue (₹ cr)"], y=d["Company"], orientation="h",
                               marker_color=[COLOR.get(n, ACCENT) for n in d["Company"]],
                               text=[inr_cr(v) for v in d["Revenue (₹ cr)"]], textposition="outside", cliponaxis=False,
                               hovertemplate="%{y}: ₹%{x:,.0f} cr<extra></extra>"))
        fig.update_xaxes(showticklabels=False)
        show_chart(style(fig, 420, "Quarterly revenue, latest quarter", legend=False))

    if SECTOR.get("themes"):
        st.subheader("This quarter's big themes")
        cols = st.columns(min(3, len(SECTOR["themes"])))
        for i, t in enumerate(SECTOR["themes"][:6]):
            cols[i % len(cols)].markdown(
                f"<div class='card'><h4>{esc(t.get('title'))}</h4><p>{esc(t.get('detail'))}</p>"
                f"<p class='sub'>{esc(', '.join(t.get('companies') or []))}</p></div>", unsafe_allow_html=True)

elif page == "Sector view":
    page_header(f"Sector view · {target_q}", "Written by the AI agent from all company results. Check key points against the sources.")
    if not SECTOR:
        st.info("The sector view appears after the agent has analysed at least one company's results.")
    else:
        st.markdown(f"<div class='callout'><b>{esc(SECTOR.get('headline'))}</b><br>{esc(SECTOR.get('summary'))}</div>",
                    unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### Leading this quarter")
            for x in SECTOR.get("leaders") or []:
                st.markdown(f"<div class='card'><h4>{esc(x.get('company'))}<span class='pill pos'>leader</span></h4>"
                            f"<p>{esc(x.get('why'))}</p></div>", unsafe_allow_html=True)
        with c2:
            st.markdown("#### Under pressure")
            for x in SECTOR.get("laggards") or []:
                st.markdown(f"<div class='card'><h4>{esc(x.get('company'))}<span class='pill neg'>lagging</span></h4>"
                            f"<p>{esc(x.get('why'))}</p></div>", unsafe_allow_html=True)
        st.markdown("#### Themes")
        for t in SECTOR.get("themes") or []:
            st.markdown(f"<div class='card'><h4>{esc(t.get('title'))}</h4><p>{esc(t.get('detail'))}</p>"
                        f"<p class='sub'>{esc(', '.join(t.get('companies') or []))}</p></div>", unsafe_allow_html=True)
        if SECTOR.get("watch_next"):
            st.markdown("#### What to watch next quarter")
            st.markdown("".join(f"- {esc(w)}\n" for w in SECTOR["watch_next"]))

    st.markdown("#### Guidance and mood by company")
    rows = []
    for n in ORDER:
        ins = INS.get(n) or {}
        rows.append({"Company": n, "Quarter": ins.get("quarter"), "Headline": ins.get("headline"),
                     "Guidance": ins.get("guidance"), "Change": ins.get("guidance_change"), "Mood": ins.get("sentiment")})
    show_table(pd.DataFrame(rows), column_config={"Headline": st.column_config.TextColumn(width="large"),
                                                  "Guidance": st.column_config.TextColumn(width="large")})

elif page == "Company deep-dive":
    name = st.selectbox("Company", ORDER, format_func=lambda n: NAMES.get(n, n))
    ins = INS.get(name) or {}
    found = ins.get("results_found")
    tick = mkt.loc[name, "ticker"] if name in mkt.index else ""
    page_header(NAMES.get(name, name), f"{tick} · AI analysis for {ins.get('quarter') or '—'}"
                + (f" · {ins.get('quarter')} shown while {ins['awaiting']} results are awaited" if ins.get("awaiting") else ""))
    fil = FIL.get(name) or {}
    if ins.get("filing"):
        g = ins["filing"]
        extra = f" · <a href='{esc(g['press_url'])}' target='_blank'>press release</a>" if g.get("press_url") else ""
        st.markdown(f"<p class='sub'>📄 Official results filed on {esc(g.get('exchange'))} at "
                    f"{esc((g.get('filed') or '').replace('T', ' '))} IST · "
                    f"<a href='{esc(g.get('url'))}' target='_blank'>results filing</a>{extra}</p>", unsafe_allow_html=True)
    elif fil.get("next_results_date"):
        st.markdown(f"<p class='sub'>🗓️ Next results board meeting: "
                    f"{esc(pd.Timestamp(fil['next_results_date']).strftime('%d %b %Y'))} (from the stock-exchange notice)</p>",
                    unsafe_allow_html=True)
    if ins.get("headline"):
        st.markdown(f"<div class='callout'>{esc(ins['headline'])} &nbsp;{pill(ins.get('sentiment'))}"
                    f"<br><span class='sub'>{esc(ins.get('sentiment_reason'))}</span></div>", unsafe_allow_html=True)

    def best(ai_key, yahoo_col, fmt):
        v = m_ai(name, ai_key) if ai_key else None
        if v is not None:
            return fmt(v), "from results news"
        v = latest_val(name, yahoo_col) if yahoo_col else None
        return (fmt(v), "Yahoo Finance") if v is not None else ("—", "not found")

    tiles = [
        ("Revenue", *best("revenue_inr_cr", "revenue", inr_cr)),
        ("Revenue growth YoY", *best("revenue_growth_yoy_pct", "rev_yoy", pct)),
        ("CC growth YoY", *best("cc_growth_yoy_pct", None, pct)),
        ("Operating margin", *best("operating_margin_pct", "op_margin", lambda v: pct(v, False))),
        ("Net profit", *best("net_profit_inr_cr", "net_income", inr_cr)),
        ("Deal wins", *best("deal_wins_usd_bn", None, lambda v: f"${v:,.2f} bn")),
        ("Headcount", *best("headcount", None, lambda v: f"{v:,.0f}")),
        ("Attrition", *best("attrition_pct", None, lambda v: pct(v, False))),
    ]
    for row in (tiles[:4], tiles[4:]):
        cols = st.columns(4)
        for c, (lab, val, note) in zip(cols, row):
            kpi(c, lab, val, note)
        st.write("")

    c1, c2 = st.columns(2)
    with c1:
        w = wide[wide["company"] == name] if not wide.empty else pd.DataFrame()
        if not w.empty:
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            fig.add_trace(go.Bar(x=w["quarter"], y=w["revenue"], name="Revenue (₹ cr)", marker_color=COLOR.get(name, ACCENT),
                                 hovertemplate="%{x}: ₹%{y:,.0f} cr<extra></extra>"), secondary_y=False)
            fig.add_trace(go.Scatter(x=w["quarter"], y=w["op_margin"], name="Operating margin %", mode="lines+markers",
                                     line=dict(color=INK, width=2.5), hovertemplate="%{x}: %{y:.1f}%<extra></extra>"),
                          secondary_y=True)
            fig.update_yaxes(title_text="₹ crore", secondary_y=False)
            fig.update_yaxes(title_text="Margin %", ticksuffix="%", secondary_y=True, showgrid=False)
            show_chart(style(fig, 360, "Revenue and operating margin by quarter"))
    with c2:
        p = D["prices"]
        if not p.empty:
            p = p[p["company"].isin([name, "Nifty IT"])].copy()
            fig = go.Figure()
            for n2, g in p.groupby("company"):
                g = g.sort_values("date")
                fig.add_trace(go.Scatter(x=g["date"], y=g["close"] / g["close"].iloc[0] * 100, name=n2, mode="lines",
                                         line=dict(color=COLOR.get(n2, ACCENT), width=2.2 if n2 == name else 1.5,
                                                   dash="solid" if n2 == name else "dot"),
                                         hovertemplate=f"{n2} %{{x}}: %{{y:.1f}}<extra></extra>"))
            show_chart(style(fig, 360, "Share price vs Nifty IT (1 year, start = 100)"))

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("#### Highlights")
        st.markdown("".join(f"- {esc(h)}\n" for h in ins.get("highlights") or []) or "_None found yet._")
        st.markdown("#### Guidance")
        st.markdown(f"<div class='card'><h4>Outlook {pill(ins.get('guidance_change'))}</h4>"
                    f"<p>{esc(ins.get('guidance') or 'Not mentioned in the news found.')}</p></div>", unsafe_allow_html=True)
        if ins.get("management_view"):
            st.markdown(f"<div class='card'><h4>Management view</h4><p>{esc(ins['management_view'])}</p></div>",
                        unsafe_allow_html=True)
    with c2:
        st.markdown("#### Risks")
        st.markdown("".join(f"- {esc(h)}\n" for h in ins.get("risks") or []) or "_None found yet._")
        if ins.get("ai_signals"):
            st.markdown(f"<div class='card'><h4>AI business</h4><p>{esc(ins['ai_signals'])}</p></div>", unsafe_allow_html=True)
        if ins.get("verticals"):
            st.markdown("#### Industry verticals")
            show_table(pd.DataFrame(ins["verticals"]).rename(columns={"name": "Vertical", "note": "What was said"}))
    if ins.get("megep_mentions"):
        st.markdown("#### Media, gaming, education & publishing mentions")
        show_table(pd.DataFrame(ins["megep_mentions"]).rename(columns={"domain": "Domain", "note": "What was said"}))
    if ins.get("unverified_dropped"):
        st.caption("Removed because the number could not be found in any source: " + ", ".join(ins["unverified_dropped"]))

    st.markdown("#### Sources the AI used")
    src = ins.get("sources") or []
    st.markdown("<div class='news'>" + "".join(
        f"<div>{'📄 ' if s.get('official') else ''}<a href='{esc(s.get('link'))}' target='_blank'>{esc(s.get('title'))}</a><br>"
        f"<span>{esc(s.get('source'))} · {esc((s.get('published') or '')[:10])}</span></div>" for s in src) + "</div>"
        if src else "<p class='sub'>No sources yet.</p>", unsafe_allow_html=True)
    with st.expander("All recent news for this company"):
        items = D["news"].get(name, [])[:25]
        st.markdown("<div class='news'>" + "".join(
            f"<div><a href='{esc(i.get('link'))}' target='_blank'>{esc(i.get('title'))}</a><br>"
            f"<span>{esc(i.get('source'))} · {esc((i.get('published') or '')[:10])}</span></div>" for i in items) + "</div>",
            unsafe_allow_html=True)

elif page == "Financial trends":
    page_header("Financial trends", "Quarterly figures from Yahoo Finance, ₹ crore. History builds up every quarter the agent runs.")
    if wide.empty:
        st.info("No financial data yet.")
    else:
        pick = st.multiselect("Companies", ORDER, default=ORDER)
        mode = st.radio("Show revenue as", ["₹ crore", "Indexed (first quarter = 100)"], horizontal=True)
        w = wide[wide["company"].isin(pick)].copy()
        qs = sorted(w["quarter"].unique(), key=quarter_key)

        def lines(col, title, suffix="", index=False):
            fig = go.Figure()
            for n in pick:
                g = w[w["company"] == n].sort_values("period_end")
                y = g[col]
                if index and len(y.dropna()):
                    y = y / y.dropna().iloc[0] * 100
                fig.add_trace(go.Scatter(x=g["quarter"], y=y, name=n, mode="lines+markers",
                                         line=dict(color=COLOR.get(n), width=2.2), marker=dict(size=6),
                                         hovertemplate=f"{n} · %{{x}}: %{{y:,.1f}}{suffix}<extra></extra>"))
            fig.update_xaxes(categoryorder="array", categoryarray=qs)
            if suffix:
                fig.update_yaxes(ticksuffix=suffix)
            return style(fig, 400, title)

        show_chart(lines("revenue", "Revenue" + (" (indexed)" if mode != "₹ crore" else " (₹ crore)"), index=mode != "₹ crore"))
        c1, c2 = st.columns(2)
        with c1:
            show_chart(lines("op_margin", "Operating margin", "%"))
        with c2:
            show_chart(lines("net_margin", "Net profit margin", "%"))

        hm = w.pivot_table(index="company", columns="quarter", values="rev_qoq").reindex(columns=qs)
        hm = hm.reindex([n for n in pick if n in hm.index]).dropna(axis=1, how="all")
        if not hm.empty:
            fig = go.Figure(go.Heatmap(z=hm.values, x=list(hm.columns), y=list(hm.index), colorscale=[[0, "#D93025"], [0.5, "#F8F9FA"], [1, "#0F9D58"]],
                                       zmid=0, text=[[pct(v) for v in r] for r in hm.values], texttemplate="%{text}",
                                       hovertemplate="%{y} · %{x}: %{z:+.1f}%<extra></extra>", colorbar=dict(title="QoQ %")))
            show_chart(style(fig, 80 + 34 * len(hm), "Revenue growth vs previous quarter (₹ reported)", legend=False))

elif page == "Share price & valuation":
    page_header("Share price & valuation", "Daily closing prices from Yahoo Finance. P/E = market cap ÷ last four quarters' net profit.")
    p = D["prices"]
    if p.empty:
        st.info("No price data yet.")
    else:
        fig = go.Figure()
        for n in ORDER + ["Nifty IT"]:
            g = p[p["company"] == n].sort_values("date")
            if g.empty:
                continue
            fig.add_trace(go.Scatter(x=g["date"], y=g["close"] / g["close"].iloc[0] * 100, name=n, mode="lines",
                                     line=dict(color=COLOR.get(n), width=1.4 if n == "Nifty IT" else 1.8,
                                               dash="dot" if n == "Nifty IT" else "solid"),
                                     hovertemplate=f"{n} %{{x}}: %{{y:.1f}}<extra></extra>"))
        fig.add_hline(y=100, line=dict(color="#C9CED6", width=1, dash="dash"))
        show_chart(style(fig, 440, "One year of share prices (start = 100)"))

        m = D["market"].copy()
        if not m.empty:
            c1, c2 = st.columns(2)
            with c1:
                d = m.melt(id_vars="company", value_vars=["return_1m", "return_3m", "return_1y"], var_name="period", value_name="ret")
                d["period"] = d["period"].map({"return_1m": "1 month", "return_3m": "3 months", "return_1y": "1 year"})
                fig = go.Figure()
                for per, col in zip(["1 month", "3 months", "1 year"], ["#A5B4FC", "#5C7CFA", "#2F5BEA"]):
                    g = d[d["period"] == per]
                    fig.add_trace(go.Bar(x=g["company"], y=g["ret"], name=per, marker_color=col,
                                         hovertemplate="%{x}: %{y:+.1f}%<extra>" + per + "</extra>"))
                fig.update_yaxes(ticksuffix="%")
                show_chart(style(fig, 400, "Share-price returns"))
            with c2:
                d = m.dropna(subset=["market_cap_cr"]).sort_values("market_cap_cr")
                fig = go.Figure(go.Bar(x=d["market_cap_cr"], y=d["company"], orientation="h",
                                       marker_color=[COLOR.get(n, ACCENT) for n in d["company"]],
                                       text=[inr_cr(v) for v in d["market_cap_cr"]], textposition="outside", cliponaxis=False,
                                       hovertemplate="%{y}: ₹%{x:,.0f} cr<extra></extra>"))
                fig.update_xaxes(showticklabels=False)
                show_chart(style(fig, 400, "Market value", legend=False))
            show_table(m[["company", "price", "price_date", "market_cap_cr", "pe_ttm", "return_1m", "return_3m", "return_1y",
                          "high_52w", "low_52w"]].rename(columns={
                "company": "Company", "price": "Price (₹)", "price_date": "As of", "market_cap_cr": "Market cap (₹ cr)",
                "pe_ttm": "P/E", "return_1m": "1M %", "return_3m": "3M %", "return_1y": "1Y %",
                "high_52w": "52-wk high", "low_52w": "52-wk low"}))

elif page == "Media · Gaming · EdTech · Publishing":
    page_header("Media, gaming, education & publishing",
                "What the companies and the AI's sector view say about these client industries.")
    outlook = SECTOR.get("domain_outlook") or []
    if outlook:
        cols = st.columns(3)
        for i, o in enumerate(outlook):
            cols[i % 3].markdown(f"<div class='card'><h4>{esc(o.get('domain'))}{pill(o.get('signal'))}</h4>"
                                 f"<p>{esc(o.get('note'))}</p></div>", unsafe_allow_html=True)
    rows = []
    for n in ORDER:
        for mtn in (INS.get(n) or {}).get("megep_mentions") or []:
            rows.append({"Domain": mtn.get("domain"), "Company": n, "What was said": mtn.get("note"),
                         "Quarter": (INS.get(n) or {}).get("quarter")})
    st.markdown("#### Every mention found this quarter")
    if rows:
        df = pd.DataFrame(rows).sort_values(["Domain", "Company"])
        dom = st.multiselect("Domain", sorted(df["Domain"].dropna().unique()), default=sorted(df["Domain"].dropna().unique()))
        show_table(df[df["Domain"].isin(dom)], column_config={"What was said": st.column_config.TextColumn(width="large")})
        cnt = df.groupby("Domain").size().sort_values()
        fig = go.Figure(go.Bar(x=cnt.values, y=cnt.index, orientation="h", marker_color=ACCENT,
                               hovertemplate="%{y}: %{x} mentions<extra></extra>"))
        show_chart(style(fig, 80 + 40 * len(cnt), "Mentions by domain", legend=False))
    else:
        st.info("No mentions yet. They appear once results are analysed.")
    st.caption("Indian IT companies rarely report these industries separately; most sit inside 'Communications, "
               "Media & Technology' style verticals. Mentions come from news coverage of results.")

elif page == "News":
    page_header("News", "Latest coverage per company from Google News and Bing News.")
    rows = []
    for n, items in D["news"].items():
        for i in items:
            rows.append({"Date": (i.get("published") or "")[:10], "Company": n, "Headline": i.get("title"),
                         "Source": i.get("source"), "Link": i.get("link")})
    if not rows:
        st.info("No news yet.")
    else:
        df = pd.DataFrame(rows).sort_values("Date", ascending=False)
        c1, c2 = st.columns([1, 1])
        who = c1.multiselect("Company", ORDER, default=[])
        q = c2.text_input("Search headlines", "")
        if who:
            df = df[df["Company"].isin(who)]
        if q:
            df = df[df["Headline"].str.contains(q, case=False, na=False)]
        show_table(df, column_config={"Headline": st.column_config.TextColumn(width="large"),
                                      "Link": st.column_config.LinkColumn("Open", display_text="open")})

else:
    page_header("About & data")
    st.markdown("""
**How it works.** A free AI agent runs several times a day on GitHub. It (1) downloads share prices and quarterly
financials from Yahoo Finance, (2) searches Google News and Bing News for each company, including Bloomberg and Reuters
headlines, (3) checks the stock exchange (BSE, with NSE as backup) for the company's official results filing and press
release, the fastest and most reliable source, (4) when results are out, asks an open AI model to read the filing and
the coverage and extract the key numbers, guidance, highlights, risks and mentions of media, gaming, education and
publishing clients, searching again when facts are missing, (5) deletes any number it cannot find in a source, and
(6) writes a sector view. A company only counts as "results out" once its results are filed on the exchange.

**Read with care.** Reported financials come from Yahoo Finance and can lag company releases by a few days; until it catches up, the scorecard uses the numbers
from the company's exchange filing (marked "(filing)").
AI-extracted figures come from news headlines and articles: check important numbers against the company's own
fact sheet before using them. Revenue growth here is in reported rupees unless labelled CC (constant currency).
This is not investment advice.
""")
    st.markdown("#### Data files")
    st.markdown("All in the `data` folder: `financials.csv` (one row per company, quarter and metric — ready for "
                "Excel, Power BI or Tableau), `market.csv`, `prices.csv`, `news.json`, `filings.json`, `insights.json`, "
                "`sector.json`, `run_log.json`.")
    if D["runs"]:
        st.markdown("#### Recent agent runs")
        show_table(pd.DataFrame([{"Finished (UTC)": (r.get("finished") or "")[:16].replace("T", " "),
                                  "Quarter": r.get("quarter"), "AI calls": r.get("ai_calls"),
                                  "What happened": "; ".join(r.get("steps") or []),
                                  "Problems": "; ".join(r.get("errors") or [])[:300]} for r in D["runs"]]))
