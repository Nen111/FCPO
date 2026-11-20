"""
FCPO Supply & Demand Dashboard - seed data generator.

Builds every CSV the dashboard reads, from the real MPOB monthly series
extracted from "MPOB data.xlsx" (data/mpob_real.csv) plus seeded series for
the data the workbook does not contain (FCPO price, forward curve, surveyor
export estimates, market fallbacks).

Run:  python scripts/seed_data.py
Out:  data/*.csv
"""

import csv
import math
import os
import random
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
os.makedirs(DATA, exist_ok=True)

RNG = random.Random(20261120)

# Reference "today" for the demo (agent context date).
TODAY = date(2026, 11, 20)

# Latest MPOB reference month (MPOB publishes with ~10 day lag).
LATEST_MPOB = "2026-10"


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def read_csv(path):
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def write_csv(path, fieldnames, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"  wrote {os.path.relpath(path, ROOT):32s} rows={len(rows)}")


def month_add(ym, n):
    y, m = int(ym[:4]), int(ym[5:7])
    total = y * 12 + (m - 1) + n
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def month_diff(a, b):
    ya, ma = int(a[:4]), int(a[5:7])
    yb, mb = int(b[:4]), int(b[5:7])
    return (ya * 12 + ma) - (yb * 12 + mb)


def month_list(start, end):
    out, cur = [], start
    while month_diff(end, cur) >= 0:
        out.append(cur)
        cur = month_add(cur, 1)
    return out


def median(xs):
    s = sorted(xs)
    n = len(s)
    if not n:
        return 0.0
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


# ----------------------------------------------------------------------------
# 1. MPOB monthly: real history + modelled tail
# ----------------------------------------------------------------------------
def seasonal_factors(rows, key):
    """Per-calendar-month multiplicative factor, normalised to mean 1."""
    by_m = {}
    for r in rows:
        v = r.get(key)
        if v in (None, ""):
            continue
        by_m.setdefault(r["month"][5:7], []).append(float(v))
    overall = median([float(r[key]) for r in rows if r.get(key) not in (None, "")])
    factors = {}
    for mm in range(1, 13):
        vals = by_m.get(f"{mm:02d}", [])
        factors[f"{mm:02d}"] = (median(vals) / overall) if vals else 1.0
    return factors


def build_mpob_monthly():
    real_all = read_csv(os.path.join(DATA, "mpob_real.csv"))
    for r in real_all:
        for k in ("production", "exports", "imports", "local_disappearance",
                  "ending_stocks", "ffb_price"):
            r[k] = float(r[k]) if r[k] not in (None, "") else None

    # Keep the full real history in the shipped reference file.
    write_csv(
        os.path.join(DATA, "mpob_real_full.csv"),
        ["month", "production", "exports", "imports", "local_disappearance",
         "ending_stocks", "ffb_price", "source"],
        [dict(r, source="real") for r in real_all],
    )

    f_prod = seasonal_factors(real_all, "production")
    f_exp = seasonal_factors(real_all, "exports")
    f_imp = seasonal_factors(real_all, "imports")
    f_ldsp = seasonal_factors(real_all, "local_disappearance")

    level_prod = median([r["production"] for r in real_all[-12:]])
    level_exp = median([r["exports"] for r in real_all[-12:]])
    level_imp = median([r["imports"] for r in real_all[-12:]])
    level_ldsp = median([r["local_disappearance"] for r in real_all[-12:]])
    stocks = [r for r in real_all if r["ending_stocks"] is not None][-1]["ending_stocks"]

    STOCK_TARGET = 1_850_000  # midpoint of the prompt's 1.5-2.5M MT band

    series = []
    for r in real_all:
        series.append({
            "month": r["month"],
            "production": r["production"],
            "exports": r["exports"],
            "imports": r["imports"],
            "local_disappearance": r["local_disappearance"],
            "ending_stocks": r["ending_stocks"],
            "source": "real",
        })

    # Modelled tail: May 2022 -> Oct 2026
    tail_months = month_list(month_add("2022-04", 1), LATEST_MPOB)
    prev_stocks = stocks
    for i, mth in enumerate(tail_months):
        mm = mth[5:7]
        # mild drift: flat-to-slightly-growing base level
        drift = 1.0 + 0.0015 * i
        noise = lambda amp: 1.0 + RNG.uniform(-amp, amp)  # noqa: E731

        production = clamp(level_prod * f_prod[mm] * drift * noise(0.07),
                            1_000_000, 2_200_000)
        exports = clamp(level_exp * f_exp[mm] * drift * noise(0.09),
                        700_000, 1_900_000)
        imports = clamp(level_imp * f_imp[mm] * drift * noise(0.25),
                        20_000, 200_000)
        ldsp = clamp(level_ldsp * f_ldsp[mm] * drift * noise(0.12),
                     120_000, 420_000)

        # stock identity: S_t = S_{t-1} + prod + imp - exp - ldsp
        identity = prev_stocks + production + imports - exports - ldsp
        # mean-revert toward the target band so stocks stay realistic
        stocks = 0.88 * identity + 0.12 * STOCK_TARGET
        stocks = clamp(stocks, 1_250_000, 2_600_000)
        # restore the identity exactly by solving for local disappearance
        ldsp = production + imports - exports - (stocks - prev_stocks)
        ldsp = clamp(ldsp, 120_000, 420_000)
        stocks = prev_stocks + production + imports - exports - ldsp
        prev_stocks = stocks

        series.append({
            "month": mth,
            "production": round(production),
            "exports": round(exports),
            "imports": round(imports),
            "local_disappearance": round(ldsp),
            "ending_stocks": round(stocks),
            "source": "sample",
        })

    # Prompt window: Jan 2016 -> Oct 2026
    out = [s for s in series if month_diff(s["month"], "2016-01") >= 0]
    for s in out:
        for k in ("production", "exports", "imports", "local_disappearance",
                  "ending_stocks"):
            s[k] = int(round(s[k]))
    write_csv(
        os.path.join(DATA, "mpob_monthly.csv"),
        ["month", "production", "exports", "local_disappearance", "imports",
         "ending_stocks", "source"],
        out,
    )
    return out


# ----------------------------------------------------------------------------
# 2. Surveyor export estimates (ITS / AmSpec) with destination split
# ----------------------------------------------------------------------------
DESTINATIONS = ["India", "China", "EU", "Pakistan", "RoW"]
PERIODS = ["1-10", "1-15", "1-20", "1-25", "Full"]
PERIOD_DAYS = {"1-10": 10, "1-15": 15, "1-20": 20, "1-25": 25, "Full": 30}


def build_surveyor(monthly):
    """last 3 months + same month last year, 2 surveyors, 5 periods each."""
    by_month = {r["month"]: r for r in monthly}
    months = ["2026-08", "2026-09", "2026-10", "2025-10"]

    rows = []
    for mth in months:
        ref = by_month.get(mth)
        base_exp = ref["exports"] if ref else 1_350_000
        for surveyor, offset in (("ITS", 1.0), ("AmSpec", 0.96)):
            # survey houses differ slightly on the level
            full = base_exp * offset * RNG.uniform(0.93, 1.07)
            for period in PERIODS:
                days = PERIOD_DAYS[period]
                # cumulative-to-date tonnes for the period
                frac = {"1-10": 0.34, "1-15": 0.51, "1-20": 0.67,
                        "1-25": 0.83, "Full": 1.0}[period]
                tonnes = full * frac * RNG.uniform(0.985, 1.015)
                # destination mix with mild monthly drift
                base_shares = {"India": 0.30, "China": 0.20, "EU": 0.18,
                               "Pakistan": 0.12, "RoW": 0.20}
                mix = {}
                for d in DESTINATIONS:
                    mix[d] = max(0.02, base_shares[d] * RNG.uniform(0.85, 1.15))
                tot = sum(mix.values())
                mix = {d: v / tot for d, v in mix.items()}
                row = {"month": mth, "surveyor": surveyor, "period": period,
                       "tonnes": int(round(tonnes))}
                for d in DESTINATIONS:
                    row[d] = int(round(tonnes * mix[d]))
                rows.append(row)

    write_csv(
        os.path.join(DATA, "surveyor_exports.csv"),
        ["month", "surveyor", "period", "tonnes"] + DESTINATIONS,
        rows,
    )
    return rows


# ----------------------------------------------------------------------------
# 3. FCPO 3rd-month daily closes + 12-month forward curve
# ----------------------------------------------------------------------------
def build_fcpo_daily():
    days = 730
    px, out = 4180.0, []
    d = TODAY - timedelta(days=days)
    while d <= TODAY:
        if d.weekday() < 5:
            px = px * (1 + RNG.gauss(0, 0.011))
            px = clamp(px, 3800, 4800)
            out.append({"date": d.isoformat(), "close": round(px, 1)})
        d += timedelta(days=1)
    write_csv(os.path.join(DATA, "fcpo_daily.csv"), ["date", "close"], out)

    # 12-month forward curve: today + one month ago
    snaps = []
    for label, snap_date in (("today", TODAY), ("1m_ago", TODAY - timedelta(days=30))):
        base = px if label == "today" else px * RNG.uniform(0.985, 1.015)
        slope = RNG.uniform(-0.012, 0.012)  # per month
        for k in range(1, 13):
            cdate = month_add(snap_date.strftime("%Y-%m"), k)
            price = base * (1 + slope * k) * RNG.uniform(0.997, 1.003)
            snaps.append({"snapshot": label, "snapshot_date": snap_date.isoformat(),
                          "contract": cdate, "price": round(clamp(price, 3600, 5000), 1)})
    write_csv(os.path.join(DATA, "fcpo_forward.csv"),
              ["snapshot", "snapshot_date", "contract", "price"], snaps)
    return out, snaps


# ----------------------------------------------------------------------------
# 4. Market fallbacks (used only when yfinance is unavailable)
# ----------------------------------------------------------------------------
def build_market_fallbacks():
    soy, out = 44.0, []
    d = TODAY - timedelta(days=730)
    while d <= TODAY:
        if d.weekday() < 5:
            soy = clamp(soy * (1 + RNG.gauss(0, 0.011)), 34, 60)
            out.append({"date": d.isoformat(), "cents_per_lb": round(soy, 3)})
        d += timedelta(days=1)
    write_csv(os.path.join(DATA, "fallback_cbot_soy.csv"),
              ["date", "cents_per_lb"], out)

    fx, out = 4.45, []
    d = TODAY - timedelta(days=730)
    while d <= TODAY:
        if d.weekday() < 5:
            fx = clamp(fx * (1 + RNG.gauss(0, 0.0022)), 3.90, 5.10)
            out.append({"date": d.isoformat(), "usd_myr": round(fx, 4)})
        d += timedelta(days=1)
    write_csv(os.path.join(DATA, "fallback_usdmyr.csv"),
              ["date", "usd_myr"], out)


# ----------------------------------------------------------------------------
if __name__ == "__main__":
    print("Seeding FCPO dashboard data...")
    monthly = build_mpob_monthly()
    build_surveyor(monthly)
    build_fcpo_daily()
    build_market_fallbacks()
    real_n = sum(1 for r in monthly if r["source"] == "real")
    print(f"Done. mpob_monthly.csv: {len(monthly)} months "
          f"({real_n} real / {len(monthly) - real_n} modelled).")
