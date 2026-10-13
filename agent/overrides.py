"""Corrections on top of Yahoo Finance's quarterly numbers.

Yahoo is free but imperfect: it sometimes skips a quarter, and for some companies its
"operating income" is not the EBIT the company reports (HCLTech is the main case).
Two files fix that, and both win over Yahoo:

  data/filed_financials.csv  written by the agent: the numbers it read from each company's
                             official stock-exchange filing (one row per quarter and metric)
  data/overrides.csv         written by you: hand-checked numbers from the company's own
                             results release. These win over everything.

Both files use the same columns as financials.csv:
  company, period_end, quarter, metric, value_inr_cr, source
metric is one of: revenue, operating_income, net_income
"""
import csv
from pathlib import Path

FIELDS = ["company", "period_end", "quarter", "metric", "value_inr_cr", "source"]


def read_rows(path):
    p = Path(path)
    if not p.exists():
        return []
    lines = p.read_text(encoding="utf-8-sig").splitlines()
    start = next((i for i, l in enumerate(lines) if l.strip().lower().startswith("company,")), None)
    if start is None:
        return []
    if True:
        rows = []
        for r in csv.DictReader(lines[start:]):
            if (r.get("company") or "").startswith("#") or not r.get("value_inr_cr"):
                continue
            try:
                float(r["value_inr_cr"])
            except ValueError:
                continue
            rows.append({k: (r.get(k) or "").strip() for k in FIELDS})
    return rows


def apply(rows, *correction_sets):
    """Replace or add rows, keyed by (company, period_end, metric). Later sets win."""
    keep = {(r["company"], str(r["period_end"]), r["metric"]): dict(r) for r in rows}
    for cs in correction_sets:
        for r in cs:
            k = (r["company"], str(r["period_end"]), r["metric"])
            old = keep.get(k, {})
            keep[k] = {**old, **r, "ticker": old.get("ticker", r.get("ticker", ""))}
    return sorted(keep.values(), key=lambda r: (r["company"], str(r["period_end"]), r["metric"]))


def rows_from_filing(company, period_end, quarter, metrics, exchange="BSE"):
    """Turn the AI's reading of an official filing into financial rows."""
    out = []
    rev = metrics.get("revenue_inr_cr")
    vals = {"revenue": rev, "net_income": metrics.get("net_profit_inr_cr")}
    if rev and metrics.get("operating_margin_pct") is not None:
        vals["operating_income"] = round(rev * metrics["operating_margin_pct"] / 100, 1)
    for m, v in vals.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            out.append({"company": company, "period_end": period_end, "quarter": quarter, "metric": m,
                        "value_inr_cr": str(v), "source": f"{exchange} results filing (read by the agent)"})
    return out
