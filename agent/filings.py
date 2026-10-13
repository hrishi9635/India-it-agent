"""Official results straight from the stock exchanges (free, no account needed).

Every listed Indian company must file its quarterly results with BSE and NSE within
30 minutes of the board approving them. That makes the exchange filing the fastest
and most reliable source there is: news sites, Bloomberg and Yahoo all copy from it.

This module:
  * reads each company's recent announcements on BSE (NSE is the backup),
  * finds the results filing and the press release / fact sheet,
  * reads the text inside those PDFs, so the AI can use the company's own numbers,
  * finds the date of the next results board meeting (shown as "results on 16 Oct").
"""
import io
import re
import time
from datetime import date, datetime, timedelta

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36")
BSE_API = "https://api.bseindia.com/BseIndiaAPI/api"
BSE_PDF = "https://www.bseindia.com/xml-data/corpfiling/{folder}/{name}"
NSE_HOME = "https://www.nseindia.com"

RESULT_WORDS = re.compile(r"financial results?|audited results|unaudited results|quarterly results|"
                          r"results? for the (quarter|period)", re.I)
NOT_RESULT = re.compile(r"intimation|to consider|will be held|is scheduled|scheduled to|schedule of|trading window|"
                        r"record date|earnings call|conference call|analyst|investor meet|newspaper|publication", re.I)
PRESS_WORDS = re.compile(r"press release|media release|fact ?sheet|earnings release|investor release|"
                         r"metrics sheet|investor presentation|earnings presentation", re.I)
MEETING_WORDS = re.compile(r"board meeting|meeting of the board", re.I)

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


# ----------------------------------------------------------------- helpers
def _clean(s):
    return re.sub(r"\s+", " ", str(s or "")).strip()


def parse_when(s):
    """Exchange timestamps come in a few formats; return 'YYYY-MM-DDTHH:MM' or ''."""
    s = _clean(s)
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d-%b-%Y %H:%M:%S",
                "%d %b %Y %H:%M:%S", "%d-%m-%Y %H:%M:%S", "%Y-%m-%d", "%d %b %Y", "%d-%b-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s[:26], fmt).strftime("%Y-%m-%dT%H:%M")
        except ValueError:
            continue
    return ""


def find_dates(text):
    """All calendar dates written in a sentence, e.g. '16/10/2026', 'October 16, 2026', '16th Oct 2026'."""
    out = []
    t = text or ""
    for d, m, y in re.findall(r"\b(\d{1,2})[/.-](\d{1,2})[/.-](20\d\d)\b", t):
        try:
            out.append(date(int(y), int(m), int(d)))
        except ValueError:
            pass
    for d, mon, y in re.findall(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9})\.?,?\s+(20\d\d)\b", t):
        if mon[:3].lower() in MONTHS:
            try:
                out.append(date(int(y), MONTHS[mon[:3].lower()], int(d)))
            except ValueError:
                pass
    for mon, d, y in re.findall(r"\b([A-Za-z]{3,9})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(20\d\d)\b", t):
        if mon[:3].lower() in MONTHS:
            try:
                out.append(date(int(y), MONTHS[mon[:3].lower()], int(d)))
            except ValueError:
                pass
    return out


def classify(item, quarter_end):
    """Label one announcement: 'result', 'press', 'meeting' or ''."""
    text = f"{item['category']} {item['subcategory']} {item['title']}"
    filed = item["time"][:10]
    after_quarter = filed > quarter_end.isoformat()
    if after_quarter and PRESS_WORDS.search(text) and not NOT_RESULT.search(item["title"]):
        return "press"
    outcome = re.search(r"outcome of (the )?board meeting", item["title"], re.I) and RESULT_WORDS.search(item["detail"])
    if after_quarter and not NOT_RESULT.search(item["title"]) and (
            "result" in item["category"].lower() or RESULT_WORDS.search(item["title"]) or outcome):
        return "result"
    if MEETING_WORDS.search(text) and re.search(r"result", text, re.I) and NOT_RESULT.search(text):
        return "meeting"
    return ""


# ----------------------------------------------------------------- BSE
class BSE:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept": "application/json, text/plain, */*",
                               "Accept-Language": "en-US,en;q=0.5", "Origin": "https://www.bseindia.com",
                               "Referer": "https://www.bseindia.com/"})

    def _get(self, path, params):
        r = self.s.get(f"{BSE_API}/{path}", params=params, timeout=25)
        r.raise_for_status()
        return r.json()

    def announcements(self, code, start, end, pages=4):
        out = []
        for page in range(1, pages + 1):
            data = self._get("AnnSubCategoryGetData/w", {
                "pageno": page, "strCat": "-1", "strPrevDate": start.strftime("%Y%m%d"),
                "strScrip": code, "strscrip": code, "strSearch": "P", "strToDate": end.strftime("%Y%m%d"),
                "strType": "C", "subcategory": "-1"})
            rows = (data or {}).get("Table") or []
            for r in rows:
                name = _clean(r.get("ATTACHMENTNAME"))
                out.append({
                    "title": _clean(r.get("NEWSSUB") or r.get("HEADLINE")),
                    "detail": _clean(r.get("HEADLINE"))[:400],
                    "category": _clean(r.get("CATEGORYNAME")),
                    "subcategory": _clean(r.get("SUBCATNAME")),
                    "time": parse_when(r.get("DissemDT") or r.get("NEWS_DT") or r.get("DT_TM") or r.get("News_submission_dt")),
                    "url": BSE_PDF.format(folder="AttachLive", name=name) if name else "",
                    "alt_url": BSE_PDF.format(folder="AttachHis", name=name) if name else "",
                    "exchange": "BSE",
                })
            total_pages = 1
            try:
                total_pages = int(((data or {}).get("Table1") or [{}])[0].get("ROWCNT", 0)) // 50 + 1
            except (TypeError, ValueError):
                pass
            if not rows or page >= total_pages:
                break
            time.sleep(0.6)
        return out

    def next_results_date(self, code):
        """BSE's 'forthcoming results' calendar."""
        today = date.today()
        try:
            data = self._get("Corpforthresults/w", {"scripcode": code, "fromdate": today.strftime("%Y%m%d"),
                                                     "todate": (today + timedelta(days=60)).strftime("%Y%m%d")})
        except Exception:  # noqa: BLE001
            return None
        rows = data if isinstance(data, list) else (data or {}).get("Table") or []
        best = None
        for r in rows:
            if str(r.get("scrip_Code") or r.get("SCRIP_CD") or r.get("scripcode") or code) != str(code):
                continue
            for k, v in r.items():
                if "date" in k.lower():
                    w = parse_when(v)
                    if w and w[:10] >= today.isoformat():
                        best = min(best or w[:10], w[:10])
        return best


# ----------------------------------------------------------------- NSE (backup)
class NSE:
    def __init__(self):
        self.s = requests.Session()
        self.s.headers.update({"User-Agent": UA, "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9",
                               "Referer": "https://www.nseindia.com/companies-listing/corporate-filings-announcements"})
        self.s.get(NSE_HOME, timeout=20)  # NSE needs the cookies from its home page first

    def announcements(self, symbol, start, end):
        r = self.s.get(f"{NSE_HOME}/api/corporate-announcements", timeout=25, params={
            "index": "equities", "symbol": symbol,
            "from_date": start.strftime("%d-%m-%Y"), "to_date": end.strftime("%d-%m-%Y")})
        r.raise_for_status()
        data = r.json()
        rows = data if isinstance(data, list) else data.get("data", [])
        return [{
            "title": _clean(r.get("attchmntText") or r.get("desc")),
            "detail": "",
            "category": _clean(r.get("desc")),
            "subcategory": "",
            "time": parse_when(r.get("sort_date") or r.get("an_dt") or r.get("exchdisstime")),
            "url": _clean(r.get("attchmntFile")),
            "alt_url": "",
            "exchange": "NSE",
        } for r in rows]


# ----------------------------------------------------------------- main entry
def company_filings(company, quarter_end, bse=None, nse=None):
    """Everything the exchanges say about this company since shortly before the quarter ended."""
    today = date.today()
    start = quarter_end - timedelta(days=25)  # catches the board-meeting notice sent before quarter end
    out = {"checked": False, "exchange": None, "count": 0, "result": None, "press": None,
           "next_results_date": None, "error": None,
           "checked_at": datetime.now().strftime("%Y-%m-%dT%H:%M")}
    items, errors = None, []
    if company.get("bse_code") and bse is not None:
        try:
            items = bse.announcements(company["bse_code"], start, today)
            out["exchange"] = "BSE"
        except Exception as e:  # noqa: BLE001
            errors.append(f"BSE: {type(e).__name__} {str(e)[:80]}")
    if items is None and company.get("nse_symbol") and nse is not None:
        for sym in company["nse_symbol"]:
            try:
                items = nse.announcements(sym, start, today)
                out["exchange"] = "NSE"
                break
            except Exception as e:  # noqa: BLE001
                errors.append(f"NSE {sym}: {type(e).__name__} {str(e)[:80]}")
    if items is None:
        out["error"] = "; ".join(errors) or "no exchange code in companies.csv"
        return out

    out["checked"] = True
    out["count"] = len(items)
    items.sort(key=lambda x: x["time"] or "")
    meeting_dates, press = [], []
    for it in items:
        kind = classify(it, quarter_end)
        if kind == "result" and not out["result"]:
            out["result"] = it  # the first results filing after the quarter ended
        elif kind == "press":
            press.append(it)
        elif kind == "meeting":
            meeting_dates += [d for d in find_dates(f"{it['title']} {it['detail']}") if d > quarter_end]
    if out["result"]:
        # the press release / fact sheet filed with (or after) the results; a 'press release' beats a deck
        rt = out["result"]["time"][:10]
        same_day = [p for p in press if p["time"][:10] >= rt]
        same_day.sort(key=lambda p: (0 if re.search(r"press release|media release|earnings release", p["title"], re.I) else 1, p["time"]))
        out["press"] = same_day[0] if same_day else None
    if not out["result"] and meeting_dates:
        upcoming = [d for d in meeting_dates if d >= today]
        if upcoming:
            out["next_results_date"] = min(upcoming).isoformat()
    if not out["result"] and not out["next_results_date"] and out["exchange"] == "BSE" and company.get("bse_code"):
        out["next_results_date"] = bse.next_results_date(company["bse_code"])
    return out


def pdf_text(item, max_pages=8):
    """Text inside a filing PDF (big IT companies file text PDFs, not scans)."""
    if not item:
        return ""
    try:
        from pypdf import PdfReader
    except ImportError:
        return ""
    for url in (item.get("url"), item.get("alt_url")):
        if not url:
            continue
        try:
            r = requests.get(url, headers={"User-Agent": UA, "Referer": "https://www.bseindia.com/"}, timeout=40)
            if r.status_code != 200 or not r.content.startswith(b"%PDF"):
                continue
            reader = PdfReader(io.BytesIO(r.content))
            text = " ".join((p.extract_text() or "") for p in reader.pages[:max_pages])
            text = _clean(text)
            if len(text) > 80:
                return text
        except Exception:  # noqa: BLE001
            continue
    return ""


KEY_LINES = re.compile(r"revenue from operations|total income|profit for the (period|quarter)|"
                       r"profit before tax|net profit|earnings per share|ebit|operating margin|"
                       r"constant currency|deal wins|tcv|headcount|attrition|dividend|guidance|outlook", re.I)


def focus(text, limit):
    """Keep the parts of a long filing that hold the numbers: the opening (headline figures, units)
    plus short windows around key lines, until the limit."""
    if len(text) <= limit:
        return text
    head = text[: limit // 2]
    parts, used = [head], len(head)
    last_end = len(head)
    for m in KEY_LINES.finditer(text):
        a, b = max(m.start() - 150, last_end), min(m.end() + 350, len(text))
        if b <= last_end:
            continue
        chunk = text[a:b]
        if used + len(chunk) > limit:
            break
        parts.append(chunk)
        used += len(chunk)
        last_end = b
    return " … ".join(parts)


def official_sources(filing, budget=6000):
    """Turn the filings into numbered-source entries for the AI, press release first."""
    out = []
    if not filing or not filing.get("checked"):
        return out
    press, result = filing.get("press"), filing.get("result")
    press_text = pdf_text(press) if press else ""
    result_text = pdf_text(result) if result else ""
    share_press = int(budget * (0.65 if result_text else 1.0)) if press_text else 0
    share_result = budget - share_press
    for it, text, share in ((press, press_text, share_press), (result, result_text, share_result)):
        if not it:
            continue
        out.append({
            "title": f"OFFICIAL {it['exchange']} FILING: {it['title']}",
            "link": it["url"], "source": f"{it['exchange']} filing", "provider": "Exchange",
            "published": (it["time"] or "")[:16] + (":00+05:30" if it["time"] else ""),
            "snippet": "", "official": True,
            "text": focus(text, share) if text and share > 300 else "",
        })
    return out
