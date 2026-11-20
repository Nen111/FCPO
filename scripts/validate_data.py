"""Data QA for the FCPO dashboard: identity checks, seasonality, ranges."""
import csv
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")


def rows(name):
    with open(os.path.join(DATA, name), newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


mpob = rows("mpob_monthly.csv")
print(f"mpob_monthly.csv: {len(mpob)} months {mpob[0]['month']} -> {mpob[-1]['month']}")
real = [r for r in mpob if r["source"] == "real"]
samp = [r for r in mpob if r["source"] == "sample"]
print(f"  real={len(real)} sample={len(samp)}")

# 1. balance identity: S_t = S_{t-1} + prod + imp - exp - ldsp
bad = 0
for a, b in zip(mpob, mpob[1:]):
    implied = (float(a["ending_stocks"]) + float(b["production"]) + float(b["imports"])
               - float(b["exports"]) - float(b["local_disappearance"]))
    if abs(implied - float(b["ending_stocks"])) > 1:
        bad += 1
print(f"  balance identity violations: {bad}")

# 2. STU and ranges
stus = []
for r in mpob:
    stu = float(r["ending_stocks"]) / (float(r["exports"]) + float(r["local_disappearance"])) * 100
    stus.append((r["month"], stu))
vals = [s for _, s in stus]
print(f"  STU%: min {min(vals):.0f}  med {sorted(vals)[len(vals)//2]:.0f}  max {max(vals):.0f}")
tight = sum(1 for v in vals if v < 105)
surp = sum(1 for v in vals if v > 130)
print(f"  STU tags -> Tight {tight} / Neutral {len(vals)-tight-surp} / Surplus {surp}")

prods = [float(r["production"]) for r in mpob]
stks = [float(r["ending_stocks"]) for r in mpob]
exps = [float(r["exports"]) for r in mpob]
print(f"  production  {min(prods):,.0f} - {max(prods):,.0f}  (prompt band 1.5-2.0M)")
print(f"  stocks      {min(stks):,.0f} - {max(stks):,.0f}  (prompt band 1.5-2.5M)")
print(f"  exports     {min(exps):,.0f} - {max(exps):,.0f}")

# 3. seasonality: production by calendar month (avg) - expect low Feb, peak Sep/Oct
by_m = {}
for r in mpob:
    by_m.setdefault(r["month"][5:7], []).append(float(r["production"]))
avg_m = {m: sum(v) / len(v) for m, v in by_m.items()}
lo = min(avg_m, key=avg_m.get)
hi = max(avg_m, key=avg_m.get)
print(f"  seasonality -> lowest month {lo} ({avg_m[lo]:,.0f}), highest {hi} ({avg_m[hi]:,.0f})")

# 4. modelled tail continuity
first_sample = samp[0]
print(f"  modelled starts {first_sample['month']} (prev real "
      f"{mpob[mpob.index(first_sample)-1]['month']}), stocks jump "
      f"{float(first_sample['ending_stocks']) - float(mpob[mpob.index(first_sample)-1]['ending_stocks']):+,.0f} t")

surv = rows("surveyor_exports.csv")
print(f"surveyor_exports.csv: {len(surv)} rows, months "
      f"{sorted({r['month'] for r in surv})}, surveyors {sorted({r['surveyor'] for r in surv})}")
fcpo = rows("fcpo_daily.csv")
print(f"fcpo_daily.csv: {len(fcpo)} rows {fcpo[0]['date']} -> {fcpo[-1]['date']} "
      f"close {fcpo[-1]['close']}")
fwd = rows("fcpo_forward.csv")
print(f"fcpo_forward.csv: {len(fwd)} rows, snapshots {sorted({r['snapshot'] for r in fwd})}")
