"""
Sends the email digest (with a one-page PDF snapshot) and Telegram alerts.

When it sends:
  * as soon as a company's results are out (each company is announced once per quarter)
  * a weekly round-up on Mondays
  * NOTIFY_FORCE=yes sends a round-up right now (the "Run workflow" button can set it)
The very first time a channel is switched on it sends one "alerts are on" message with the current
status, instead of announcing every company that already reported.

Each channel is skipped quietly if its secrets are missing, and a problem with one channel never
stops the other.
  Email:    GMAIL_USER, GMAIL_APP_PASSWORD, EMAIL_TO (comma-separated for several people)
  Telegram: TELEGRAM_BOT_TOKEN (TELEGRAM_CHAT_ID is optional: found automatically after you
            send your bot any message)
"""
import html
import json
import os
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

import requests

from agent.settings import DATA, load_settings
from agent.summary import build, inr_cr, new_results, pct

STATE = DATA / "notify_state.json"
IST = timezone(timedelta(hours=5, minutes=30))


def e(x):
    return html.escape(str(x)) if x is not None else ""


def plain_cr(v):  # the PDF's built-in font has no ₹ sign
    return inr_cr(v).replace("₹", "Rs ")


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(st):
    STATE.write_text(json.dumps(st, indent=1), encoding="utf-8")


def links(settings):
    return [(n, settings.get(k)) for n, k in (("Interactive dashboard", "SITE_STREAMLIT"),
                                             ("Backup dashboard", "SITE_HUGGINGFACE"),
                                             ("Fast copy", "SITE_CLOUDFLARE")) if settings.get(k)]


def result_line(r, s):
    i = r["insight"] or {}
    m = i.get("metrics") or {}
    bits = [f"revenue {inr_cr(r['revenue'])}"]
    if r["rev_yoy"] is not None:
        bits.append(f"{pct(r['rev_yoy'])} YoY")
    if m.get("cc_growth_yoy_pct") is not None:
        bits.append(f"CC {pct(m['cc_growth_yoy_pct'])} YoY")
    if r["op_margin"] is not None:
        bits.append(f"margin {pct(r['op_margin'], False)}")
    if r["net_profit"] is not None:
        bits.append(f"net profit {inr_cr(r['net_profit'])}")
    if m.get("deal_wins_usd_bn"):
        bits.append(f"deals ${m['deal_wins_usd_bn']:,.2f} bn")
    return ", ".join(bits)


# ------------------------------------------------------------------ PDF
def make_pdf(s, path):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    ss = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(path), pagesize=landscape(A4), leftMargin=14 * mm, rightMargin=14 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm, title="Indian IT results snapshot")
    k = s["kpi"]
    story = [Paragraph(f"Indian IT · Quarterly results snapshot · {e(s['quarter'])}", ss["Title"]),
             Paragraph(f"Generated {e(s['generated'])} · last agent run {e(s['last_run'])}", ss["Normal"]), Spacer(1, 6)]
    if (s["sector"] or {}).get("headline"):
        story += [Paragraph(f"<b>{e(s['sector']['headline'])}</b>", ss["Normal"]), Spacer(1, 6)]
    kt = Table([["Results out", "Combined quarterly revenue", "Median revenue growth (YoY)", "Median operating margin"],
                [f"{k['reported']}/{k['total']}", plain_cr(k['combined_revenue']), pct(k['median_yoy']), pct(k['median_margin'], False)]],
               colWidths=[60 * mm] * 4)
    kt.setStyle(TableStyle([("FONTNAME", (0, 0), (-1, 0), "Helvetica"), ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#5B6475")),
                            ("FONTSIZE", (0, 0), (-1, 0), 8), ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"), ("FONTSIZE", (0, 1), (-1, 1), 14),
                            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#E4E7EC")), ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E4E7EC")),
                            ("TOPPADDING", (0, 0), (-1, -1), 5), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story += [kt, Spacer(1, 8)]
    head = ["Company", "Status", "Data quarter", "Revenue", "QoQ", "YoY", "Op. margin", "Net profit", "CC YoY", "Guidance", "Mood"]
    data = [head]
    for r in s["rows"]:
        data.append([r["company"], f"{s['quarter']} out" if r["reported"] else ("due " + r["due"] if r["due"] else "awaiting"),
                     r["data_quarter"] or "—", plain_cr(r["revenue"]), pct(r["rev_qoq"]), pct(r["rev_yoy"]),
                     pct(r["op_margin"], False), plain_cr(r["net_profit"]), pct(r["cc_yoy"]), r["guidance"] or "—", r["mood"] or "—"])
    t = Table(data, repeatRows=1)
    style = [("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8),
             ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F5F9")), ("ALIGN", (3, 1), (8, -1), "RIGHT"),
             ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor("#E4E7EC")), ("TOPPADDING", (0, 0), (-1, -1), 3),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    for idx, r in enumerate(s["rows"], 1):
        style.append(("TEXTCOLOR", (0, idx), (0, idx), colors.HexColor(r["color"])))
        style.append(("FONTNAME", (0, idx), (0, idx), "Helvetica-Bold"))
    t.setStyle(TableStyle(style))
    story += [t, Spacer(1, 8)]
    themes = (s["sector"] or {}).get("themes") or []
    if themes:
        story.append(Paragraph("<b>This quarter's themes</b>", ss["Heading4"]))
        for th in themes[:4]:
            story.append(Paragraph(f"<b>{e(th.get('title'))}:</b> {e(th.get('detail'))}", ss["Normal"]))
    story += [Spacer(1, 6), Paragraph("AI-extracted figures should be checked against company releases. Not investment advice.", ss["Italic"])]
    doc.build(story)
    return path


# ------------------------------------------------------------------ email
def email_html(s, settings, new, weekly):
    k = s["kpi"]
    rows = "".join(
        f"<tr><td style='padding:6px 8px;border-bottom:1px solid #eee'><b style='color:{r['color']}'>●</b> {e(r['company'])}</td>"
        f"<td style='padding:6px 8px;border-bottom:1px solid #eee'>{'✅ out' if r['reported'] else ('due ' + e(r['due']) if r['due'] else 'awaiting')}</td>"
        f"<td style='padding:6px 8px;border-bottom:1px solid #eee;text-align:right'>{e(inr_cr(r['revenue']))}</td>"
        f"<td style='padding:6px 8px;border-bottom:1px solid #eee;text-align:right'>{e(pct(r['rev_yoy']))}</td>"
        f"<td style='padding:6px 8px;border-bottom:1px solid #eee;text-align:right'>{e(pct(r['op_margin'], False))}</td>"
        f"<td style='padding:6px 8px;border-bottom:1px solid #eee'>{e(r['mood'] or '—')}</td></tr>" for r in s["rows"])
    newhtml = "".join(
        f"<div style='border-left:4px solid {r['color']};padding:8px 12px;margin:10px 0;background:#F7F8FB'>"
        f"<b>{e(r['name'])}</b> – {e(s['quarter'])} results{' (filed ' + e(r['filed_at']) + ' IST)' if r['filed_at'] else ''}<br>"
        f"{e(result_line(r, s))}<br><i>{e((r['insight'] or {}).get('headline'))}</i></div>" for _, r in new)
    lk = " · ".join(f"<a href='{e(u)}'>{e(n)}</a>" for n, u in links(settings))
    head = (s["sector"] or {}).get("headline")
    return f"""<div style='font-family:Arial,sans-serif;color:#16213E;max-width:720px'>
<h2 style='margin:0 0 4px'>Indian IT results · {e(s['quarter'])}</h2>
<p style='color:#5B6475;margin:0 0 12px'>{'Weekly round-up' if weekly else 'New results'} · {e(s['generated'])}</p>
{f"<p><b>{e(head)}</b></p>" if head else ''}
{('<h3>Just reported</h3>' + newhtml) if new else ''}
<p><b>{k['reported']}/{k['total']}</b> companies have reported · combined revenue <b>{e(inr_cr(k['combined_revenue']))}</b>
({e(k['combined_note'])}) · median growth <b>{e(pct(k['median_yoy']))}</b> · median margin <b>{e(pct(k['median_margin'], False))}</b></p>
<table style='border-collapse:collapse;font-size:13px;width:100%'><tr style='background:#F3F5F9;text-align:left'>
<th style='padding:6px 8px'>Company</th><th style='padding:6px 8px'>Status</th><th style='padding:6px 8px;text-align:right'>Revenue</th>
<th style='padding:6px 8px;text-align:right'>YoY</th><th style='padding:6px 8px;text-align:right'>Op. margin</th><th style='padding:6px 8px'>Mood</th></tr>{rows}</table>
<p>Full dashboard: {lk}</p><p style='color:#5B6475;font-size:12px'>A one-page PDF snapshot is attached. Sent automatically by your results agent.</p></div>"""


def send_email(s, settings, new, weekly, intro=False):
    user, pw, to = os.environ.get("GMAIL_USER"), os.environ.get("GMAIL_APP_PASSWORD"), os.environ.get("EMAIL_TO")
    if not (user and pw and to):
        print("Email: skipped (GMAIL_USER / GMAIL_APP_PASSWORD / EMAIL_TO not set)")
        return False
    if new:
        names = ", ".join(r["company"] for _, r in new)
        subject = f"Indian IT results: {names} {s['quarter']} out"
    elif intro:
        subject = f"Indian IT results alerts are on · {s['kpi']['reported']}/{s['kpi']['total']} reported for {s['quarter']}"
    else:
        subject = f"Indian IT weekly round-up · {datetime.now(IST):%d %b %Y}"
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, user, to
    msg.set_content("Your email app shows the HTML version of this message.")
    msg.add_alternative(email_html(s, settings, new, weekly or intro), subtype="html")
    try:
        pdf = make_pdf(s, DATA.parent / "results_snapshot.pdf")
        msg.add_attachment(pdf.read_bytes(), maintype="application", subtype="pdf",
                           filename=f"Indian-IT-results-{datetime.now(IST):%Y-%m-%d}.pdf")
        pdf.unlink(missing_ok=True)
    except Exception as ex:  # noqa: BLE001
        print(f"Email: PDF skipped ({ex})")
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=60) as smtp:
        smtp.login(user, pw)
        smtp.send_message(msg)
    print(f"Email: sent '{subject}' to {to}")
    return True


# ------------------------------------------------------------------ Telegram
def telegram_chat(token):
    cid = os.environ.get("TELEGRAM_CHAT_ID")
    if cid:
        return cid
    r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=30).json()
    chats = [u.get("message", {}).get("chat", {}).get("id") for u in r.get("result", []) if u.get("message")]
    return str(chats[-1]) if chats else None


def send_telegram(s, settings, new, weekly, intro=False):
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("Telegram: skipped (TELEGRAM_BOT_TOKEN not set)")
        return False
    chat = telegram_chat(token)
    if not chat:
        print("Telegram: no chat found yet – open your bot in Telegram and send it any message (e.g. 'hi')")
        return False
    k = s["kpi"]
    parts = []
    if intro:
        parts.append("🔔 <b>Indian IT results alerts are on.</b> You'll get a message as soon as a company reports.")
    for _, r in new:
        parts.append(f"📊 <b>{e(r['name'])}</b> {e(s['quarter'])} results out\n{e(result_line(r, s))}\n"
                     f"<i>{e((r['insight'] or {}).get('headline'))}</i>")
    if weekly or intro:
        waiting = [r["company"] + (f" ({r['due']})" if r["due"] else "") for r in s["rows"] if not r["reported"]]
        parts.append(f"🗓 <b>{k['reported']}/{k['total']}</b> reported for {e(s['quarter'])}. "
                     f"Median growth {e(pct(k['median_yoy']))}, median margin {e(pct(k['median_margin'], False))}."
                     + (f"\nStill to report: {e(', '.join(waiting))}" if waiting else ""))
    lk = links(settings)
    if lk:
        parts.append(" · ".join(f"<a href='{e(u)}'>{e(n)}</a>" for n, u in lk))
    text = "\n\n".join(parts)[:4000]
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=30,
                      json={"chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True})
    r.raise_for_status()
    print("Telegram: message sent")
    return True


# ------------------------------------------------------------------ main
def main():
    settings = load_settings()
    s = build()
    state = load_state()
    force = os.environ.get("NOTIFY_FORCE", "").lower() in ("yes", "true", "1")
    today = datetime.now(IST)
    for channel, sender in (("email", send_email), ("telegram", send_telegram)):
        st = state.setdefault(channel, {})
        intro = "announced" not in st
        new = new_results(s, st)
        weekly = force or (today.weekday() == 0 and st.get("last_weekly") != today.date().isoformat())
        if intro:
            new = []  # don't announce everything that already reported; one "alerts are on" message instead
        if not (new or weekly or intro):
            print(f"{channel.title()}: nothing new")
            continue
        try:
            sent = sender(s, settings, new, weekly, intro=intro)
        except Exception as ex:  # noqa: BLE001
            print(f"{channel.title()}: problem – {type(ex).__name__}: {str(ex)[:200]}")
            continue
        if sent:
            done = set(st.get("announced", [])) | {f"{r['company']}|{s['quarter']}" for r in s["rows"] if r["reported"]}
            st["announced"] = sorted(done)
            if weekly or intro:
                st["last_weekly"] = today.date().isoformat()
    save_state(state)


if __name__ == "__main__":
    main()
