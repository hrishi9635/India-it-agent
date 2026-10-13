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
GOOD, BAD, WARN, ACCENT = "#0CA30C", "#D03B3B", "#C98500", "#2A78D6"
PEER, BENCH, ACCENT_SOFT = "#C3C7CF", "#52514E", "#86B6EF"   # other companies, Nifty IT, secondary bars
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
    df = df.copy()
    for c in df.columns:  # show a dash, not "None", where a value wasn't found
        if df[c].dtype == object:
            df[c] = df[c].where(df[c].notna() & (df[c].astype(str) != "None"), "—")
    try:
        st.dataframe(df, width="stretch", hide_index=True, **kw)
    except Exception:  # older Streamlit versions
        st.dataframe(df, use_container_width=True, hide_index=True, **kw)


def focus_lines(fig, frame, xcol, ycol, focus, names, suffix="", fmt=",.1f"):
    """All companies as thin grey lines, the chosen one in blue on top, Nifty IT dotted. Direct labels at the end."""
    order = [n for n in names if n != focus] + ([focus] if focus in names else [])
    for n in order:
        g = frame[frame["_name"] == n]
        if g.empty:
            continue
        on, bench = n == focus, n == "Nifty IT"
        fig.add_trace(go.Scatter(
            x=g[xcol], y=g[ycol], name=n, mode="lines+markers" if on and len(g) < 30 else "lines",
            line=dict(color=ACCENT if on else (BENCH if bench else PEER), width=2.6 if on else (1.6 if bench else 1.2),
                      dash="dot" if bench else "solid"),
            marker=dict(size=8, color=ACCENT, line=dict(color="white", width=2)) if on else None,
            opacity=1 if (on or bench) else 0.85, showlegend=on or bench,
            hovertemplate=f"<b>{n}</b> · %{{x}}: %{{y:{fmt}}}{suffix}<extra></extra>"))
        if on or bench:
            last = g.dropna(subset=[ycol]).tail(1)
            if not last.empty:
                fig.add_annotation(x=last[xcol].iloc[0], y=last[ycol].iloc[0], text=f"<b>{n}</b>" if on else n,
                                   showarrow=False, xanchor="left", xshift=8, font=dict(color=INK if on else MUTED, size=12))
    return fig


def kpi(col, label, value, note=""):
    col.markdown(f"<div class='kpi'><div class='lab'>{esc(label)}</div><div class='big'>{esc(value)}</div>"
                 f"<div class='note'>{esc(note)}</div></div>", unsafe_allow_html=True)


# ---------------------------------------------------------------- data
def corrected(fin, *fixes):
    """Official numbers win over Yahoo: exchange-filing numbers, then hand-checked overrides (data/overrides.csv)."""
    parts = [d for d in (fin, *fixes) if d is not None and not d.empty and {"company", "period_end", "metric", "value_inr_cr"} <= set(d.columns)]
    if not parts:
        return fin
    allr = pd.concat(parts, ignore_index=True)
    allr = allr[~allr["company"].astype(str).str.startswith("#")]
    allr["value_inr_cr"] = pd.to_numeric(allr["value_inr_cr"], errors="coerce")
    allr["period_end"] = allr["period_end"].astype(str).str[:10]
    allr = allr.dropna(subset=["value_inr_cr"]).drop_duplicates(["company", "period_end", "metric"], keep="last")
    return allr.sort_values(["company", "period_end", "metric"]).reset_index(drop=True)


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

    def rc_from_header(name):
        """Hand-edited CSVs may have stray lines (e.g. '---') above the header; skip them."""
        p = DATA / name
        if not p.exists():
            return pd.DataFrame()
        lines = p.read_text(encoding="utf-8-sig").splitlines()
        start = next((i for i, l in enumerate(lines) if l.strip().lower().startswith("company,")), None)
        if start is None:
            return pd.DataFrame()
        import io
        return pd.read_csv(io.StringIO("\n".join(lines[start:])))

    def rc(name):
        p = DATA / name
        return pd.read_csv(p, encoding="utf-8-sig") if p.exists() and p.stat().st_size > 0 else pd.DataFrame()

    with open(ROOT / "companies.csv", encoding="utf-8-sig", newline="") as fh:
        comps = [r for r in csv.DictReader(fh) if (r.get("name") or "").strip()]
    return {
        "companies": comps, "fin": corrected(rc("financials.csv"), rc_from_header("filed_financials.csv"), rc_from_header("overrides.csv")), "market": rc("market.csv"), "prices": rc("prices.csv"),
        "insights": rj("insights.json", {}), "sector": rj("sector.json", {}), "news": rj("news.json", {}),
        "runs": rj("run_log.json", []), "filings": rj("filings.json", {}), "verticals": rc_from_header("verticals.csv"),
    }


D = load(stamp())
ORDER = [c["short_name"] or c["name"] for c in D["companies"]]
NAMES = {(c["short_name"] or c["name"]): c["name"] for c in D["companies"]}
COLOR = {n: PALETTE[i % len(PALETTE)] for i, n in enumerate(ORDER)}
COLOR["Nifty IT"] = BENCH
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
    if ORDER:
        st.progress(len(reported) / len(ORDER))
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
    common_q = sc["Data quarter"].dropna().astype(str).str.replace(" (filing)", "", regex=False).mode()
    common_q = common_q.iloc[0] if len(common_q) else None
    same_q = sc[sc["Data quarter"].astype(str).str.replace(" (filing)", "", regex=False) == str(common_q)]
    tot_rev = same_q["Revenue (₹ cr)"].sum(min_count=1)
    yoy = [v for v in sc["Revenue YoY %"] if pd.notna(v)]
    mar = [v for v in sc["Op. margin %"] if pd.notna(v)]
    nifty = D["prices"][D["prices"]["company"] == "Nifty IT"]["close"] if not D["prices"].empty else pd.Series(dtype=float)
    nifty_ret = (nifty.iloc[-1] / nifty.iloc[0] - 1) * 100 if len(nifty) > 1 else None
    k = st.columns(5)
    kpi(k[0], "Results out", f"{len(reported)}/{len(ORDER)}", f"for {target_q}")
    kpi(k[1], "Combined quarterly revenue", inr_cr(tot_rev), f"{len(same_q)} companies · {common_q or '—'}")
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
                        color=ACCENT, opacity=0.75, line=dict(color="white", width=2)),
            customdata=d[["Market cap (₹ cr)"]],
            hovertemplate="<b>%{text}</b><br>Growth %{x:+.1f}%<br>Margin %{y:.1f}%<br>Mcap ₹%{customdata[0]:,.0f} cr<extra></extra>"))
        fig.update_xaxes(title="Revenue growth, year on year (%)", ticksuffix="%")
        fig.update_yaxes(title="Operating margin (%)", ticksuffix="%")
        show_chart(style(fig, 420, "Growth vs margin (bubble = market cap)", legend=False))
    with c2:
        d = sc.dropna(subset=["Revenue (₹ cr)"]).sort_values("Revenue (₹ cr)")
        fig = go.Figure(go.Bar(x=d["Revenue (₹ cr)"], y=d["Company"], orientation="h",
                               marker=dict(color=ACCENT, cornerradius=4),
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

    SC = scorecard()
    rank_cols = {"revenue": "Revenue (₹ cr)", "rev_yoy": "Revenue YoY %", "op_margin": "Op. margin %", "net_income": "Net profit (₹ cr)"}

    def rank_note(yahoo_col):
        col = rank_cols.get(yahoo_col)
        if not col or col not in SC or name not in set(SC["Company"]):
            return ""
        vals = SC[["Company", col]].dropna()
        if name not in set(vals["Company"]) or len(vals) < 3:
            return ""
        r = int(vals[col].rank(ascending=False, method="min")[vals["Company"] == name].iloc[0])
        return f" · #{r} of {len(vals)}"

    def best(ai_key, yahoo_col, fmt):
        v = m_ai(name, ai_key) if ai_key else None
        src = "from the filing" if ins.get("official") else "from results news"
        if v is not None:
            return fmt(v), src + rank_note(yahoo_col)
        v = latest_val(name, yahoo_col) if yahoo_col else None
        return (fmt(v), "Yahoo Finance" + rank_note(yahoo_col)) if v is not None else ("—", "not found")

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

    w = wide[wide["company"] == name].tail(8) if not wide.empty else pd.DataFrame()
    c1, c2, c3 = st.columns(3)
    if not w.empty:
        with c1:  # revenue and margin as two charts: different units never share one chart
            last = len(w) - 1
            fig = go.Figure(go.Bar(x=w["quarter"], y=w["revenue"], marker=dict(color=[ACCENT if i == last else ACCENT_SOFT for i in range(len(w))], cornerradius=4),
                                   text=[inr_cr(v) if i == last else "" for i, v in enumerate(w["revenue"])], textposition="outside", cliponaxis=False,
                                   hovertemplate="%{x}: ₹%{y:,.0f} cr<extra></extra>"))
            show_chart(style(fig, 320, "Revenue by quarter (₹ crore)", legend=False))
        with c2:
            fig = go.Figure(go.Scatter(x=w["quarter"], y=w["op_margin"], mode="lines+markers+text",
                                       line=dict(color=ACCENT, width=2.5), marker=dict(size=8, color=ACCENT, line=dict(color="white", width=2)),
                                       text=[pct(v, False) if i in (0, len(w) - 1) else "" for i, v in enumerate(w["op_margin"])],
                                       textposition="top center", hovertemplate="%{x}: %{y:.1f}%<extra></extra>"))
            fig.update_yaxes(ticksuffix="%")
            show_chart(style(fig, 320, "Operating margin by quarter", legend=False))
    with c3:
        p = D["prices"]
        if not p.empty:
            p = p[p["company"].isin([name, "Nifty IT"])].copy().sort_values("date")
            p["idx"] = p.groupby("company")["close"].transform(lambda x: x / x.iloc[0] * 100)
            p["_name"] = p["company"]
            fig = focus_lines(go.Figure(), p, "date", "idx", name, [name, "Nifty IT"])
            fig.add_hline(y=100, line=dict(color=LINE, width=1, dash="dash"))
            show_chart(style(fig, 320, "Share price vs Nifty IT (1 year, start = 100)", legend=False))

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
    page_header("Financial trends", "Quarterly figures in ₹ crore: company filings and hand-checked results where available, "
                "Yahoo Finance otherwise. Pick a company to highlight it against its peers (grey).")
    if wide.empty:
        st.info("No financial data yet.")
    else:
        c1, c2 = st.columns([1, 1.4])
        focus = c1.selectbox("Highlight", ORDER, index=0, format_func=lambda n: NAMES.get(n, n))
        mode = c2.radio("Show revenue as", ["Indexed (first quarter = 100)", "₹ crore"], horizontal=True)
        pick = ORDER
        w = wide[wide["company"].isin(pick)].copy()
        w["_name"] = w["company"]
        qs = sorted(w["quarter"].unique(), key=quarter_key)

        def lines(col, title, suffix="", index=False):
            g = w.sort_values("period_end").copy()
            if index:
                g[col] = g.groupby("company")[col].transform(lambda y: y / y.dropna().iloc[0] * 100 if y.notna().any() else y)
            fig = focus_lines(go.Figure(), g, "quarter", col, focus, pick, suffix)
            fig.update_xaxes(categoryorder="array", categoryarray=qs)
            if suffix:
                fig.update_yaxes(ticksuffix=suffix)
            return style(fig, 400, title, legend=False)

        show_chart(lines("revenue", "Revenue" + (" (indexed)" if mode != "₹ crore" else " (₹ crore)"), index=mode != "₹ crore"))
        c1, c2 = st.columns(2)
        with c1:
            show_chart(lines("op_margin", "Operating margin", "%"))
        with c2:
            show_chart(lines("net_margin", "Net profit margin", "%"))

        hm = w.pivot_table(index="company", columns="quarter", values="rev_qoq").reindex(columns=qs)
        hm = hm.reindex([n for n in pick if n in hm.index]).dropna(axis=1, how="all")
        if not hm.empty:
            fig = go.Figure(go.Heatmap(z=hm.values, x=list(hm.columns), y=list(hm.index), colorscale=[[0, "#D03B3B"], [0.5, "#F0EFEC"], [1, "#2A78D6"]],
                                       zmid=0, text=[[pct(v) for v in r] for r in hm.values], texttemplate="%{text}",
                                       hovertemplate="%{y} · %{x}: %{z:+.1f}%<extra></extra>", colorbar=dict(title="QoQ %")))
            show_chart(style(fig, 80 + 34 * len(hm), "Revenue growth vs previous quarter (blue = grew, red = fell)", legend=False))

elif page == "Share price & valuation":
    page_header("Share price & valuation", "Daily closing prices from Yahoo Finance. P/E = market cap ÷ last four quarters' net profit.")
    p = D["prices"]
    if p.empty:
        st.info("No price data yet.")
    else:
        focus = st.selectbox("Highlight", ORDER, index=0, format_func=lambda n: NAMES.get(n, n), key="px_focus")
        pp = p.sort_values("date").copy()
        pp["idx"] = pp.groupby("company")["close"].transform(lambda x: x / x.iloc[0] * 100)
        pp["_name"] = pp["company"]
        fig = focus_lines(go.Figure(), pp, "date", "idx", focus, ORDER + ["Nifty IT"])
        fig.add_hline(y=100, line=dict(color=LINE, width=1, dash="dash"))
        show_chart(style(fig, 440, f"One year of share prices, start = 100 ({NAMES.get(focus, focus)} vs peers and Nifty IT)", legend=False))

        m = D["market"].copy()
        if not m.empty:
            c1, c2 = st.columns(2)
            with c1:
                per = st.radio("Return over", ["1 month", "3 months", "1 year"], index=2, horizontal=True)
                colname = {"1 month": "return_1m", "3 months": "return_3m", "1 year": "return_1y"}[per]
                d = m.dropna(subset=[colname]).sort_values(colname)
                fig = go.Figure(go.Bar(x=d[colname], y=d["company"], orientation="h",
                                       marker=dict(color=[ACCENT if v >= 0 else BAD for v in d[colname]], cornerradius=4),
                                       text=[pct(v) for v in d[colname]], textposition="outside", cliponaxis=False,
                                       hovertemplate="%{y}: %{x:+.1f}%<extra></extra>"))
                fig.update_xaxes(ticksuffix="%", zeroline=True, zerolinecolor=BENCH)
                show_chart(style(fig, 400, f"Share-price return, {per} (blue = up, red = down)", legend=False))
            with c2:
                d = m.dropna(subset=["market_cap_cr"]).sort_values("market_cap_cr")
                fig = go.Figure(go.Bar(x=d["market_cap_cr"], y=d["company"], orientation="h",
                                       marker=dict(color=ACCENT, cornerradius=4),
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
                "How Indian IT companies are doing with media, entertainment, gaming, education, publishing and telecom clients.")
    DOMAIN_WORDS = {
        "Media & broadcasting": ["media", "broadcast", "broadcaster", "news channel", "tv ", "television", "advertis"],
        "Entertainment & streaming": ["entertainment", "streaming", "studio", "film", "music", "ott", "sports network"],
        "Gaming": ["gaming", "game ", "games", "esports", "casino", "console"],
        "Education": ["education", "edtech", "university", "learning", "school", "skilling"],
        "Publishing": ["publishing", "publisher", "newspaper", "content"],
        "Telecom": ["telecom", "telco", "5g", "network operator", "communications"],
    }

    def tag(text):
        t = f" {str(text).lower()} "
        return [d for d, words in DOMAIN_WORDS.items() if any(w in t for w in words)]

    # 1. the AI's outlook per domain
    outlook = SECTOR.get("domain_outlook") or []
    st.markdown("#### Outlook by industry")
    if outlook:
        cols = st.columns(3)
        for i, o in enumerate(outlook):
            cols[i % 3].markdown(f"<div class='card'><h4>{esc(o.get('domain'))}{pill(o.get('signal'))}</h4>"
                                 f"<p>{esc(o.get('note'))}</p></div>", unsafe_allow_html=True)
    else:
        st.caption("The AI writes this once results are analysed for the quarter.")

    # 2. the media / communications segment each company reports, quarter by quarter
    st.markdown("#### Media & communications segment, as reported by each company")
    V = D["verticals"].copy() if not D["verticals"].empty else pd.DataFrame()
    if not V.empty:
        for col in ("revenue_share_pct", "growth_qoq_pct", "growth_yoy_pct", "growth_cc_yoy_pct"):
            V[col] = pd.to_numeric(V[col], errors="coerce")
        V["_k"] = V["quarter"].map(quarter_key)
        lastv = V.sort_values("_k").groupby("company").tail(1)
        lastv["growth"] = lastv["growth_cc_yoy_pct"].fillna(lastv["growth_yoy_pct"])
        c1, c2 = st.columns(2)
        with c1:
            d = lastv.dropna(subset=["growth"]).sort_values("growth")
            if not d.empty:
                fig = go.Figure(go.Bar(x=d["growth"], y=d["company"], orientation="h",
                                       marker=dict(color=[ACCENT if v >= 0 else BAD for v in d["growth"]], cornerradius=4),
                                       text=[pct(v) for v in d["growth"]], textposition="outside", cliponaxis=False,
                                       customdata=d[["vertical", "quarter"]],
                                       hovertemplate="<b>%{y}</b> · %{customdata[0]} (%{customdata[1]}): %{x:+.1f}%<extra></extra>"))
                fig.update_xaxes(ticksuffix="%", zeroline=True, zerolinecolor=BENCH)
                show_chart(style(fig, 80 + 42 * len(d), "Segment growth, year on year (constant currency where given)", legend=False))
        with c2:
            d = lastv.dropna(subset=["revenue_share_pct"]).sort_values("revenue_share_pct")
            if not d.empty:
                fig = go.Figure(go.Bar(x=d["revenue_share_pct"], y=d["company"], orientation="h",
                                       marker=dict(color=ACCENT, cornerradius=4),
                                       text=[pct(v, False) for v in d["revenue_share_pct"]], textposition="outside", cliponaxis=False,
                                       hovertemplate="%{y}: %{x:.1f}% of revenue<extra></extra>"))
                fig.update_xaxes(ticksuffix="%")
                show_chart(style(fig, 80 + 42 * len(d), "Segment's share of company revenue", legend=False))
        show_table(V.sort_values(["_k", "company"], ascending=[False, True])[
            ["company", "quarter", "vertical", "revenue_share_pct", "growth_qoq_pct", "growth_yoy_pct", "growth_cc_yoy_pct", "commentary", "source"]
        ].rename(columns={"company": "Company", "quarter": "Quarter", "vertical": "Segment", "revenue_share_pct": "Share of revenue %",
                          "growth_qoq_pct": "QoQ %", "growth_yoy_pct": "YoY %", "growth_cc_yoy_pct": "YoY CC %",
                          "commentary": "What was said", "source": "Source"}),
            column_config={"What was said": st.column_config.TextColumn(width="large")})
    else:
        st.caption("Filled in automatically as each company files its results and fact sheet.")
    with st.expander("Which segment we track for each company"):
        show_table(pd.DataFrame([{"Company": c["short_name"] or c["name"], "Segment that holds media, publishing, gaming & education clients":
                                  c.get("media_vertical") or "Not reported separately"} for c in D["companies"]]))
    vrows = []
    for n in ORDER:
        ins = INS.get(n) or {}
        for v in ins.get("verticals") or []:
            if tag(v.get("name")) or "communication" in str(v.get("name")).lower() or "hi-tech" in str(v.get("name")).lower():
                vrows.append({"Company": n, "Quarter": ins.get("quarter"), "Vertical": v.get("name"), "What was said": v.get("note")})
    if vrows:
        st.markdown("##### Other comments on these segments")
        show_table(pd.DataFrame(vrows), column_config={"What was said": st.column_config.TextColumn(width="large")})

    # 3. client and deal mentions the AI picked out of the results
    rows = []
    for n in ORDER:
        for mtn in (INS.get(n) or {}).get("megep_mentions") or []:
            rows.append({"Domain": mtn.get("domain"), "Company": n, "What was said": mtn.get("note"),
                         "Quarter": (INS.get(n) or {}).get("quarter")})
    st.markdown("#### Client and deal mentions in the results")
    if rows:
        df = pd.DataFrame(rows).sort_values(["Domain", "Company"])
        dom = st.multiselect("Domain", sorted(df["Domain"].dropna().unique()), default=sorted(df["Domain"].dropna().unique()))
        show_table(df[df["Domain"].isin(dom)], column_config={"What was said": st.column_config.TextColumn(width="large")})
    else:
        st.caption("None found in this quarter's results coverage yet.")

    # 4. news about these industries, found automatically in each company's coverage
    nrows = []
    for n, items in D["news"].items():
        for i in items:
            for d in tag(f"{i.get('title')} {i.get('snippet', '')}"):
                nrows.append({"Date": (i.get("published") or "")[:10], "Domain": d, "Company": n,
                              "Headline": i.get("title"), "Source": i.get("source"), "Link": i.get("link")})
    st.markdown("#### In the news")
    if nrows:
        nd = pd.DataFrame(nrows).drop_duplicates(["Headline", "Domain"]).sort_values("Date", ascending=False)
        c1, c2 = st.columns([1.4, 1])
        with c1:
            show_table(nd, column_config={"Headline": st.column_config.TextColumn(width="large"),
                                          "Link": st.column_config.LinkColumn("Open", display_text="open")})
        with c2:
            cnt = nd.groupby("Domain").size().sort_values()
            fig = go.Figure(go.Bar(x=cnt.values, y=cnt.index, orientation="h", marker_color=ACCENT,
                                   hovertemplate="%{y}: %{x} stories<extra></extra>"))
            show_chart(style(fig, 80 + 40 * len(cnt), "Stories by industry (last 30 days)", legend=False))
    else:
        st.info("No media, gaming, education, publishing or telecom stories in the latest news yet.")
    st.caption("Indian IT companies rarely report these industries separately; most sit inside 'Communications, "
               "Media & Technology' style verticals. Mentions come from results filings and news coverage.")

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
    dl = st.columns(4)
    for c, (label, fname) in zip(dl, [("Financials (CSV)", "financials.csv"), ("Market data (CSV)", "market.csv"),
                                      ("AI insights (JSON)", "insights.json"), ("Exchange filings (JSON)", "filings.json")]):
        f = DATA / fname
        if f.exists():
            try:
                c.download_button(f"⬇ {label}", f.read_bytes(), file_name=fname, width="stretch")
            except TypeError:  # older Streamlit versions
                c.download_button(f"⬇ {label}", f.read_bytes(), file_name=fname, use_container_width=True)
    if D["runs"]:
        st.markdown("#### Recent agent runs")
        show_table(pd.DataFrame([{"Finished (UTC)": (r.get("finished") or "")[:16].replace("T", " "),
                                  "Quarter": r.get("quarter"), "AI calls": r.get("ai_calls"),
                                  "What happened": "; ".join(r.get("steps") or []),
                                  "Problems": "; ".join(r.get("errors") or [])[:300]} for r in D["runs"]]))
