"""Free news search: Google News and Bing News RSS feeds (no account or key needed)."""
import html
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qs, quote_plus, urlparse

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept-Language": "en-IN,en;q=0.9"}
TAG = re.compile(r"<[^>]+>")


def _clean(text):
    return re.sub(r"\s+", " ", html.unescape(TAG.sub(" ", text or ""))).strip()


def _date(text):
    try:
        d = parsedate_to_datetime(text)
        return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat()
    except Exception:  # noqa: BLE001
        return None


def _rss(url, provider):
    try:
        r = requests.get(url, headers=UA, timeout=25)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except Exception as e:  # noqa: BLE001
        print(f"      ({provider} news unavailable: {type(e).__name__})")
        return []
    items = []
    for it in root.iter("item"):
        title = _clean(it.findtext("title"))
        link = (it.findtext("link") or "").strip()
        src = it.find("source")
        source = _clean(src.text) if src is not None and src.text else ""
        if provider == "Bing" and "apiclick" in link:
            link = parse_qs(urlparse(link).query).get("url", [link])[0]
        if provider == "Google" and " - " in title and not source:
            title, source = title.rsplit(" - ", 1)
        elif provider == "Google" and source and title.endswith(" - " + source):
            title = title[: -len(source) - 3]
        if not source:
            source = urlparse(link).netloc.replace("www.", "")
        items.append({
            "title": title, "link": link, "source": source, "provider": provider,
            "published": _date(it.findtext("pubDate")),
            "snippet": _clean(it.findtext("description"))[:400] if provider == "Bing" else "",
        })
    return items


def google_news(query, days):
    q = quote_plus(f"{query} when:{days}d")
    return _rss(f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en", "Google")


def bing_news(query):
    return _rss(f"https://www.bing.com/news/search?q={quote_plus(query)}&format=rss&mkt=en-IN", "Bing")


def search(query, aliases, days):
    """Search both feeds, keep items that name the company and are recent, newest first."""
    items = google_news(query, days) + bing_news(query)
    time.sleep(1)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    seen, out = set(), []
    for it in items:
        text = (it["title"] + " " + it["snippet"]).lower()
        if not any(a.lower() in text for a in aliases):
            continue
        if it["published"] and datetime.fromisoformat(it["published"]) < cutoff:
            continue
        key = re.sub(r"[^a-z0-9]", "", it["title"].lower())[:80]
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    out.sort(key=lambda x: x["published"] or "", reverse=True)
    return out


def article_text(url, max_chars=1800):
    """Read the main paragraphs of a news article. Many sites block this; that's fine."""
    if not url or "news.google.com" in url:
        return ""
    try:
        from bs4 import BeautifulSoup
        r = requests.get(url, headers=UA, timeout=20)
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            return ""
        soup = BeautifulSoup(r.text, "html.parser")
        paras = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
        text = " ".join(p for p in paras if len(p) > 60)
        return text[:max_chars] if len(text) > 300 else ""
    except Exception:  # noqa: BLE001
        return ""
