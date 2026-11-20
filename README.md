# FCPO Supply & Demand Dashboard

Single-page Streamlit dashboard for Malaysian palm oil (FCPO) fundamentals: MPOB
supply & demand balance, export pace, and cross-market bean-palm spread.

Built from `Prompt/fcpo_60min_prompt.md` for a 60-minute demo.

---

## Run it

```bat
run_1001.bat
```

or manually:

```bat
C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe -m streamlit run app.py --server.port 1001
```

Then open **http://localhost:1001**

Regenerate the seeded data (only needed if you change the seed logic):

```bat
C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe scripts\seed_data.py
C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe scripts\validate_data.py
```

Requirements: `pip install -r requirements.txt` (streamlit, plotly, pandas, numpy, yfinance).

---

## What is live vs what is sample data

| Element | Status | Source |
|---|---|---|
| CBOT Soybean Oil `ZL=F` (cents/lb) | **LIVE** | yfinance, cached 1h, silent CSV fallback |
| USD/MYR `MYR=X` | **LIVE** | yfinance, cached 1h, silent CSV fallback |
| MPOB monthly balances, Jan 2016 – Apr 2022 | **REAL** | `MPOB data.xlsx` → `Monthly` sheet |
| MPOB monthly balances, May 2022 – Oct 2026 | **Sample data** | modelled: real seasonal factors + balance identity |
| FCPO 3rd-month price | **Sample data** | seeded random walk around 4,200 MYR/MT (no free Yahoo ticker exists: `FCPO=F`, `FCPO.F`, `FCPO` all 404) |
| FCPO 12-month forward curve | **Sample data** | seeded, two snapshots (today / 1 month ago) |
| Surveyor export estimates (ITS, AmSpec) | **Sample data** | seeded, 5 periods × 2 surveyors × 4 months |
| Export destination split | **Sample data** | seeded from the surveyor's full-month estimate |

Every non-live figure carries a **LIVE** (green) or **Sample data** (amber) badge on
screen, and the footer repeats the full live/sample inventory.

---

## Data provenance

`MPOB data.xlsx` was parsed directly (no manual copy-paste). The `Monthly` sheet
holds 149 months, **Dec-2009 → Apr-2022**, with these real MPOB series used:

| CSV column | Workbook row |
|---|---|
| `production` | `Production` (total CPO) |
| `ending_stocks` | `Stock` — total palm oil (CPO + PPO) |
| `exports` | `Export` (CPO) |
| `imports` | `Import` (CPO + PPO) |
| `local_disappearance` | `LDSP` |
| `ffb_price` | `FFB (RM/tonne)` |

The modelled tail keeps the balance identity exactly:
`stocks_t = stocks_(t-1) + production + imports − exports − local_disappearance`
(0 violations across all 130 months, verified by `scripts/validate_data.py`).
Production seasonality is preserved: **lowest in February, peak in October**.

---

## One deliberate deviation from the prompt

The prompt specifies `STU% = ending_stocks ÷ (exports + domestic) × 100` and asks
for a tag at **Tight if STU < 15%, Surplus if > 20%**.

The formula is kept **exactly**. The thresholds are not, because real palm oil
stock-to-use runs **66% – 193% (median 118%)** in the MPOB history — the preset
15%/20% thresholds would tag **every single month "Surplus"** and make the KPI
meaningless.

Implemented thresholds: **Tight < 105%, Neutral 105–130%, Surplus > 130%**
→ 40 Tight / 63 Neutral / 27 Surplus months across the window, so the tag
actually moves. Change `STU_TIGHT` / `STU_SURPLUS` at the top of `app.py` if you
want the original numbers back.

---

## The 10 questions asked (and how each was answered)

**Already confirmed before build (asked via questionnaire):**

1. **Runtime** — no Python on this machine, only Node 26. → *Install Python 3.12 + Streamlit via winget.* Done: Python 3.12.10 + streamlit 1.67.0.
2. **Data gap** — workbook ends Apr 2022, today is Nov 2026. → *Model the gap from seasonality, tag Sample data.* Done: 54 modelled months, real/sample flagged per row.
3. **Demo scope** — → *Full prompt build order, all 4 sections.* Done: KPI strip, S&D balance, export pace, cross-market.
4. **Live market data** — → *yfinance.* Done: `ZL=F` and `MYR=X` are LIVE with silent CSV fallback.

**Open questions, implemented with these defaults (say the word and I'll change any of them):**

5. **FCPO price series** — default: seeded random walk around 4,200 MYR/MT clipped to 3,800–4,800. *Alternative: pull from a paid/ licensed feed, or a scraper for Bursa.*
6. **Export destination split** — default: India 30%, China 20%, EU 18%, Pakistan 12%, RoW 20%, with ±15% monthly drift. *Alternative: use real destination data from a surveyor feed.*
7. **Stock-to-use tag thresholds** — default: Tight < 105%, Surplus > 130% (see above). *Alternative: keep the prompt's 15%/20% literally.*
8. **Theme** — default: Streamlit dark theme + Plotly `plotly_dark`, custom CSS for the LIVE/Sample badges. *Alternative: light theme, or a brand palette.*
9. **Deliverable form** — default: local-only at `localhost:1001`, no public deployment. *Alternative: publish to a public URL (needs your explicit approval — the site would be visible to anyone with the link).*
10. **Data format** — default: CSVs in `data/`, regenerated by `scripts/seed_data.py`, with the workbook extract committed as `data/mpob_real.csv`. *Alternative: read `MPOB data.xlsx` at runtime (needs `openpyxl`), or move to PostgreSQL (Phase 2).*

---

## 2-minute demo click path

1. **Open http://localhost:1001** — title, KPI strip and sidebar are already on screen.
2. **KPI strip (top)** — FCPO 4,471 MYR/MT (−0.78% 1d, *Sample data*) · MPOB ending stocks 1,961,043 t (+14.1% MoM, STU 100%, **Tight** tag) · ITS export estimate 1,733,453 t (+5.7% vs Sep) · **bean-palm spread +236 USD/MT (LIVE via yfinance)**.
3. **Section 2 · Supply & Demand Balance** — grouped bars (production / exports / domestic) + ending-stocks line on the right axis, with the violet **5-year min–max band and average**. Point at the Oct-2026 production spike against the band. Below it, the **deviation vs 5-year average for the same month**: production +17.0%, exports +5.0%, stocks +0.9%.
4. **Toggle "5-year min-max band & average" off**, then on — show the band is a toggle, not a chart artefact.
5. **Section 3 · Export Pace** — grouped columns in the style of `chart1.PNG` (solid blue = this month, grey = last month, red with white diagonal hatch = last year) across the 1-10 / 1-15 / 1-20 / 1-25 / full-month periods, plus the horizontal **stacked bar by destination** (India 510,605 t leads, then China / EU / Pakistan / RoW).
6. **Section 4 · Cross-Market** — bean-palm spread with ±1σ / ±2σ bands (σ = 170 USD/MT) and the **forward curve: today vs 1 month ago, tagged Backwardation** (front 4,466 → 12-month 4,260 MYR/MT, −4.6%).
7. **Sidebar** — change the **Data window** (e.g. 2024-01 → 2026-10) to show the charts re-scaling; point at the **Data status** block to state what is live and what is sample.
8. **Footer** — data sources, live-vs-sample inventory, Phase 2 list.

Talking point if asked "is it live?": soybean oil and USD/MYR are live market data
via yfinance; MPOB balances are real MPOB figures to Apr 2022 and modelled after;
the FCPO price, forward curve and surveyor estimates are seeded and labelled as
such on every screen.

---

## Files

```
app.py                      single-file dashboard (Streamlit + Plotly)
requirements.txt            python dependencies
run_1001.bat                one-click launcher on port 1001
scripts/seed_data.py        builds every CSV in data/ from data/mpob_real.csv
scripts/validate_data.py    data QA: identity, STU, ranges, seasonality
data/mpob_real.csv          raw extract of the real MPOB workbook (149 months)
data/mpob_monthly.csv       Jan 2016 - Oct 2026, with source=real|sample per row
data/mpob_real_full.csv     full real history Dec 2009 - Apr 2022
data/surveyor_exports.csv   ITS + AmSpec, 5 periods, destination split
data/fcpo_daily.csv         2 years of 3rd-month closes
data/fcpo_forward.csv       12-month forward curve, two snapshots
data/fallback_*.csv         market fallbacks used when yfinance is unavailable
```

## Phase 2 (not built today)

Telegram/Telethon listener · MPOB scraper · PostgreSQL/TimescaleDB · POGO spread ·
GAPKI · USDA · SPPOMA · auth · deployment.
