"""
The Indian IT results agent
---------------------------
Run it:            python run_agent.py
Re-check everyone: python run_agent.py --force
Only some firms:   python run_agent.py --only "TCS,Infosys"
No AI (data only): python run_agent.py --skip-ai
Save your AI key:  python run_agent.py --set-key

What it does, in order:
 1. Works out which quarter's results are being announced now.
 2. Downloads share prices and quarterly financials for each company (free, Yahoo Finance).
 3. Searches the news for each company (free Google News and Bing News feeds, plus Bloomberg and
    Reuters headlines).
 4. Checks the stock exchanges (BSE, with NSE as backup) for the company's official results filing and
    press release. This is the fastest, most reliable source: news, Bloomberg and Yahoo all copy from it.
 5. For companies with new results, asks a free AI model to read the official filing and the news and pull
    out the key facts, searching again if important facts are missing, and throwing away any number it
    can't find in a source.
 6. Writes a sector-wide view for the quarter.
 7. Saves everything in the "data" folder, where the dashboard reads it.
"""
import argparse
import csv
import json
import sys
import time
import traceback
from datetime import datetime, timezone

from agent import analyst, market
from agent import filings as filingsmod
from agent import overrides as ovr
from agent import news as newsmod
from agent.llm import LLM, AIError
from agent.quarters import label as quarter_label_of
from agent.quarters import months_text, previous_quarter_end, target_quarter
from agent.settings import DATA, load_companies, load_settings, save_key


FIN_FIELDS = ["company", "ticker", "period_end", "quarter", "metric", "value_inr_cr", "source"]


def read_json(name, default):
    p = DATA / name
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return default
    return default


def write_json(name, obj):
    DATA.mkdir(exist_ok=True)
    (DATA / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def write_csv(name, rows, fields):
    DATA.mkdir(exist_ok=True)
    with open(DATA / name, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def read_csv(name):
    p = DATA / name
    if not p.exists():
        return []
    with open(p, encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def merge_rows(old, new, key_fields, companies_refreshed):
    """Keep history: replace rows for refreshed companies, keep older rows that Yahoo no longer returns."""
    keep = {tuple(r[k] for k in key_fields): r for r in old}
    for r in new:
        keep[tuple(str(r[k]) for k in key_fields)] = {k: str(v) for k, v in r.items()}
    return sorted(keep.values(), key=lambda r: tuple(r[k] for k in key_fields))


def quick_scorecard(fin_rows):
    by = {}
    for r in fin_rows:
        by.setdefault(r["company"], {}).setdefault(r["period_end"], {})[r["metric"]] = float(r["value_inr_cr"])
    out = []
    for c, q in by.items():
        ps = sorted(q)
        last = q[ps[-1]]
        rev = last.get("revenue")
        row = {"company": c, "quarter_end": ps[-1], "revenue_inr_cr": rev}
        if rev and last.get("operating_income") is not None:
            row["op_margin_pct"] = round(last["operating_income"] / rev * 100, 1)
        if len(ps) >= 2 and rev and q[ps[-2]].get("revenue"):
            row["revenue_qoq_pct"] = round((rev / q[ps[-2]]["revenue"] - 1) * 100, 1)
        if len(ps) >= 5 and rev and q[ps[-5]].get("revenue"):
            row["revenue_yoy_pct"] = round((rev / q[ps[-5]]["revenue"] - 1) * 100, 1)
        out.append(row)
    return out


def main():
    ap = argparse.ArgumentParser(description="Indian IT results agent")
    ap.add_argument("--force", action="store_true", help="re-analyse every company with AI")
    ap.add_argument("--only", default="", help="comma-separated short names, e.g. TCS,Infosys")
    ap.add_argument("--skip-ai", action="store_true", help="update data and news only")
    ap.add_argument("--set-key", action="store_true", help="save your AI key on this computer")
    ap.add_argument("--no-articles", action="store_true", help="read headlines only, not article pages")
    args = ap.parse_args()

    if args.set_key:
        key = input("Paste your AI key (from console.groq.com/keys) and press Enter:\n> ").strip()
        if len(key) < 20:
            print("That doesn't look like a full key. Nothing saved.")
            return 1
        path = save_key(key)
        print(f"Saved. Your key is stored on this computer only, at: {path}")
        print("It is NOT inside the project folder, so it will never be uploaded to GitHub.")
        return 0

    try:
        import yfinance as yf
    except ImportError:
        print("The add-ons aren't installed yet. Run step 1 (Set up) first: python -m pip install -r requirements.txt")
        return 1

    settings = load_settings()
    companies = load_companies()
    if args.only:
        wanted = {x.strip().lower() for x in args.only.split(",")}
        companies = [c for c in companies if c["short"].lower() in wanted or c["name"].lower() in wanted]
    qe, qlabel = target_quarter()
    prev_label = quarter_label_of(previous_quarter_end(qe))
    started = datetime.now(timezone.utc)
    log = {"started": started.isoformat(timespec="seconds"), "quarter": qlabel, "steps": [], "errors": []}

    print(f"\n=== Indian IT results agent · looking at {qlabel} ({months_text(qe)}) ===\n")

    # ---------- 1. market data + financials ----------
    print("Step 1 of 5 · Share prices and quarterly financials (Yahoo Finance)")
    fx, fx_hist = market.usd_inr(yf)
    fin_new, mkt_rows, prices, refreshed = [], [], [], set()
    for c in companies:
        print(f"   {c['short']}...", end=" ", flush=True)
        try:
            t = market.resolve_ticker(yf, c["tickers"])
            if not t:
                raise RuntimeError(f"no price data for {c['tickers']}")
            rows = market.quarterly_rows(yf, c, t, fx, fx_hist)
            too_big = [r for r in rows if r["metric"] == "revenue" and r["value_inr_cr"] > 200000]
            if too_big:  # no Indian IT company earns ₹2 lakh crore in a quarter: the data is wrong
                log["errors"].append(f"financials {c['short']}: implausible revenue {too_big[0]['value_inr_cr']:,.0f} cr, skipped")
                print("(financials looked wrong, skipped) ", end="")
                rows = []
            snap, pr = market.market_snapshot(yf, c, t, rows)
            fin_new += rows
            mkt_rows.append(snap)
            prices += pr
            refreshed.add(c["short"])
            latest = max((r["quarter"] for r in rows), default="none", key=lambda q: (q[-2:], q[1]))
            print(f"ok (latest quarter in data: {latest})")
        except Exception as e:  # noqa: BLE001
            print(f"skipped ({e})")
            log["errors"].append(f"market {c['short']}: {e}")
        time.sleep(1.5)
    bench = market.benchmark_prices(yf, settings["BENCHMARK_TICKER"])
    old_fin = read_csv("financials.csv")
    fin_all = merge_rows(old_fin, fin_new, ["company", "period_end", "metric"], refreshed)
    # official numbers win over Yahoo: first those read from exchange filings, then your hand-checked overrides
    fin_all = ovr.apply(fin_all, ovr.read_rows(DATA / "filed_financials.csv"), ovr.read_rows(DATA / "overrides.csv"))
    write_csv("financials.csv", fin_all, FIN_FIELDS)
    if mkt_rows:
        old_m = {r["company"]: r for r in read_csv("market.csv")}
        for r in mkt_rows:
            old_m[r["company"]] = r
        write_csv("market.csv", list(old_m.values()), ["company", "name", "ticker", "price", "price_date", "market_cap_cr",
                                                       "return_1m", "return_3m", "return_1y", "high_52w", "low_52w", "pe_ttm"])
    if prices:
        keep = [r for r in read_csv("prices.csv") if r["company"] not in refreshed and r["company"] != "Nifty IT"]
        write_csv("prices.csv", keep + prices + bench, ["date", "company", "close"])
    log["steps"].append(f"market data for {len(refreshed)}/{len(companies)} companies")

    # ---------- 2. news ----------
    print("\nStep 2 of 5 · News search (Google News + Bing News, incl. Bloomberg & Reuters headlines)")
    all_news = read_json("news.json", {})
    for c in companies:
        queries = [f"{c['search']} {qlabel} results", f"{c['search']} quarterly results",
                   f"{c['search']} deal OR guidance OR CEO",
                   f"{c['search']} (site:bloomberg.com OR site:reuters.com)",
                   f"{c['search']} media OR gaming OR broadcaster OR publishing OR edtech OR telecom deal"]
        if c.get("media_vertical"):
            queries.append(f"{c['search']} {c['media_vertical'].split(';')[0]} vertical growth")
        items = []
        for q in queries:
            items += newsmod.search(q, c["aliases"], settings["NEWS_DAYS"])
        seen, uniq = set(), []
        for it in sorted(items, key=lambda x: x["published"] or "", reverse=True):
            if it["title"] not in seen:
                seen.add(it["title"])
                uniq.append(it)
        if uniq:
            all_news[c["short"]] = uniq[:40]
        print(f"   {c['short']}: {len(uniq)} articles")
    write_json("news.json", all_news)
    log["steps"].append("news updated")

    # ---------- 3. official stock-exchange filings ----------
    print("\nStep 3 of 5 · Official results filings (BSE, NSE as backup)")
    filings = read_json("filings.json", {})
    bse, nse = filingsmod.BSE(), None
    for c in companies:
        try:
            f = filingsmod.company_filings(c, qe, bse=bse, nse=nse)
            if not f["checked"] and c.get("nse_symbol") and nse is None:
                try:  # BSE didn't answer: try NSE once
                    nse = filingsmod.NSE()
                    f = filingsmod.company_filings(c, qe, bse=None, nse=nse)
                except Exception as e:  # noqa: BLE001
                    f["error"] = (f.get("error") or "") + f"; NSE: {type(e).__name__}"
        except Exception as e:  # noqa: BLE001
            f = {"checked": False, "error": f"{type(e).__name__}: {str(e)[:120]}"}
        f["quarter"] = qlabel
        filings[c["short"]] = f
        if f.get("result"):
            print(f"   {c['short']}: RESULTS FILED on {f['exchange']} at {f['result']['time'].replace('T', ' ')}"
                  + (" (+ press release)" if f.get("press") else ""))
        elif f.get("checked"):
            nxt = f" · results due {f['next_results_date']}" if f.get("next_results_date") else ""
            print(f"   {c['short']}: no results filing yet{nxt}")
        else:
            print(f"   {c['short']}: exchange not reachable ({f.get('error')}); will rely on news")
            log["errors"].append(f"filings {c['short']}: {f.get('error')}")
        time.sleep(0.8)
    write_json("filings.json", filings)
    filed = [n for n, f in filings.items() if f.get("quarter") == qlabel and f.get("result")]
    log["steps"].append(f"exchange filings checked; results filed: {', '.join(filed) or 'none'}")

    # ---------- 3. AI analysis ----------
    print("\nStep 4 of 5 · AI analysis of results")
    insights = read_json("insights.json", {})
    llm = LLM(settings)
    analysed = []
    if args.skip_ai:
        print("   Skipped (you used --skip-ai).")
    elif not llm.available():
        print("   Skipped: no AI key found. Save one with:  python run_agent.py --set-key")
        log["errors"].append("no AI key")
    else:
        yahoo = {}
        for r in fin_all:
            yahoo.setdefault(r["company"], {}).setdefault(r["quarter"], {})[r["metric"]] = float(r["value_inr_cr"])
        for c in companies:
            name = c["short"]
            current = insights.get(name) or {}
            items = all_news.get(name, [])
            fil = filings.get(name) if (filings.get(name) or {}).get("quarter") == qlabel else None
            official_out = bool(fil and fil.get("result"))
            if current.get("quarter") == qlabel and current.get("results_found") and analyst.results_check(current, qe, fil):
                print(f"   {name}: earlier analysis said results were out, but {analyst.results_check(current, qe, fil)}; resetting")
                current = {}  # an earlier run wrongly marked results as out; check again
                insights.pop(name, None)
            done = current.get("quarter") == qlabel and current.get("results_found")
            if done and official_out and not current.get("official"):
                print(f"   {name}: official filing now available, re-reading it")
                done = False
            if done and not args.force:
                print(f"   {name}: {qlabel} already analysed")
                continue
            if not args.force and not official_out and not analyst.results_news_present(items, qlabel, qe.isoformat()):
                print(f"   {name}: no {qlabel} results news yet, waiting")
                if current and current.get("quarter") != qlabel:
                    current["awaiting"] = qlabel
                    insights[name] = current
                continue
            try:
                official = filingsmod.official_sources(fil) if official_out else []
                print(f"   {name}: reading "
                      + (f"the official filing ({len([o for o in official if o.get('text')])} PDF read) + " if official else "")
                      + f"{min(len(items), 28)} news items...")
                facts = {q: v for q, v in yahoo.get(name, {}).items() if q in (qlabel, prev_label)}
                res = analyst.analyse_company(llm, c, items, qlabel, months_text(qe), facts,
                                              settings["NEWS_DAYS"], read_articles=not args.no_articles,
                                              official=official)
                why = analyst.results_check(res, qe, fil)
                if why:
                    print(f"      -> AI said results were out, but {why}; treating as not out yet")
                    res["results_found"] = False
                if official_out and not res.get("results_found"):
                    res["results_found"] = True  # the exchange filing is proof
                    res["results_date"] = fil["result"]["time"][:10]
                if official_out:
                    res["filing"] = {"exchange": fil["exchange"], "title": fil["result"]["title"],
                                     "url": fil["result"]["url"], "filed": fil["result"]["time"],
                                     "press_url": (fil.get("press") or {}).get("url")}
                if res.get("results_found") or not current.get("results_found"):
                    insights[name] = res
                    analysed.append(name)
                    note = f" (dropped unverified: {', '.join(res['unverified_dropped'])})" if res.get("unverified_dropped") else ""
                    print(f"      -> {'results found' if res.get('results_found') else 'no results yet'}, "
                          f"sentiment {res.get('sentiment')}{note}")
                else:
                    current["awaiting"] = qlabel
                    insights[name] = current
                    print(f"      -> {qlabel} results not out yet; keeping {current.get('quarter')}")
            except AIError as e:
                print(f"      AI problem: {e}")
                log["errors"].append(f"ai {name}: {e}")
                if "refused" in str(e):
                    break
            except Exception as e:  # noqa: BLE001
                print(f"      Unexpected problem: {e}")
                log["errors"].append(f"ai {name}: {traceback.format_exc(limit=2)}")
        write_json("insights.json", insights)
        # keep the official numbers the AI read, so Yahoo's gaps and mistakes are corrected for good
        filed_rows = ovr.read_rows(DATA / "filed_financials.csv")
        for name in analysed:
            res = insights.get(name) or {}
            if res.get("official") and res.get("results_found") and res.get("quarter") == qlabel:
                filed_rows = ovr.apply(filed_rows, ovr.rows_from_filing(name, qe.isoformat(), qlabel, res.get("metrics") or {},
                                                                         (res.get("filing") or {}).get("exchange", "BSE")))
        write_csv("filed_financials.csv", filed_rows, ovr.FIELDS)
        # media / communications vertical, one row per company and quarter, so the trend builds up
        vfields = ["company", "quarter", "period_end", "vertical", "revenue_share_pct", "growth_qoq_pct",
                   "growth_yoy_pct", "growth_cc_yoy_pct", "commentary", "source"]
        vrows = {(r["company"], r["quarter"]): r for r in read_csv("verticals.csv")}
        for name, res in insights.items():
            mv = (res or {}).get("media_vertical")
            if (res or {}).get("results_found") and isinstance(mv, dict) and any(
                    mv.get(k) is not None for k in ("revenue_share_pct", "growth_qoq_pct", "growth_yoy_pct", "growth_cc_yoy_pct")):
                q = res.get("quarter")
                old = vrows.get((name, q), {})
                new = {"company": name, "quarter": q, "period_end": qe.isoformat() if q == qlabel else "",
                                    "vertical": mv.get("name") or "", "revenue_share_pct": mv.get("revenue_share_pct"),
                                    "growth_qoq_pct": mv.get("growth_qoq_pct"), "growth_yoy_pct": mv.get("growth_yoy_pct"),
                                    "growth_cc_yoy_pct": mv.get("growth_cc_yoy_pct"), "commentary": mv.get("commentary") or "",
                                    "source": "exchange filing" if res.get("official") else "news"}
                vrows[(name, q)] = {k: (v if v not in (None, "") else old.get(k, "")) for k, v in new.items()}
        write_csv("verticals.csv", list(vrows.values()), vfields)
        fin_all = ovr.apply(fin_all, filed_rows, ovr.read_rows(DATA / "overrides.csv"))
        write_csv("financials.csv", fin_all, FIN_FIELDS)
    log["steps"].append(f"AI analysed: {', '.join(analysed) or 'none'}")

    # ---------- 4. sector view ----------
    print("\nStep 5 of 5 · Sector view")
    sector = read_json("sector.json", {})
    if analysed or (llm.available() and not args.skip_ai and insights and sector.get("quarter") != qlabel):
        try:
            sector = analyst.sector_view(llm, qlabel, insights, quick_scorecard(fin_all))
            write_json("sector.json", sector)
            print(f"   Written: {sector.get('headline')}")
        except AIError as e:
            print(f"   AI problem: {e}")
            log["errors"].append(f"sector: {e}")
    else:
        print("   Nothing new to summarise.")

    log["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    log["ai_calls"] = llm.calls
    runs = read_json("run_log.json", [])
    write_json("run_log.json", ([log] + runs)[:30])
    print(f"\nDone in {int((datetime.now(timezone.utc) - started).total_seconds())}s. "
          f"AI calls used: {llm.calls}. Problems: {len(log['errors'])}.")
    print("Open the dashboard to see the results.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
