"""One shared summary of everything the agent has saved, used by the static website copy,
the email digest, the PDF snapshot and the Telegram alerts. (The Streamlit app has its own.)"""
import csv
import json
import statistics
from datetime import datetime, timezone

from .overrides import apply as apply_fixes
from .overrides import read_rows
from .settings import DATA, ROOT

PALETTE = ["#2A78D6", "#EB6834", "#1BAF7A", "#6250D6", "#E87BA4",
           "#008300", "#E34948", "#C98500", "#0891B2", "#A8551F"]


def _json(name, default):
    p = DATA / name
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
    except (json.JSONDecodeError, OSError):
        return default


def _csv(name):
    p = DATA / name
    if not p.exists():
        return []
    with open(p, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def _f(v):
    try:
        x = float(v)
        return None if x != x else x
    except (TypeError, ValueError):
        return None


def quarter_key(q):
    try:
        return (int(str(q).split("FY")[1]), int(str(q)[1]))
    except (IndexError, ValueError):
        return (0, 0)


def inr_cr(v):
    if v is None:
        return "—"
    return f"₹{v / 1e5:,.2f} lakh cr" if abs(v) >= 1e5 else f"₹{v:,.0f} cr"


def pct(v, signed=True):
    if v is None:
        return "—"
    return f"{v:+.1f}%" if signed else f"{v:.1f}%"


def build():
    """Return a plain dict with everything the outputs need."""
    with open(ROOT / "companies.csv", encoding="utf-8-sig", newline="") as fh:
        comps = [r for r in csv.DictReader(fh) if (r.get("name") or "").strip()]
    order = [(c.get("short_name") or c["name"]).strip() for c in comps]
    names = {(c.get("short_name") or c["name"]).strip(): c["name"].strip() for c in comps}
    color = {n: PALETTE[i % len(PALETTE)] for i, n in enumerate(order)}

    fin = apply_fixes(_csv("financials.csv"), read_rows(DATA / "filed_financials.csv"), read_rows(DATA / "overrides.csv"))
    by = {}
    for r in fin:
        v = _f(r.get("value_inr_cr"))
        if v is None:
            continue
        by.setdefault(r["company"], {}).setdefault(str(r["period_end"])[:10], {"quarter": r.get("quarter")})[r["metric"]] = v

    ins = _json("insights.json", {})
    sector = _json("sector.json", {})
    filings = _json("filings.json", {})
    news = _json("news.json", {})
    runs = _json("run_log.json", [])
    market = {r["company"]: r for r in _csv("market.csv")}
    verticals = _csv("verticals.csv")
    target_q = sector.get("quarter") or max((i.get("quarter") for i in ins.values() if i), key=quarter_key, default="")

    rows, history = [], {}
    for n in order:
        q = by.get(n, {})
        periods = sorted(q)
        history[n] = [{"quarter": q[p].get("quarter"), "revenue": q[p].get("revenue"),
                       "op_margin": (q[p]["operating_income"] / q[p]["revenue"] * 100)
                       if q[p].get("operating_income") is not None and q[p].get("revenue") else None}
                      for p in periods][-8:]
        last = q[periods[-1]] if periods else {}
        rev = last.get("revenue")

        def growth(k):
            if len(periods) > k and rev and q[periods[-1 - k]].get("revenue"):
                return round((rev / q[periods[-1 - k]]["revenue"] - 1) * 100, 1)
            return None

        i = ins.get(n) or {}
        m = i.get("metrics") or {} if i.get("results_found") else {}
        f = filings.get(n) or {}
        mk = market.get(n, {})
        row = {
            "company": n, "name": names.get(n, n), "color": color[n],
            "data_quarter": last.get("quarter"),
            "revenue": rev, "rev_qoq": growth(1), "rev_yoy": growth(4),
            "op_margin": round(last["operating_income"] / rev * 100, 1) if rev and last.get("operating_income") is not None else None,
            "net_profit": last.get("net_income"),
            "net_margin": round(last["net_income"] / rev * 100, 1) if rev and last.get("net_income") is not None else None,
            "cc_yoy": m.get("cc_growth_yoy_pct"), "deals": m.get("deal_wins_usd_bn"),
            "guidance": i.get("guidance_change") if i.get("results_found") else None,
            "mood": i.get("sentiment") if i.get("results_found") else None,
            "mcap": _f(mk.get("market_cap_cr")), "ret_1y": _f(mk.get("return_1y")), "pe": _f(mk.get("pe_ttm")),
            "reported": bool(i.get("quarter") == target_q and i.get("results_found")),
            "official": bool(i.get("official")),
            "filed_at": ((f.get("result") or {}).get("time") or "").replace("T", " ") if f.get("quarter") == target_q else "",
            "due": f.get("next_results_date"),
            "insight": i,
        }
        # Yahoo can lag: use the filed numbers until it catches up
        if row["reported"] and row["official"] and row["data_quarter"] != target_q and m.get("revenue_inr_cr"):
            prev = rev
            row.update({"data_quarter": f"{target_q} (filing)", "revenue": m["revenue_inr_cr"],
                        "rev_qoq": round((m["revenue_inr_cr"] / prev - 1) * 100, 1) if prev else None,
                        "rev_yoy": m.get("revenue_growth_yoy_pct"), "op_margin": m.get("operating_margin_pct"),
                        "net_profit": m.get("net_profit_inr_cr"),
                        "net_margin": round(m["net_profit_inr_cr"] / m["revenue_inr_cr"] * 100, 1) if m.get("net_profit_inr_cr") else None})
        rows.append(row)

    common = statistics.mode([r["data_quarter"].replace(" (filing)", "") for r in rows if r["data_quarter"]]) if any(r["data_quarter"] for r in rows) else None
    same = [r for r in rows if r["data_quarter"] and r["data_quarter"].replace(" (filing)", "") == common]
    yoy = [r["rev_yoy"] for r in rows if r["rev_yoy"] is not None]
    mar = [r["op_margin"] for r in rows if r["op_margin"] is not None]
    allnews = []
    for n, items in news.items():
        for it in items:
            allnews.append({**it, "company": n})
    allnews.sort(key=lambda x: x.get("published") or "", reverse=True)
    last_run = (runs[0].get("finished") or "")[:16].replace("T", " ") + " UTC" if runs else "—"
    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "last_run": last_run, "quarter": target_q, "rows": rows, "history": history, "color": color,
        "kpi": {
            "reported": sum(r["reported"] for r in rows), "total": len(rows),
            "combined_revenue": sum(r["revenue"] for r in same if r["revenue"]) if same else None,
            "combined_note": f"{len(same)} companies · {common or '—'}",
            "median_yoy": statistics.median(yoy) if yoy else None,
            "median_margin": statistics.median(mar) if mar else None,
        },
        "sector": sector, "verticals": verticals, "news": allnews[:40],
    }


def new_results(summary, state):
    """Companies whose results were filed/found and not yet announced on a channel."""
    seen = set(state.get("announced", []))
    out = []
    for r in summary["rows"]:
        if r["reported"]:
            key = f"{r['company']}|{summary['quarter']}"
            if key not in seen:
                out.append((key, r))
    return out
