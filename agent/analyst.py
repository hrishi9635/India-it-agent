"""The 'thinking' part of the agent: reads the news, extracts results, asks for more if needed,
checks every number against the sources, and writes the sector view."""
import json
import re
from datetime import datetime, timezone

from . import news as newsmod

DOMAINS = ["Media & broadcasting", "Entertainment & streaming", "Gaming",
           "Education", "Publishing", "Telecom"]

COMPANY_SYSTEM = """You are a careful equity-research analyst covering Indian IT services companies.
You read numbered news sources about ONE company and extract facts about its results for ONE fiscal quarter.
Rules:
- Use ONLY the numbered sources. Never use outside knowledge for numbers, names or dates.
- If something is not stated in the sources, use null (or an empty list). Do not guess.
- Indian fiscal year: Q1 = Apr-Jun, Q2 = Jul-Sep, Q3 = Oct-Dec, Q4 = Jan-Mar. FY27 = Apr 2026 to Mar 2027.
- Keep constant-currency (CC) growth separate from reported rupee or dollar growth.
- Rupee amounts in crore as plain numbers (12075 not "12,075 crore"). Percentages as numbers (2.4 not "2.4%").
- Only count it as results for the requested quarter if a source clearly reports that quarter's ACTUAL results
  (announced numbers). Previews, expectations, analyst or brokerage estimates, "results date" announcements and
  articles about an earlier quarter are NOT results: then set results_found to false and leave metrics null.
- results_date is the day the company announced the results, taken from a source.
- Sources whose title starts with "OFFICIAL" are the company's own stock-exchange filing (results statement or
  press release). They are the most reliable: always prefer their numbers over news reports. If an OFFICIAL
  results filing is present, the results are out and results_date is that filing's date.
- Filings may state amounts in ₹ crore, ₹ million or ₹ lakh. Convert rupee amounts to crore
  (1 crore = 10 million = 100 lakh). Use CONSOLIDATED figures, not standalone. US-dollar revenue in $ million.
- Write short, plain, neutral sentences. Return one JSON object only."""

COMPANY_SCHEMA = """{
 "results_found": true or false,
 "results_date": "YYYY-MM-DD" or null,
 "headline": "one sentence: the most important takeaway",
 "metrics": {
   "revenue_inr_cr": number|null, "revenue_usd_m": number|null,
   "revenue_growth_yoy_pct": number|null, "cc_growth_qoq_pct": number|null, "cc_growth_yoy_pct": number|null,
   "net_profit_inr_cr": number|null, "net_profit_growth_yoy_pct": number|null,
   "operating_margin_pct": number|null, "deal_wins_usd_bn": number|null,
   "headcount": number|null, "net_headcount_change": number|null, "attrition_pct": number|null,
   "dividend_per_share_inr": number|null
 },
 "guidance": "text or null", "guidance_change": "raised|cut|retained|introduced|none|unknown",
 "highlights": ["3-5 short points"],
 "risks": ["1-3 short points"],
 "verticals": [{"name": "vertical name", "note": "growth or comment"}],
 "megep_mentions": [{"domain": "Media & broadcasting|Entertainment & streaming|Gaming|Education|Publishing|Telecom", "note": "what was said, client or deal"}],
 "ai_signals": "what was said about AI revenue, deals or pricing, or null",
 "management_view": "one-sentence paraphrase of management commentary, or null",
 "sentiment": "Positive|Neutral|Negative",
 "sentiment_reason": "short reason",
 "source_ids": [numbers of the sources you used],
 "missing": ["important fields you could not find"],
 "follow_up_queries": ["up to 2 web news searches that would find the missing facts"]
}"""

SECTOR_SYSTEM = """You are the head of research for Indian IT services. You write a crisp quarterly sector view
from per-company summaries prepared by your analysts. Use ONLY the information given. Plain language, short
sentences, no hype. Return one JSON object only."""

SECTOR_SCHEMA = """{
 "headline": "one sentence on the state of the sector this quarter",
 "summary": "3-4 sentences",
 "themes": [{"title": "short title", "detail": "1-2 sentences", "companies": ["names"]}],
 "leaders": [{"company": "name", "why": "short reason"}],
 "laggards": [{"company": "name", "why": "short reason"}],
 "domain_outlook": [{"domain": "Media & broadcasting|Entertainment & streaming|Gaming|Education|Publishing|Telecom",
                     "signal": "Positive|Mixed|Negative|Not enough data", "note": "1-2 sentences"}],
 "watch_next": ["3-5 things to watch next quarter"]
}"""


def _num_variants(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return []
    v = abs(v)
    out = {f"{v:g}", f"{v:.1f}", f"{v:.2f}"}
    if float(v).is_integer():
        out.add(str(int(v)))
        out.add(f"{int(v):,}")
    # rupee crore figures may appear in a filing as ₹ million (x10) or ₹ lakh (x100)
    for mult in (10, 100):
        w = round(v * mult, 2)
        out.update({f"{w:g}", f"{w:.0f}", f"{w:.1f}"})
    return [x.rstrip("0").rstrip(".") if "." in x else x for x in out]


def verify_numbers(result, corpus):
    """Drop any number that does not appear in the source text (protects against made-up figures)."""
    flat = corpus.replace(",", "")
    dropped = []
    for k, v in list((result.get("metrics") or {}).items()):
        if v is None:
            continue
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            result["metrics"][k] = None
            dropped.append(k)
            continue
        if not any(re.search(rf"(?<![\d.]){re.escape(x.replace(',', ''))}(?![\d])", flat) for x in _num_variants(v)):
            result["metrics"][k] = None
            dropped.append(k)
    result["unverified_dropped"] = dropped
    return result


def build_corpus(items, max_items=28, max_articles=3, read_articles=True, official=None):
    """Number the sources so the AI can cite them. Official exchange filings go first."""
    lines, used = [], []
    read = 0
    official = official or []
    if official:  # keep the request inside the free AI's size limit
        max_items, max_articles = max(10, max_items - 8), min(max_articles, 1)
    for i, it in enumerate(official, 1):
        line = f"[{i}] {it['title']} ({it['source']}, {(it.get('published') or '')[:10]})"
        if it.get("text"):
            line += f"\n    Filing text: {it['text']}"
        lines.append(line)
        used.append(it)
    for i, it in enumerate(items[:max_items], len(official) + 1):
        date = (it.get("published") or "")[:10]
        line = f"[{i}] {it['title']} ({it['source']}, {date})"
        if it.get("snippet"):
            line += f" — {it['snippet']}"
        if read_articles and read < max_articles and it.get("provider") == "Bing" and "result" in it["title"].lower():
            body = newsmod.article_text(it["link"])
            if body:
                line += f"\n    Article text: {body}"
                read += 1
        lines.append(line)
        used.append(it)
    return "\n".join(lines), used


def results_news_present(items, quarter_label, quarter_end_iso):
    q = quarter_label.split()[0].lower()  # "q2"
    words = ("result", "profit", "revenue", "earnings", q)
    for it in items:
        if (it.get("published") or "") >= quarter_end_iso and any(w in it["title"].lower() for w in words):
            return True
    return False


def results_check(result, quarter_end, filing=None):
    """Reject 'results found' when the facts make it impossible. Returns the reason, or '' if fine.

    When the stock exchange was checked, its answer wins: a results filing means the results are out,
    no results filing means they are not (whatever the news says)."""
    if not result.get("results_found"):
        return ""
    if filing and filing.get("checked"):
        if filing.get("result"):
            return ""
        if filing.get("count", 0) > 0:
            return "there is no results filing on the stock exchange yet"
    d = result.get("results_date")
    try:
        rd = datetime.fromisoformat(str(d)[:10]).date() if d else None
    except ValueError:
        rd = None
    if rd is None:
        return "no announcement date was found"
    if rd <= quarter_end:
        return f"the date {rd} is before the quarter ended"
    if rd > datetime.now(timezone.utc).date():
        return f"the date {rd} is in the future (a preview)"
    after = [s for s in (result.get("sources") or []) if (s.get("published") or "")[:10] >= rd.isoformat()]
    if not after:
        return "no source was published on or after the results date"
    # The headline itself must report results: a number or a results verb, and no preview wording.
    preview = ("preview", "expect", "estimate", "likely", "to announce", "will announce", "date", "when",
               "board meeting", "what to watch", "ahead of", "could", "may ", "poll", "live updates", "how to")
    reported = ("profit", "net ", "revenue", "rises", "falls", "jumps", "drops", "declines", "beats", "misses",
                "posts", "reports", "crore", " cr", "%", "margin")
    good = [s for s in after
            if not any(w in s.get("title", "").lower() for w in preview)
            and any(w in s.get("title", "").lower() for w in reported)]
    if not good:
        return "no source headline actually reports the numbers (only previews or generic pages)"
    # Sense check: IT services growth never moves this much in one quarter.
    m = result.get("metrics") or {}
    for k, limit in (("cc_growth_qoq_pct", 8), ("cc_growth_yoy_pct", 25)):
        v = m.get(k)
        if isinstance(v, (int, float)) and abs(v) > limit:
            return f"{k} = {v} is not believable for an IT services company"
    return ""


def analyse_company(llm, company, items, quarter_label, quarter_months, yahoo_facts, days, read_articles=True,
                    official=None):
    """One company, up to two rounds: read, notice gaps, search again, re-read."""
    corpus, used = build_corpus(items, read_articles=read_articles, official=official)
    result = None
    for round_no in (1, 2):
        user = (f"Company: {company['name']} (also called {', '.join(company['aliases'])}).\n"
                f"Quarter to analyse: {quarter_label} ({quarter_months}).\n"
                f"Facts already known from the stock exchange data feed (for context, do not copy into metrics "
                f"unless the sources state them): {json.dumps(yahoo_facts)}\n\n"
                f"Sources:\n{corpus}\n\nReturn JSON exactly in this shape:\n{COMPANY_SCHEMA}")
        result = llm.chat_json(COMPANY_SYSTEM, user)
        queries = [q for q in (result.get("follow_up_queries") or []) if isinstance(q, str)][:2]
        important_missing = [m for m in (result.get("missing") or [])
                             if any(w in str(m).lower() for w in ("revenue", "profit", "growth", "margin", "deal", "guidance"))]
        if round_no == 2 or not queries or not important_missing:
            break
        print(f"      Looking for missing facts: {', '.join(queries)}")
        extra = []
        for q in queries:
            extra += newsmod.search(q, company["aliases"], days)
        known = {it["title"] for it in used}
        extra = [it for it in extra if it["title"] not in known]
        if not extra:
            break
        more, more_used = build_corpus(extra, max_items=12, max_articles=1, read_articles=read_articles)
        # renumber the new sources after the existing ones
        offset = len(used)
        more = re.sub(r"^\[(\d+)\]", lambda m: f"[{int(m.group(1)) + offset}]", more, flags=re.M)
        corpus += "\n" + more
        used += more_used
    result = verify_numbers(result, corpus)
    ids = [i for i in (result.get("source_ids") or []) if isinstance(i, int) and 1 <= i <= len(used)]
    for i, it in enumerate(used[:len(official or [])], 1):  # always cite the official filings that were read
        if i not in ids:
            ids.insert(0, i)
    result["sources"] = [{"title": used[i - 1]["title"], "link": used[i - 1]["link"],
                          "source": used[i - 1]["source"], "published": used[i - 1].get("published"),
                          "official": bool(used[i - 1].get("official"))} for i in ids]
    result["official"] = bool(official)
    result["quarter"] = quarter_label
    result["company"] = company["short"]
    result["analysed_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for k in ("follow_up_queries", "source_ids"):
        result.pop(k, None)
    return result


def sector_view(llm, quarter_label, insights, scorecard):
    brief = []
    for name, ins in insights.items():
        if not ins:
            continue
        brief.append({
            "company": name, "quarter": ins.get("quarter"), "results_found": ins.get("results_found"),
            "headline": ins.get("headline"), "metrics": {k: v for k, v in (ins.get("metrics") or {}).items() if v is not None},
            "guidance": ins.get("guidance"), "guidance_change": ins.get("guidance_change"),
            "sentiment": ins.get("sentiment"), "megep_mentions": (ins.get("megep_mentions") or [])[:4],
            "ai_signals": ins.get("ai_signals"),
        })
    user = (f"Quarter: {quarter_label}.\nCompany summaries:\n{json.dumps(brief, ensure_ascii=False)}\n\n"
            f"Reported financials from the exchange data feed (₹ crore, % growth):\n{json.dumps(scorecard)}\n\n"
            f"For domain_outlook cover these domains: {', '.join(DOMAINS)}. Base each on the megep_mentions and "
            f"themes; say 'Not enough data' when there is nothing.\n\nReturn JSON exactly in this shape:\n{SECTOR_SCHEMA}")
    out = llm.chat_json(SECTOR_SYSTEM, user, max_tokens=3000)
    out["quarter"] = quarter_label
    out["written_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return out
