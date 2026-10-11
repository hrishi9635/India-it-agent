"""One-off fix for the numbers already saved in the data folder. Run once."""
import csv, json, shutil
from pathlib import Path

DATA = Path(__file__).parent / "data"
fin_p, mkt_p, ins_p = DATA / "financials.csv", DATA / "market.csv", DATA / "insights.json"
if not fin_p.exists():
    raise SystemExit("Put this file in the india-it-agent folder (next to app.py) and try again.")
for p in (fin_p, mkt_p, ins_p):
    if p.exists():
        shutil.copy(p, p.with_suffix(p.suffix + ".backup"))

rows = list(csv.DictReader(open(fin_p, encoding="utf-8-sig", newline="")))
fields = list(rows[0].keys())

# 1. HCLTech: undo the wrong dollar conversion (every HCLTech row was multiplied by the same rate)
hcl_rev = [r for r in rows if r["company"] == "HCLTech" and r["metric"] == "revenue" and r["quarter"] == "Q1 FY27"]
factor = None
if hcl_rev and float(hcl_rev[0]["value_inr_cr"]) > 200000:
    factor = float(hcl_rev[0]["value_inr_cr"]) / 34579   # official Q1 FY27 revenue, Rs crore
    for r in rows:
        if r["company"] == "HCLTech":
            r["value_inr_cr"] = round(float(r["value_inr_cr"]) / factor, 2)
            r["source"] = "Yahoo Finance (corrected)"
    print(f"HCLTech: divided all figures by {factor:.2f}")
else:
    print("HCLTech revenue already looks right; nothing to undo.")

# 2. HCLTech: use official Q1 FY27 figures (company release, 13 Jul 2026) and drop Yahoo's operating income,
#    which uses a different definition from HCLTech's reported EBIT.
official = {"revenue": 34579, "operating_income": 5831, "net_income": 4624}
rows = [r for r in rows if not (r["company"] == "HCLTech" and r["metric"] == "operating_income" and r["quarter"] != "Q1 FY27")]
for r in rows:
    if r["company"] == "HCLTech" and r["quarter"] == "Q1 FY27" and r["metric"] in official:
        r["value_inr_cr"] = official[r["metric"]]
        r["source"] = "HCLTech Q1 FY27 release"
with open(fin_p, "w", encoding="utf-8", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=fields); w.writeheader(); w.writerows(rows)
print("HCLTech: Q1 FY27 set to official revenue Rs 34,579 cr, EBIT Rs 5,831 cr, net profit Rs 4,624 cr")

# 3. Recalculate HCLTech's P/E from the corrected profit
if mkt_p.exists():
    m = list(csv.DictReader(open(mkt_p, encoding="utf-8-sig", newline="")))
    ni = sorted((r for r in rows if r["company"] == "HCLTech" and r["metric"] == "net_income"), key=lambda r: r["period_end"])
    ttm = sum(float(r["value_inr_cr"]) for r in ni[-4:]) if len(ni) >= 4 else None
    for r in m:
        if r["company"] == "HCLTech" and r.get("market_cap_cr") and ttm:
            r["pe_ttm"] = round(float(r["market_cap_cr"]) / ttm, 1)
            print(f"HCLTech: P/E recalculated to {r['pe_ttm']}")
    with open(mkt_p, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(m[0].keys())); w.writeheader(); w.writerows(m)

# 4. Wipro has not announced Q2 FY27 yet: remove the AI entry that mistook a preview for results
if ins_p.exists():
    ins = json.loads(ins_p.read_text(encoding="utf-8"))
    if (ins.get("Wipro") or {}).get("quarter") == "Q2 FY27":
        ins.pop("Wipro")
        ins_p.write_text(json.dumps(ins, ensure_ascii=False, indent=1), encoding="utf-8")
        print("Wipro: removed the mistaken 'Q2 FY27 out' entry")

print("\nDone. Refresh the dashboard page in your browser. (Backups were saved as *.backup in the data folder.)")
