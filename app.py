"""
FCPO Supply & Demand Dashboard
==============================
Single-page Streamlit dashboard for Malaysian palm oil (FCPO) fundamentals.

Live market data (CBOT Soybean Oil ZL=F, USD/MYR MYR=X, and FCPO if a ticker
resolves) is pulled with yfinance. Everything else comes from seeded CSVs in
data/ (MPOB monthly balances, surveyor export estimates, FCPO price/forward
curve). Any figure that is not live is labelled "Sample data" on screen.

Run:  streamlit run app.py --server.port 1001
"""

import os
from datetime import date, datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

st.set_page_config(
    page_title="FCPO Supply & Demand Dashboard",
    page_icon="🌴",
    layout="wide",
    initial_sidebar_state="expanded",
)

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

# --- Stock-to-use tag thresholds (palm-oil scale) ---------------------------
# Prompt's formula is kept exactly: STU% = ending_stocks / (exports + domestic) * 100
# Real palm-oil STU runs ~66-193% (median 118%), so the prompt's preset
# <15%/>20% would tag every single month "Surplus". Only the thresholds are
# rescaled so the tag is informative; the formula is untouched.
STU_TIGHT = 105.0
STU_SURPLUS = 130.0

CSS = """
<style>
  .block-container { padding-top: 1.6rem; padding-bottom: 2rem; }
  [data-testid="stMetricValue"] { font-size: 1.55rem; }
  .badge {
      display:inline-block; padding:1px 9px; border-radius:10px;
      font-size:0.72rem; font-weight:600; letter-spacing:.02em;
      margin-left:8px; vertical-align:middle;
  }
  .badge-live   { background:#0f3d2e; color:#4ade80; border:1px solid #14532d; }
  .badge-sample { background:#3b2f12; color:#fbbf24; border:1px solid #713f12; }
  .badge-tight  { background:#3f1d1d; color:#f87171; border:1px solid #7f1d1d; }
  .badge-surplus{ background:#14321d; color:#4ade80; border:1px solid #14532d; }
  .badge-neutral{ background:#2a2f3a; color:#cbd5e1; border:1px solid #3f4654; }
  .kpi-note { color:#94a3b8; font-size:0.75rem; margin-top:-6px; }
  h2 { border-bottom:1px solid #33415580; padding-bottom:4px; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


# ============================================================================
# Loaders
# ============================================================================
@st.cache_data(show_spinner=False)
def load_mpob():
    df = pd.read_csv(os.path.join(DATA, "mpob_monthly.csv"))
    df["month"] = pd.to_datetime(df["month"] + "-01")
    for c in ("production", "exports", "imports", "local_disappearance", "ending_stocks"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("month").reset_index(drop=True)


@st.cache_data(show_spinner=False)
def load_surveyor():
    df = pd.read_csv(os.path.join(DATA, "surveyor_exports.csv"))
    return df


@st.cache_data(show_spinner=False)
def load_fcpo_daily():
    df = pd.read_csv(os.path.join(DATA, "fcpo_daily.csv"))
    df["date"] = pd.to_datetime(df["date"])
    return df.sort_values("date").reset_index(drop=True)


@st.cache_data(show_spinner=False)
def load_forward():
    df = pd.read_csv(os.path.join(DATA, "fcpo_forward.csv"))
    df["contract_dt"] = pd.to_datetime(df["contract"] + "-01")
    return df


@st.cache_data(show_spinner=False)
def load_fallback(name, value_col):
    df = pd.read_csv(os.path.join(DATA, name))
    df["date"] = pd.to_datetime(df["date"])
    df[value_col] = pd.to_numeric(df[value_col], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


@st.cache_data(ttl=3600, show_spinner=False)
def load_live_market():
    """Try yfinance for soy oil / FX / FCPO. Silently fall back to CSV."""
    out = {"live": {"soy": False, "fx": False, "fcpo": False}, "error": None}
    soy = fx = fcpo = None
    try:
        import yfinance as yf

        def grab(ticker, field="Close"):
            d = yf.download(ticker, period="2y", progress=False, auto_adjust=True)
            if d is None or len(d) == 0:
                return None
            if isinstance(d.columns, pd.MultiIndex):
                d.columns = d.columns.get_level_values(0)
            if field not in d.columns:
                return None
            s = d[field].dropna()
            if len(s) < 30:
                return None
            out_ = pd.DataFrame({"date": pd.to_datetime(s.index).tz_localize(None).normalize(),
                                 "value": s.to_numpy()})
            return out_[out_["date"] > out_["date"].max() - pd.Timedelta(days=760)]

        # CBOT Soybean Oil: Yahoo quotes USD/lb -> normalise to cents/lb
        s = grab("ZL=F")
        if s is not None and s["value"].median() > 0:
            if s["value"].median() < 5:      # USD/lb -> cents/lb
                s["value"] = s["value"] * 100.0
            soy = s
            out["live"]["soy"] = True

        # USD/MYR: Yahoo may quote MYR-per-USD or USD-per-MYR -> normalise
        f = grab("MYR=X")
        if f is not None and f["value"].median() > 0:
            if f["value"].median() < 1:      # USD per MYR -> MYR per USD
                f["value"] = 1.0 / f["value"]
            fx = f
            out["live"]["fx"] = True

        # FCPO has no free Yahoo ticker (FCPO=F / FCPO.F / FCPO all 404),
        # so the FCPO price stays on the seeded series.
        if os.environ.get("FCPO_LIVE_TICKER"):
            s2 = grab(os.environ["FCPO_LIVE_TICKER"])
            if s2 is not None and 3000 < s2["value"].median() < 6000:
                fcpo = s2.rename(columns={"value": "close"})
                out["live"]["fcpo"] = True
    except Exception as exc:  # pragma: no cover - network/parse failures
        out["error"] = str(exc)[:120]

    if soy is None:
        soy = load_fallback("fallback_cbot_soy.csv", "cents_per_lb").rename(columns={"cents_per_lb": "value"})
    if fx is None:
        fx = load_fallback("fallback_usdmyr.csv", "usd_myr").rename(columns={"usd_myr": "value"})
    out["soy"], out["fx"], out["fcpo"] = soy, fx, fcpo
    return out


def live_badge(live: bool) -> str:
    cls, txt = ("badge-live", "LIVE") if live else ("badge-sample", "Sample data")
    return f'<span class="badge {cls}">{txt}</span>'


# ============================================================================
# Derived series
# ============================================================================
def build_spread(market, fcpo_daily):
    """Bean-palm spread: soy USD/MT - FCPO USD/MT, daily."""
    df = fcpo_daily[["date", "close"]].rename(columns={"close": "fcpo_myr"})
    df = df.merge(market["soy"][["date", "value"]].rename(columns={"value": "cents_lb"}),
                  on="date", how="left").merge(
        market["fx"][["date", "value"]].rename(columns={"value": "usd_myr"}),
        on="date", how="left")
    df["cents_lb"] = df["cents_lb"].ffill()
    df["usd_myr"] = df["usd_myr"].ffill()
    df = df.dropna()
    df["soy_usd_mt"] = df["cents_lb"] * 22.0462
    df["fcpo_usd_mt"] = df["fcpo_myr"] / df["usd_myr"]
    df["spread"] = df["soy_usd_mt"] - df["fcpo_usd_mt"]
    return df


def fmt_mt(x) -> str:
    return f"{x:,.0f}"


def month_order(ym: str) -> int:
    """Sortable integer for a YYYY-MM string."""
    return int(ym[:4]) * 12 + int(ym[5:7])


def banner(live: bool, text: str = "") -> str:
    return live_badge(live) + (f" {text}" if text else "")


# ============================================================================
# Load everything
# ============================================================================
mpob = load_mpob()
surveyor = load_surveyor()
fcpo_daily = load_fcpo_daily()
forward = load_forward()
market = load_live_market()

live_soy = market["live"]["soy"]
live_fx = market["live"]["fx"]
live_fcpo = market["live"]["fcpo"]

# FCPO price series: live if a ticker resolved, otherwise seeded
if live_fcpo:
    fcpo_series = market["fcpo"][["date", "close"]]
else:
    fcpo_series = fcpo_daily[["date", "close"]]

spread = build_spread(market, fcpo_daily)

# ============================================================================
# Sidebar
# ============================================================================
months = mpob["month"].dt.strftime("%Y-%m").tolist()
min_m, max_m = months[0], months[-1]

with st.sidebar:
    st.markdown("### 🌴 FCPO Dashboard")
    st.caption("MPOB supply & demand, export pace and cross-market spread.")

    d_start = datetime.strptime(months[max(0, len(months) - 61)], "%Y-%m").date()
    d_end = datetime.strptime(months[-1], "%Y-%m").date()
    picked = st.date_input(
        "Data window", value=(d_start, d_end),
        min_value=datetime.strptime(months[0], "%Y-%m").date(),
        max_value=d_end, format="YYYY-MM-DD",
    )
    if isinstance(picked, (tuple, list)):
        start_m = picked[0].strftime("%Y-%m") if picked[0] else months[0]
        end_m = picked[1].strftime("%Y-%m") if len(picked) > 1 and picked[1] else months[-1]
    else:
        start_m = end_m = picked.strftime("%Y-%m")
    if month_order(start_m) > month_order(end_m):
        start_m, end_m = end_m, start_m

    st.divider()
    st.markdown("#### Display")
    show_band = st.toggle("5-year min-max band & average", value=True)
    show_sigma = st.toggle("Spread ±1σ / ±2σ bands", value=True)

    st.divider()
    st.markdown("#### Data status")
    st.markdown(
        f"- Soybean oil (ZL=F): {banner(live_soy)}\n"
        f"- USD/MYR: {banner(live_fx)}\n"
        f"- FCPO price: {banner(live_fcpo)}\n"
        f"- MPOB balances: {live_badge(True)} real to Apr 2022, {live_badge(False)} modelled after",
        unsafe_allow_html=True,
    )
    if market.get("error"):
        st.caption(f"yfinance: {market['error']} (using CSV fallback)")

    st.divider()
    st.caption("Phase 2 (not built today): Telegram/Telethon listener, MPOB scraper, "
               "PostgreSQL/TimescaleDB, POGO spread, GAPKI, USDA, SPPOMA, auth, deployment.")


# ============================================================================
# Header
# ============================================================================
st.title("FCPO Supply & Demand Dashboard")
st.markdown(
    f"<div class='kpi-note'>Window <b>{start_m}</b> to <b>{end_m}</b> &nbsp;|&nbsp; "
    f"MPOB reference month <b>{mpob['month'].dt.strftime('%b %Y').iloc[-1]}</b> "
    f"&nbsp;|&nbsp; built for a 60-minute demo</div>",
    unsafe_allow_html=True,
)
st.divider()

# ============================================================================
# 1. KPI strip
# ============================================================================
latest = mpob.iloc[-1]
prev = mpob.iloc[-2]


def deviation_vs_5y(df, month_ts, col, value):
    """% deviation of a value vs the 5-year average for the same calendar month."""
    mm, yy = month_ts.month, month_ts.year
    hist = df[(df["month"].dt.month == mm) & (df["month"].dt.year >= yy - 5)
              & (df["month"].dt.year < yy)]
    if hist.empty:
        return None
    avg = float(hist[col].mean())
    if not avg:
        return None
    return (value - avg) / avg * 100

# FCPO price + 1-day change
px_last = float(fcpo_series["close"].iloc[-1])
px_prev = float(fcpo_series["close"].iloc[-2])
px_chg = (px_last / px_prev - 1) * 100

# Ending stocks + MoM + STU tag
stk = float(latest["ending_stocks"])
stk_mom = (stk / float(prev["ending_stocks"]) - 1) * 100
stu = stk / (float(latest["exports"]) + float(latest["local_disappearance"])) * 100
if stu < STU_TIGHT:
    tag, tag_cls = "Tight", "badge-tight"
elif stu > STU_SURPLUS:
    tag, tag_cls = "Surplus", "badge-surplus"
else:
    tag, tag_cls = "Neutral", "badge-neutral"

# Surveyor export estimate vs last month
its = surveyor[surveyor["surveyor"] == "ITS"]
full = its[its["period"] == "Full"].copy().sort_values("month")
surv_last, surv_prev = full.iloc[-1], full.iloc[-2]
surv_chg = (surv_last["tonnes"] / surv_prev["tonnes"] - 1) * 100

# Bean-palm spread
sp_now = float(spread["spread"].iloc[-1])
sp_prev = float(spread["spread"].iloc[-2])

c1, c2, c3, c4 = st.columns(4)
with c1:
    st.metric(
        "FCPO 3rd month (MYR/MT)",
        f"{px_last:,.0f}",
        delta=f"{px_chg:+.2f}% 1d",
    )
    st.markdown(f"<div class='kpi-note'>{banner(live_fcpo)}</div>", unsafe_allow_html=True)
with c2:
    st.metric(
        "MPOB Ending Stocks (MT)",
        fmt_mt(stk),
        delta=f"{stk_mom:+.1f}% MoM",
        delta_color="off",
    )
    st.markdown(
        f"<div class='kpi-note'>{latest['month'].strftime('%b %Y')} &nbsp; "
        f"STU {stu:.0f}% &nbsp;<span class='badge {tag_cls}'>{tag}</span></div>",
        unsafe_allow_html=True)
with c3:
    st.metric(
        "Surveyor Exports (ITS Full, MT)",
        fmt_mt(surv_last["tonnes"]),
        delta=f"{surv_chg:+.1f}% vs {surv_prev['month']}",
        delta_color="off",
    )
    st.markdown(
        f"<div class='kpi-note'>{surv_last['month']} &nbsp; {live_badge(False)}</div>",
        unsafe_allow_html=True)
with c4:
    st.metric(
        "Bean-Palm Spread (USD/MT)",
        f"{sp_now:+,.0f}",
        delta=f"{sp_now - sp_prev:+,.0f} vs prior day",
        delta_color="off",
    )
    st.markdown(
        f"<div class='kpi-note'>{banner(live_soy and live_fx, 'Soy oil & FX via yfinance')}</div>",
        unsafe_allow_html=True)

st.divider()

# ============================================================================
# 2. Supply & demand balance
# ============================================================================
st.subheader("2 · Supply & Demand Balance")
mask = (mpob["month"] >= pd.Timestamp(start_m + "-01")) & (mpob["month"] <= pd.Timestamp(end_m + "-01"))
view = mpob[mask].copy()

fig = make_subplots(specs=[[{"secondary_y": True}]])
x = view["month"].dt.strftime("%Y-%m")
fig.add_trace(go.Bar(name="Production", x=x, y=view["production"], marker_color="#f59e0b",
                     hovertemplate="%{x}<br>Production %{y:,.0f} t<extra></extra>"), secondary_y=False)
fig.add_trace(go.Bar(name="Exports", x=x, y=view["exports"], marker_color="#22c55e",
                     hovertemplate="%{x}<br>Exports %{y:,.0f} t<extra></extra>"), secondary_y=False)
fig.add_trace(go.Bar(name="Local disappearance", x=x, y=view["local_disappearance"], marker_color="#38bdf8",
                     hovertemplate="%{x}<br>Domestic %{y:,.0f} t<extra></extra>"), secondary_y=False)
fig.add_trace(go.Scatter(name="Ending stocks", x=x, y=view["ending_stocks"], mode="lines+markers",
                         line=dict(color="#e879f9", width=2.5), marker=dict(size=4),
                         hovertemplate="%{x}<br>Stocks %{y:,.0f} t<extra></extra>"), secondary_y=True)

if show_band:
    # 5-year min-max band and average for the SAME calendar month
    lows, highs, avgs = [], [], []
    for _, row in view.iterrows():
        mm, yy = row["month"].month, row["month"].year
        hist = mpob[(mpob["month"].dt.month == mm) & (mpob["month"].dt.year >= yy - 5)
                    & (mpob["month"].dt.year < yy)]
        if len(hist):
            lows.append(hist["ending_stocks"].min())
            highs.append(hist["ending_stocks"].max())
            avgs.append(hist["ending_stocks"].mean())
        else:
            lows.append(np.nan); highs.append(np.nan); avgs.append(np.nan)
    fig.add_trace(go.Scatter(name="5-yr max", x=x, y=highs, mode="lines", line=dict(color="#a78bfa", width=1, dash="dot"),
                             hoverinfo="skip", showlegend=False), secondary_y=True)
    fig.add_trace(go.Scatter(name="5-yr min-max band", x=x, y=lows, mode="lines", line=dict(color="#a78bfa", width=1, dash="dot"),
                             fill="tonexty", fillcolor="rgba(167,139,250,0.12)",
                             hovertemplate="5-yr min %{y:,.0f} t<extra></extra>"), secondary_y=True)
    fig.add_trace(go.Scatter(name="5-yr average", x=x, y=avgs, mode="lines", line=dict(color="#a78bfa", width=1.5),
                             hovertemplate="5-yr avg %{y:,.0f} t<extra></extra>"), secondary_y=True)

fig.update_layout(
    barmode="group", template="plotly_dark", height=440, margin=dict(l=10, r=10, t=30, b=10),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    hovermode="x unified",
    yaxis=dict(title="Flow (MT/month)", gridcolor="#33415580"),
    yaxis2=dict(title="Ending stocks (MT)", gridcolor="rgba(0,0,0,0)", overlaying="y", side="right"),
)
st.plotly_chart(fig, width="stretch")
st.caption("Bars: monthly production / exports / domestic disappearance. Line: ending stocks (right axis). "
           "MPOB data is real to Apr 2022 and modelled thereafter (Sample data).")

st.markdown(f"**Deviation vs 5-year average, same month "
            f"({latest['month'].strftime('%b %Y')})**")
_dev_cols = st.columns(3)
for _c, (_lbl, _key) in zip(_dev_cols, [("Production", "production"),
                                        ("Exports", "exports"),
                                        ("Ending stocks", "ending_stocks")]):
    _d = deviation_vs_5y(mpob, latest["month"], _key, float(latest[_key]))
    _c.metric(_lbl, "n/a" if _d is None else f"{_d:+.1f}%", delta_color="off")

st.divider()

# ============================================================================
# 3. Export pace
# ============================================================================
st.subheader("3 · Export Pace")
months_3 = [surv_last["month"], surv_prev["month"]]
ly = full[full["month"] == "2025-10"]
ly_month = "2025-10"
label_map = {surv_last["month"]: f"This month ({surv_last['month']})",
             surv_prev["month"]: f"Last month ({surv_prev['month']})",
             ly_month: f"Last year ({ly_month})"}

# Style mirrored from chart1.PNG (the workbook reference image): grouped columns
# on a white plot area, solid blue series + red series with a white diagonal
# hatch, black gridlines / axis / text.
CHART1_BLUE = "#2A51A4"
CHART1_RED = "#C32021"
CHART1_GREY = "#7B7A7A"
CHART1_INK = "#231F20"
CHART1_DAYS = {"1-10": 10, "1-15": 15, "1-20": 20, "1-25": 25, "Full": 30}
CHART1_PERIOD_LABEL = {"1-10": "1-10", "1-15": "1-15", "1-20": "1-20",
                        "1-25": "1-25", "Full": "Full month"}

# (month, label, fill, hatch, outline) - chart1 uses blue solid + red hatched
PACE_SERIES = [
    (surv_last["month"], f"This month ({surv_last['month']})", CHART1_BLUE, False, "#1B3570"),
    (surv_prev["month"], f"Last month ({surv_prev['month']})", CHART1_GREY, False, "#4F4F4F"),
    (ly_month, f"Last year ({ly_month})", CHART1_RED, True, CHART1_RED),
]

fig2 = go.Figure()
for mth, lbl, fill, hatched, edge in PACE_SERIES:
    sub = its[its["month"] == mth].copy()
    if sub.empty:
        continue
    order = {"1-10": 0, "1-15": 1, "1-20": 2, "1-25": 3, "Full": 4}
    sub["ord"] = sub["period"].map(order)
    sub = sub.sort_values("ord")
    marker = dict(color=fill, line=dict(width=1, color=edge))
    if hatched:
        marker["pattern"] = dict(shape="/", fgcolor="#FFFFFF",
                                 bgcolor=fill, solidity=0.22, size=7)
    fig2.add_trace(go.Bar(
        x=[CHART1_PERIOD_LABEL[p] for p in sub["period"]],
        y=sub["tonnes"] / 1_000_000,
        name=lbl,
        marker=marker,
        hovertemplate="%{x}<br>%{y:,.2f} million t<extra>%{fullData.name}</extra>"))

fig2.update_layout(
    template="plotly_white", height=430,
    margin=dict(l=70, r=20, t=60, b=100),
    plot_bgcolor="#FFFFFF", paper_bgcolor="#FFFFFF",
    font=dict(color=CHART1_INK),
    title=dict(text="CPO Monthly Export Pace", x=0.0, xanchor="left",
               font=dict(size=17, color=CHART1_INK)),
    legend=dict(orientation="h", yanchor="top", y=-0.26, x=0.5, xanchor="center",
                bgcolor="rgba(0,0,0,0)", font=dict(color=CHART1_INK, size=12)),
    barmode="group", bargap=0.18, bargroupgap=0.06,
    xaxis=dict(title="Export period (day of month)", gridcolor="rgba(0,0,0,0)",
               showline=True, linecolor=CHART1_INK, linewidth=1, ticks="outside",
               tickcolor=CHART1_INK, tickfont=dict(color=CHART1_INK),
               title_font=dict(color=CHART1_INK), zeroline=False),
    yaxis=dict(title="Million tonnes", tickformat=".1f", tickmode="linear",
               tick0=0, dtick=0.25,
               gridcolor="#231F20", gridwidth=1, showline=True, linecolor=CHART1_INK,
               linewidth=1, ticks="outside", tickcolor=CHART1_INK,
               tickfont=dict(color=CHART1_INK), title_font=dict(color=CHART1_INK),
               zeroline=False),
    hovermode="closest",
)
st.plotly_chart(fig2, width="stretch")
st.caption("Grouped columns styled after chart1.PNG: solid blue = this month, "
           "grey = last month, red with white diagonal hatch = last year.")

# Destination split
dest_rows = []
for mth in [surv_last["month"], surv_prev["month"], ly_month]:
    sub = its[(its["month"] == mth) & (its["period"] == "Full")]
    if not sub.empty:
        dest_rows.append((label_map.get(mth, mth), sub.iloc[0]))

DESTS = ["India", "China", "EU", "Pakistan", "RoW"]
COLORS = ["#f59e0b", "#22c55e", "#38bdf8", "#e879f9", "#94a3b8"]
fig3 = go.Figure()
for _i, (lbl, row) in enumerate(dest_rows):
    for d, c in zip(DESTS, COLORS):
        fig3.add_trace(go.Bar(
            y=[lbl], x=[float(row[d])], orientation="h", name=d,
            marker_color=c, text=f"{d} {row[d]:,.0f}", textposition="inside",
            showlegend=(_i == 0),
            hovertemplate="%{x:,.0f} t<extra></extra>"))
fig3.update_layout(
    template="plotly_dark", height=220, barmode="stack",
    margin=dict(l=10, r=10, t=30, b=10),
    legend=dict(orientation="h", yanchor="bottom", y=1.08, x=0),
    xaxis=dict(title="Export tonnes (full-month estimate)", gridcolor="#33415580"),
)
st.plotly_chart(fig3, width="stretch")
st.caption("ITS surveyor estimates by destination. Sample data - surveyor figures are seeded, "
           "not scraped from a live MPOB/surveyor feed.")

st.divider()

# ============================================================================
# 4. Cross-market
# ============================================================================
st.subheader("4 · Cross-Market")
c_a, c_b = st.columns([3, 2])

with c_a:
    st.markdown("**Bean-palm spread (soy oil − FCPO), USD/MT**")
    fig4 = go.Figure()
    mu, sd = spread["spread"].mean(), spread["spread"].std()
    fig4.add_hline(y=mu, line=dict(color="#cbd5e1", width=1.5, dash="dash"),
                   annotation_text=f"mean {mu:,.0f}", annotation_position="top left")
    if show_sigma:
        for k, col, al in ((2, "rgba(248,113,113,0.10)", 1), (1, "rgba(148,163,184,0.14)", 1)):
            fig4.add_hrect(y0=mu - k * sd, y1=mu + k * sd, fillcolor=col, line_width=0,
                           annotation_text=f"±{k}σ", annotation_position="top right")
    fig4.add_trace(go.Scatter(x=spread["date"], y=spread["spread"], mode="lines",
                               line=dict(color="#22c55e", width=1.6),
                               name="Spread",
                               hovertemplate="%{x|%b %Y}<br>%{y:,.0f} USD/MT<extra></extra>"))
    fig4.update_layout(template="plotly_dark", height=380, margin=dict(l=10, r=10, t=30, b=10),
                       legend=dict(orientation="h", y=1.02),
                       xaxis=dict(title="", gridcolor="#33415580"),
                       yaxis=dict(title="USD/MT", gridcolor="#33415580"))
    st.plotly_chart(fig4, width="stretch")
    st.markdown(f"<span style='color:#94a3b8;font-size:0.75rem'>σ bands from the daily spread sample "
                f"(σ = {sd:,.0f} USD/MT).</span> {banner(live_soy and live_fx, 'Soy oil and USD/MYR live via yfinance')}",
                unsafe_allow_html=True)

with c_b:
    st.markdown("**FCPO forward curve**")
    fig5 = go.Figure()
    for snap, colour, lbl in (("today", "#f59e0b", "Today"), ("1m_ago", "#64748b", "1 month ago")):
        sub = forward[forward["snapshot"] == snap].sort_values("contract_dt")
        if sub.empty:
            continue
        fig5.add_trace(go.Scatter(x=sub["contract_dt"], y=sub["price"], mode="lines+markers",
                                  name=lbl, line=dict(color=colour, width=2.5),
                                  hovertemplate="%{x|%b %Y}<br>%{y:,.0f} MYR/MT<extra></extra>"))
    today_curve = forward[forward["snapshot"] == "today"].sort_values("contract_dt")
    if len(today_curve) >= 2:
        front, back = float(today_curve["price"].iloc[0]), float(today_curve["price"].iloc[-1])
        shape = "Contango" if back > front else "Backwardation"
        st.markdown(f"<div style='text-align:center'><span class='badge badge-neutral'>{shape}</span></div>",
                    unsafe_allow_html=True)
        st.caption(f"Front {front:,.0f} → 12-month {back:,.0f} MYR/MT "
                   f"({(back/front-1)*100:+.1f}%). Sample data - forward curve is seeded.")
    fig5.update_layout(template="plotly_dark", height=320, margin=dict(l=10, r=10, t=30, b=10),
                       legend=dict(orientation="h", y=1.02),
                       xaxis=dict(title="", gridcolor="#33415580"),
                       yaxis=dict(title="MYR/MT", gridcolor="#33415580"))
    st.plotly_chart(fig5, width="stretch")

st.divider()

# ============================================================================
# Footer
# ============================================================================
st.markdown("---")
st.markdown(
    f"""
**Data sources** &nbsp; MPOB monthly balances (*MPOB data.xlsx*, real to Apr 2022, modelled May 2022–Oct 2026) ·
CBOT Soybean Oil `ZL=F` and USD/MYR `MYR=X` via yfinance {live_badge(live_soy and live_fx)} ·
FCPO price & forward curve, surveyor export estimates: **Sample data** (seeded).

**Live vs sample** &nbsp; Soybean oil: {live_badge(live_soy)} · USD/MYR: {live_badge(live_fx)} ·
FCPO price: {live_badge(live_fcpo)} · MPOB balances to Apr 2022: {live_badge(True)} ·
MPOB balances after Apr 2022, FCPO price/curve, surveyor estimates: {live_badge(False)}

**Phase 2 (not built today)** &nbsp; Telegram/Telethon listener · MPOB scraper ·
PostgreSQL/TimescaleDB · POGO spread · GAPKI · USDA · SPPOMA · auth · deployment.
""",
    unsafe_allow_html=True,
)
st.caption(f"Generated {datetime.now():%d %b %Y %H:%M} · Streamlit + Plotly")
