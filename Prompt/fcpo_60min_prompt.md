# FCPO Supply & Demand Dashboard: 60-minute demo build

Timebox: 60 minutes, then a live demo. Build ONE working dashboard page. Speed beats completeness; every step must leave something demo-able.

## Stack (fastest path)
- Python + Streamlit + Plotly, single file `app.py`, plus `data/` CSVs. Run with `streamlit run app.py`.
- No database, no Telegram listener, no MPOB scraper, no cron jobs today. Use seeded CSVs.
- Live data only where it's one line of code: `yfinance` for CBOT Soybean Oil (`ZL=F`) and USD/MYR (`MYR=X`), last 2 years daily. If yfinance fails, fall back to the CSV silently.
- Label every non-live figure on screen "Sample data". Keep realistic magnitudes (e.g. production 1.5–2.0M MT/month, ending stocks 1.5–2.5M MT, FCPO 3,800–4,800 MYR/MT).

## Seed data (generate with a small script, 5 min)
- `mpob_monthly.csv`: Jan 2016 to Oct 2026, columns month, production, exports, local_disappearance, imports, ending_stocks (with realistic seasonality: low Feb, peak Sep–Oct).
- `surveyor_exports.csv`: last 3 months plus the same month last year, surveyor (ITS, AmSpec), period (1-10, 1-15, 1-20, 1-25, Full), tonnes, plus destination split (India, China, EU, Pakistan, RoW).
- `fcpo_daily.csv`: 2 years of FCPO 3rd-month closes (random walk around 4,200) and a 12-month forward curve snapshot for today and one month ago.

## Calculations (keep exactly)
- Soybean oil USD/MT = CBOT cents/lb × 22.0462
- FCPO USD/MT = FCPO MYR/MT ÷ USD/MYR
- Bean-palm spread = soy USD/MT − FCPO USD/MT, with mean and ±1σ, ±2σ bands
- Stock-to-usage % = ending stocks ÷ (exports + domestic) × 100
- Deviation vs 5-year average for the same month

## Build order (stop wherever the hour ends)
1. **KPI strip (10 min):** FCPO price with 1-day change, latest MPOB ending stocks with MoM % and a tag (Tight if STU < 15%, Surplus if > 20%), latest surveyor export estimate vs last month, bean-palm spread.
2. **S&D balance (15 min):** grouped bars for production, exports and domestic, with ending stocks as a line on a second axis; a toggle to show this year's stocks against the 5-year min–max band and average.
3. **Export pace (10 min):** stepped line of cumulative exports by 5-day period, this month vs last month vs last year; a horizontal stacked bar by destination.
4. **Cross-market (10 min):** bean-palm spread over time with σ bands; FCPO forward curve (today vs a month ago) with a label showing backwardation or contango.
5. **Polish (5 min):** title "FCPO Supply & Demand Dashboard", sidebar date-range filter, dark theme, a footer with data sources and "Sample data" notes.

## Out of scope today
Telegram/Telethon parsing, MPOB scraping, PostgreSQL/TimescaleDB, POGO spread, GAPKI, USDA, SPPOMA, auth, deployment. List these as "Phase 2" in the footer.

When done, report what's live vs sample, and the 2-minute demo click path.
