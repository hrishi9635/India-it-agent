"""Free market data and quarterly financials from Yahoo Finance (via the open-source yfinance library)."""
import time

import pandas as pd

from .quarters import label, quarter_end_month

METRICS = {
    "revenue": ["Total Revenue", "Operating Revenue"],
    "operating_income": ["Operating Income", "EBIT"],
    "net_income": ["Net Income", "Net Income Common Stockholders",
                   "Net Income From Continuing Operation Net Minority Interest"],
    "ebitda": ["EBITDA", "Normalized EBITDA"],
}


def _retry(fn, tries=3, wait=8):
    """Yahoo sometimes says 'too many requests'. Wait and try again."""
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(wait * (i + 1))
    raise last


def resolve_ticker(yf, tickers):
    for t in tickers:
        try:
            h = _retry(lambda: yf.Ticker(t).history(period="1mo"), tries=2, wait=4)
            if h is not None and not h.empty:
                return t
        except Exception:  # noqa: BLE001
            continue
    return None


def usd_inr(yf):
    """Dollar-rupee rate: (latest rate, two years of daily rates)."""
    try:
        h = yf.Ticker("INR=X").history(period="2y")["Close"].dropna()
        h.index = pd.to_datetime(h.index).tz_localize(None)
        return float(h.iloc[-1]), h
    except Exception:  # noqa: BLE001
        return None, None


def quarter_rate(fx_hist, qe, fallback):
    """Average dollar-rupee rate during the quarter (companies convert at the quarter's rate)."""
    try:
        q = fx_hist[(fx_hist.index > qe - pd.DateOffset(months=3)) & (fx_hist.index <= qe)]
        return float(q.mean()) if len(q) > 20 else fallback
    except Exception:  # noqa: BLE001
        return fallback


def market_cap(tk):
    """Market value in rupees (Yahoo gives it in the listing currency, ₹ for .NS shares)."""
    try:
        fi = tk.fast_info
        for key in ("market_cap", "marketCap"):
            try:
                v = getattr(fi, key) if hasattr(fi, key) else fi[key]
            except Exception:  # noqa: BLE001
                v = None
            if v:
                return float(v)
    except Exception:  # noqa: BLE001
        pass
    return None


def pick_conversion(stmt, label_currency, fx, mcap):
    """Decide whether the statement numbers are already in rupees.

    Yahoo's currency label is sometimes wrong (e.g. it says USD while the numbers are in ₹).
    We test both readings against the company's market value: an IT company is normally worth
    0.3x to 40x its yearly revenue. Whichever reading gives a sensible ratio wins."""
    rev = None
    for n in METRICS["revenue"]:
        if n in stmt.index:
            rev = pd.to_numeric(stmt.loc[n], errors="coerce").dropna()
            break
    if rev is None or rev.empty or not mcap or not fx:
        # no way to check: Indian listings report in rupees, so trust that
        return 1.0, "INR"
    yearly = float(rev.iloc[:4].mean()) * 4
    if yearly <= 0:
        return 1.0, "INR"

    def sensible(ratio):
        return 0.3 <= ratio <= 40

    as_inr, as_usd = mcap / yearly, mcap / (yearly * fx)
    if label_currency == "INR":
        if sensible(as_inr) or not sensible(as_usd):
            return 1.0, "INR"
        return fx, "USD (label said INR; checked)"
    if sensible(as_usd) and not sensible(as_inr):
        return fx, f"{label_currency} converted"
    return 1.0, f"INR (label said {label_currency}; checked)"


def quarterly_rows(yf, company, ticker, fx, fx_hist=None):
    """One row per quarter per metric, in ₹ crore."""
    tk = yf.Ticker(ticker)
    stmt = None
    for attr in ("quarterly_income_stmt", "quarterly_financials"):
        try:
            stmt = _retry(lambda: getattr(tk, attr))
            if stmt is not None and not stmt.empty:
                break
        except Exception:  # noqa: BLE001
            stmt = None
    if stmt is None or stmt.empty:
        return []
    label_currency = "INR"
    try:
        label_currency = (tk.get_info() or {}).get("financialCurrency") or "INR"
    except Exception:  # noqa: BLE001
        pass
    to_inr, note = pick_conversion(stmt, label_currency, fx, market_cap(tk))
    rows = []
    for col in stmt.columns:
        ts = pd.Timestamp(col)
        qe = ts.replace(month=quarter_end_month(ts.month), day=1) + pd.offsets.MonthEnd(0)
        rate = 1.0 if to_inr == 1.0 else quarter_rate(fx_hist, qe.tz_localize(None) if qe.tzinfo else qe, to_inr)
        for metric, names in METRICS.items():
            val = None
            for n in names:
                if n in stmt.index:
                    v = stmt.loc[n, col]
                    if pd.notna(v):
                        val = float(v)
                        break
            if val is None:
                continue
            rows.append({
                "company": company["short"],
                "ticker": ticker,
                "period_end": qe.date().isoformat(),
                "quarter": label(qe.date()),
                "metric": metric,
                "value_inr_cr": round(val * rate / 1e7, 2),
                "source": "Yahoo Finance" + ("" if note == "INR" else f" ({note})"),
            })
    return rows


def market_snapshot(yf, company, ticker, fin_rows):
    tk = yf.Ticker(ticker)
    hist = _retry(lambda: tk.history(period="2y"))
    close_all = hist["Close"].dropna()
    close = close_all[close_all.index >= close_all.index[-1] - pd.Timedelta(days=365)] if not close_all.empty else close_all
    out = {"company": company["short"], "name": company["name"], "ticker": ticker}
    if close.empty:
        return out, []
    last = float(close.iloc[-1])

    def ret(days):
        cut = close.index[-1] - pd.Timedelta(days=days)
        past = close_all[close_all.index <= cut]
        return round((last / float(past.iloc[-1]) - 1) * 100, 2) if not past.empty else None

    mcap = market_cap(tk)
    ni = sorted([r for r in fin_rows if r["metric"] == "net_income"], key=lambda r: r["period_end"])
    ttm = sum(r["value_inr_cr"] for r in ni[-4:]) if len(ni) >= 4 else None
    mcap_cr = round(float(mcap) / 1e7, 0) if mcap else None
    out.update({
        "price": round(last, 2),
        "price_date": close.index[-1].date().isoformat(),
        "market_cap_cr": mcap_cr,
        "return_1m": ret(30), "return_3m": ret(91), "return_1y": ret(364),
        "high_52w": round(float(close.max()), 2), "low_52w": round(float(close.min()), 2),
        "pe_ttm": round(mcap_cr / ttm, 1) if mcap_cr and ttm and ttm > 0 else None,
    })
    prices = [{"date": d.date().isoformat(), "company": company["short"], "close": round(float(v), 2)}
              for d, v in close.items()]
    return out, prices


def benchmark_prices(yf, ticker, name="Nifty IT"):
    try:
        close = _retry(lambda: yf.Ticker(ticker).history(period="1y"))["Close"].dropna()
        close = close[close.index >= close.index[-1] - pd.Timedelta(days=365)]
        return [{"date": d.date().isoformat(), "company": name, "close": round(float(v), 2)} for d, v in close.items()]
    except Exception:  # noqa: BLE001
        return []
