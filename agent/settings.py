"""Reads settings.txt and the secret AI key."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
KEY_FILE = Path.home() / ".india-it-agent" / "ai_key.txt"

DEFAULTS = {
    "LLM_BASE_URL": "https://api.groq.com/openai/v1",
    "LLM_MODEL": "openai/gpt-oss-120b",
    "LLM_FALLBACK_MODEL": "openai/gpt-oss-20b",
    "LLM_PAUSE_SECONDS": "25",
    "NEWS_DAYS": "30",
    "BENCHMARK_TICKER": "^CNXIT",
}


def load_settings():
    s = dict(DEFAULTS)
    f = ROOT / "settings.txt"
    if f.exists():
        for line in f.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            s[k.strip()] = v.strip()
    for k in list(s):  # environment variables win (used on GitHub)
        if os.environ.get(k):
            s[k] = os.environ[k]
    s["LLM_API_KEY"] = os.environ.get("LLM_API_KEY", "").strip()
    if not s["LLM_API_KEY"] and KEY_FILE.exists():
        s["LLM_API_KEY"] = KEY_FILE.read_text(encoding="utf-8").strip()
    s["LLM_PAUSE_SECONDS"] = float(s["LLM_PAUSE_SECONDS"] or 0)
    s["NEWS_DAYS"] = int(s["NEWS_DAYS"] or 30)
    return s


def save_key(key: str):
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_text(key.strip(), encoding="utf-8")
    return KEY_FILE


def load_companies():
    import csv
    rows = []
    with open(ROOT / "companies.csv", encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            if not (r.get("name") or "").strip():
                continue
            rows.append({
                "name": r["name"].strip(),
                "short": (r.get("short_name") or r["name"]).strip(),
                "tickers": [t.strip() for t in (r.get("tickers") or "").split("|") if t.strip()],
                "search": (r.get("search_name") or r["name"]).strip(),
                "aliases": [a.strip() for a in (r.get("aliases") or r["name"]).split("|") if a.strip()],
                "bse_code": (r.get("bse_code") or "").strip(),
                "nse_symbol": [t.strip() for t in (r.get("nse_symbol") or "").split("|") if t.strip()],
                "media_vertical": (r.get("media_vertical") or "").strip(),
            })
    return rows
