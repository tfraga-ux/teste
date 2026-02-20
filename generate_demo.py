#!/usr/bin/env python3
"""
generate_demo.py
================
Generates a realistic demo HTML dashboard using synthetic 13F data
based on publicly known information about these hedge funds.

This is useful to preview the dashboard format before running
analyze_13f.py against the live SEC EDGAR API.

Usage:
    python generate_demo.py
    # → writes 13f_demo_report.html
"""

import json
import math
import random
import sys
from pathlib import Path

# ─── Seed for reproducibility ────────────────────────────────────────────────
random.seed(42)

# ─── Quarter helpers ─────────────────────────────────────────────────────────

def quarters_range(start="2015-03-31", end="2024-09-30"):
    """Generate list of quarter-end dates."""
    periods = []
    year, month = int(start[:4]), int(start[5:7])
    ey, em = int(end[:4]), int(end[5:7])
    while (year, month) <= (ey, em):
        periods.append(f"{year}-{month:02d}-{[31,30,30,31][month//3-1]:02d}")
        month += 3
        if month > 12:
            month = 1
            year += 1
    return periods


ALL_QUARTERS = quarters_range()

# Map period → index for AUM interpolation
Q_IDX = {p: i for i, p in enumerate(ALL_QUARTERS)}

# ─── Stock universe (real companies these funds have publicly held) ────────────

STOCKS = {
    # US Tech / Growth
    "037833100": ("Apple Inc", "AAPL"),
    "023135106": ("Amazon.com Inc", "AMZN"),
    "02079K305": ("Alphabet Inc (Class A)", "GOOGL"),
    "594918104": ("Microsoft Corp", "MSFT"),
    "67066G104": ("NVIDIA Corp", "NVDA"),
    "30303M102": ("Meta Platforms Inc", "META"),
    "88160R101": ("Tesla Inc", "TSLA"),
    "09073M104": ("Snowflake Inc", "SNOW"),
    "25809K105": ("Datadog Inc", "DDOG"),
    "44891N208": ("HubSpot Inc", "HUBS"),
    "15135B101": ("CrowdStrike Holdings", "CRWD"),
    "91332U101": ("UiPath Inc", "PATH"),
    "81762P102": ("ServiceNow Inc", "NOW"),
    "009375505": ("Airbnb Inc", "ABNB"),
    "82811L101": ("Shopify Inc", "SHOP"),
    "76472A106": ("RingCentral Inc", "RNG"),
    "40574B102": ("Guardant Health", "GH"),
    "38150F107": ("Alphabet Inc (Class C)", "GOOG"),
    "90353T100": ("Uber Technologies", "UBER"),
    "49338L103": ("Workday Inc", "WDAY"),
    "45867G101": ("Intuitive Surgical", "ISRG"),
    "55354G100": ("Mastercard Inc", "MA"),
    "92826C839": ("Visa Inc", "V"),
    "20826T105": ("Constellation Software", "CSU"),
    "038222105": ("Applied Materials", "AMAT"),
    "883556102": ("The Trade Desk", "TTD"),
    "09857L108": ("Booking Holdings", "BKNG"),
    "84470P109": ("Spotify Technology", "SPOT"),
    "029912201": ("Atlassian Corp", "TEAM"),
    "14448C104": ("Carrier Global", "CARR"),
    # Value / Diversified
    "780259107": ("Roper Technologies", "ROP"),
    "46090E103": ("Intercontinental Exchange", "ICE"),
    "531134104": ("Eli Lilly & Co", "LLY"),
    "719413100": ("Pfizer Inc", "PFE"),
    "589331107": ("Merck & Co", "MRK"),
    "G5480U104": ("LSEG (London Stock Exchange)", "LSEG"),
    "428236103": ("Honeywell International", "HON"),
    "822582103": ("Sherwin-Williams", "SHW"),
    "17275R102": ("Cisco Systems", "CSCO"),
    "63935N107": ("Netflix Inc", "NFLX"),
    # International / ADRs
    "46625H100": ("JD.com Inc ADR", "JD"),
    "81141R100": ("Sea Limited ADR", "SE"),
    "59001A102": ("MercadoLibre Inc", "MELI"),
    "G6683N103": ("Meituan (HK-listed)", "MPNGF"),
    "G0593M107": ("Adyen NV", "ADYEY"),
    "L8407E126": ("Wolters Kluwer", "WTKWY"),
    # Activist / Value targets
    "812350106": ("Seagate Technology", "STX"),
    "126650100": ("CBS Corp / Paramount", "PARA"),
    "09075V102": ("Biogen Inc", "BIIB"),
    "023608102": ("American Express", "AXP"),
    "03073E105": ("Amphenol Corp", "APH"),
}

# ─── Fund profiles ────────────────────────────────────────────────────────────
# Each fund has: aum_trajectory (relative), core_stocks, avg_positions, style

FUND_PROFILES = {
    "Egerton Capital": {
        "cik": "1079708",
        "entity_name": "EGERTON CAPITAL LIMITED",
        "description": "London-based long/short equity, founded 1994 by John Armitage. Concentrated growth-at-a-reasonable-price style.",
        "aum_bn": [2.5, 3.0, 3.8, 5.2, 6.4, 7.1, 8.3, 9.2, 8.8, 6.5, 7.8, 8.4, 7.6, 8.1, 8.5, 9.0, 8.7, 8.3, 8.9, 9.4, 9.8, 6.2, 6.8, 7.2, 7.6, 7.9, 8.3, 8.7, 8.4, 8.9, 9.1, 9.3, 9.5, 9.8, 10.1, 10.3, 10.6, 10.8, 11.0],
        "core": ["594918104","02079K305","38150F107","92826C839","55354G100","49338L103","81762P102","G5480U104","780259107","46090E103"],
        "positions": (25, 38),
        "start_q": 0,
    },
    "TCI Fund Management": {
        "cik": "1346807",
        "entity_name": "TCI FUND MANAGEMENT LIMITED",
        "description": "London-based activist/concentrated fund, founded 2003 by Chris Hohn. Typically 5-8 large positions.",
        "aum_bn": [3.2, 4.0, 5.1, 6.8, 8.5, 10.2, 12.5, 13.8, 14.2, 12.1, 15.3, 17.2, 16.8, 18.4, 19.2, 21.5, 22.8, 23.1, 24.5, 25.8, 26.2, 18.4, 20.1, 22.3, 23.5, 24.8, 26.1, 27.4, 26.8, 28.2, 29.5, 30.8, 31.2, 32.5, 33.8, 34.2, 35.1, 36.4, 37.8],
        "core": ["02079K305","594918104","38150F107","92826C839","55354G100","63935N107","G5480U104","09857L108","46090E103"],
        "positions": (5, 10),
        "start_q": 0,
    },
    "Durable Capital Partners": {
        "cik": "1775850",
        "entity_name": "DURABLE CAPITAL PARTNERS LP",
        "description": "Founded 2019 by Henry Ellenbogen (ex-T. Rowe Price). Long-duration, high-quality growth companies.",
        "aum_bn": [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,2.1, 8.5, 7.2, 8.4, 9.1, 9.8, 10.4, 11.2, 10.8, 11.5, 12.1, 12.8, 12.4, 12.9, 13.2, 13.6, 13.9, 14.2, 14.6],
        "core": ["09073M104","25809K105","81762P102","49338L103","883556100","09857L108","023135106","02079K305","29260W104","82811L101"],
        "positions": (20, 35),
        "start_q": 20,
    },
    "RV Capital": {
        "cik": "1634632",
        "entity_name": "RV CAPITAL GMBH",
        "description": "German-based concentrated long-term value fund. Very low turnover, 10-15 quality compounders.",
        "aum_bn": [0.8, 1.0, 1.3, 1.6, 2.0, 2.4, 2.9, 3.3, 3.5, 2.8, 3.4, 3.8, 3.6, 4.0, 4.3, 4.7, 5.0, 5.2, 5.6, 5.9, 6.1, 4.2, 4.8, 5.2, 5.5, 5.8, 6.1, 6.5, 6.3, 6.7, 7.0, 7.3, 7.5, 7.8, 8.1, 8.3, 8.5, 8.7, 8.9],
        "core": ["20826T105","81762P102","49338L103","82811L101","09857L108","029912201","G0593M107","L8407E126"],
        "positions": (8, 14),
        "start_q": 0,
    },
    "D1 Capital Partners": {
        "cik": "1741830",
        "entity_name": "D1 CAPITAL PARTNERS LP",
        "description": "Founded 2018 by Dan Sundheim (ex-Viking Global CIO). Long-biased multi-asset fund.",
        "aum_bn": [0,0,0,0,0,0,0,0,0,0,0,0,2.3,5.8,8.2,12.5,15.8,18.2,20.4,22.1,24.5,14.2,16.8,18.4,19.8,21.2,22.6,24.1,23.5,24.8,26.2,27.5,26.8,28.1,29.4,30.2,31.1,32.0,33.2],
        "core": ["023135106","02079K305","38150F107","594918104","30303M102","63935N107","09073M104","90353T100","009375505","88160R101"],
        "positions": (40, 70),
        "start_q": 12,
    },
    "Tiger Global Management": {
        "cik": "1167483",
        "entity_name": "TIGER GLOBAL MANAGEMENT LLC",
        "description": "Founded 2001 by Chase Coleman (Tiger Cub). Large tech-focused hedge fund and growth equity.",
        "aum_bn": [5.2, 6.8, 9.2, 12.4, 16.8, 21.2, 28.5, 35.2, 40.1, 32.5, 45.2, 52.8, 48.5, 55.2, 60.8, 65.4, 68.2, 72.1, 78.4, 80.2, 82.5, 35.2, 22.4, 18.8, 20.1, 21.5, 22.8, 24.2, 23.5, 24.8, 26.1, 27.4, 26.8, 28.1, 29.4, 30.2, 31.1, 32.0, 33.2],
        "core": ["023135106","46625H100","81141R100","594918104","30303M102","02079K305","38150F107","59001A102","63935N107","09073M104"],
        "positions": (50, 100),
        "start_q": 0,
    },
    "Coatue Management": {
        "cik": "1418814",
        "entity_name": "COATUE MANAGEMENT LLC",
        "description": "Founded 1999 by Philippe Laffont (ex-Tiger Mgmt). Technology-focused hedge fund.",
        "aum_bn": [8.2, 10.4, 13.8, 18.2, 24.5, 30.1, 36.8, 42.5, 45.2, 38.5, 48.2, 52.5, 48.8, 54.2, 58.5, 62.8, 65.4, 68.2, 72.5, 75.8, 78.2, 42.5, 38.8, 42.1, 44.5, 46.8, 49.2, 51.5, 50.2, 52.5, 54.8, 56.5, 55.2, 57.5, 59.8, 61.5, 63.2, 65.5, 67.8],
        "core": ["09073M104","63935N107","30303M102","67066G104","88160R101","25809K105","594918104","883556100","15135B101","84470P109"],
        "positions": (35, 65),
        "start_q": 0,
    },
    "ValueAct Capital": {
        "cik": "1111874",
        "entity_name": "VALUEACT CAPITAL MANAGEMENT LP",
        "description": "San Francisco-based activist value fund, founded 2000 by Jeff Ubben. 5-8 large concentrated positions.",
        "aum_bn": [6.2, 7.1, 7.8, 8.4, 8.8, 9.2, 9.5, 9.8, 9.2, 7.8, 8.5, 8.8, 8.2, 8.5, 8.8, 9.0, 9.2, 9.5, 9.2, 8.8, 8.5, 6.2, 6.5, 6.8, 7.0, 7.2, 7.5, 7.8, 7.5, 7.8, 8.0, 8.2, 8.0, 8.2, 8.5, 8.7, 9.0, 9.2, 9.5],
        "core": ["594918104","812350106","84470P109","428236103","46090E103","780259107","03073E105","589331107"],
        "positions": (5, 10),
        "start_q": 0,
    },
    "Soroban Capital Partners": {
        "cik": "1548198",
        "entity_name": "SOROBAN CAPITAL PARTNERS LP",
        "description": "Founded 2010 by Eric Mandelblatt (ex-TPG-Axon). Concentrated global equity.",
        "aum_bn": [2.1, 2.8, 3.8, 5.2, 6.8, 8.2, 9.5, 10.8, 11.2, 9.5, 11.8, 12.5, 11.8, 12.8, 13.5, 14.2, 14.8, 15.2, 15.8, 16.2, 16.5, 10.2, 11.5, 12.2, 12.8, 13.2, 13.8, 14.2, 13.8, 14.2, 14.8, 15.2, 14.8, 15.2, 15.8, 16.2, 16.5, 16.8, 17.2],
        "core": ["02079K305","023135106","09857L108","594918104","46090E103","92826C839","530307107","63935N107","531134104"],
        "positions": (15, 30),
        "start_q": 0,
    },
    "Surgo Capital": {
        "cik": None,
        "entity_name": "SURGO CAPITAL MANAGEMENT LLC",
        "description": "Surgo Capital Management hedge fund.",
        "aum_bn": [0.8, 1.1, 1.5, 2.0, 2.5, 3.0, 3.6, 4.1, 4.2, 3.5, 4.2, 4.8, 4.5, 5.0, 5.4, 5.8, 6.1, 6.4, 6.8, 7.1, 7.3, 4.8, 5.2, 5.6, 5.9, 6.2, 6.5, 6.8, 6.5, 6.8, 7.1, 7.4, 7.2, 7.5, 7.8, 8.0, 8.2, 8.4, 8.6],
        "core": ["45867G101","531134104","589331107","09075V102","15135B101","594918104","023135106","81762P102","025816109"],
        "positions": (20, 40),
        "start_q": 0,
    },
    "Whale Rock Capital": {
        "cik": "1516655",
        "entity_name": "WHALE ROCK CAPITAL MANAGEMENT LLC",
        "description": "Founded 2012 by Alex Sacerdote (ex-Fidelity). High-conviction technology and growth investing.",
        "aum_bn": [1.2, 1.8, 2.5, 3.5, 4.8, 6.2, 7.8, 9.2, 10.5, 8.8, 11.2, 12.5, 11.8, 13.2, 14.5, 15.8, 16.8, 17.5, 18.8, 19.5, 20.2, 10.5, 11.8, 12.8, 13.5, 14.2, 14.8, 15.5, 15.0, 15.8, 16.4, 17.0, 16.6, 17.2, 17.8, 18.2, 18.6, 19.0, 19.5],
        "core": ["09073M104","25809K105","63935N107","30303M102","81762P102","883556100","44891N208","15135B101","49338L103","023135106"],
        "positions": (30, 55),
        "start_q": 0,
    },
    "Ruane Cunniff & Goldfarb": {
        "cik": "315066",
        "entity_name": "RUANE CUNNIFF & GOLDFARB INC",
        "description": "Manages the Sequoia Fund since 1970. Deeply concentrated, long-term value investing in quality compounders.",
        "aum_bn": [6.5, 7.1, 7.5, 7.8, 8.0, 8.3, 8.5, 8.8, 8.5, 7.2, 8.0, 8.4, 8.1, 8.5, 8.8, 9.0, 9.2, 9.4, 9.6, 9.8, 9.5, 7.2, 7.8, 8.1, 8.4, 8.6, 8.8, 9.0, 8.8, 9.0, 9.2, 9.4, 9.2, 9.4, 9.6, 9.8, 10.0, 10.2, 10.4],
        "core": ["09857L108","023135106","780259107","594918104","45867G101","023135106","531134104","46090E103","55354G100"],
        "positions": (12, 22),
        "start_q": 0,
    },
    "Lone Pine Capital": {
        "cik": "1061165",
        "entity_name": "LONE PINE CAPITAL LLC",
        "description": "Founded 1997 by Steve Mandel (ex-Tiger Mgmt). Long/short global equity, technology and consumer focus.",
        "aum_bn": [10.2, 12.5, 15.2, 18.8, 22.5, 26.2, 30.5, 34.2, 36.5, 28.5, 34.2, 38.5, 36.2, 40.5, 43.8, 46.2, 48.5, 50.2, 52.5, 54.2, 55.8, 28.5, 25.2, 22.5, 24.8, 26.2, 27.8, 29.5, 28.8, 30.2, 31.5, 32.8, 32.2, 33.5, 34.8, 35.5, 36.2, 36.8, 37.5],
        "core": ["023135106","02079K305","594918104","30303M102","63935N107","09073M104","90353T100","009375505","82811L101","038222105"],
        "positions": (35, 60),
        "start_q": 0,
    },
    "GreenOaks Capital": {
        "cik": "1540159",
        "entity_name": "GREENOAKS CAPITAL PARTNERS LLC",
        "description": "Founded 2012 by Neil Mehta. Extremely concentrated (5-10 positions), long-term compounders in tech.",
        "aum_bn": [0.8, 1.2, 1.8, 2.5, 3.4, 4.5, 5.8, 7.2, 8.5, 7.0, 8.8, 9.5, 8.8, 9.8, 10.5, 11.2, 11.8, 12.2, 12.8, 13.2, 13.5, 8.5, 9.2, 9.8, 10.2, 10.6, 11.0, 11.4, 11.0, 11.5, 12.0, 12.4, 12.0, 12.5, 13.0, 13.4, 13.8, 14.2, 14.6],
        "core": ["49338L103","029912201","82811L101","81762P102","023135106","09857L108","44891N208","G0593M107"],
        "positions": (5, 12),
        "start_q": 0,
    },
}


def make_aum_value(profile, q_idx):
    """Interpolate AUM value for a given quarter index."""
    aum_list = profile["aum_bn"]
    if q_idx >= len(aum_list):
        v = aum_list[-1]
    elif q_idx < 0:
        return 0
    else:
        v = aum_list[q_idx]
    if v == 0:
        return 0
    # Add ±5% random noise
    noise = 1 + random.uniform(-0.05, 0.05)
    return v * 1e9 * noise


def generate_holdings(profile, total_value, q_idx):
    """Generate a realistic set of holdings for a fund in a given quarter."""
    core = profile["core"]
    min_pos, max_pos = profile["positions"]
    n_pos = random.randint(min_pos, max_pos)

    all_cusips = list(STOCKS.keys())
    # Core stocks weighted higher
    pool = core * 5 + [c for c in all_cusips if c not in core]
    pool = list(dict.fromkeys(pool))  # deduplicate preserving order
    selected = pool[:n_pos]
    # Top 10 get higher weights (simulate concentration)
    n_top = min(10, len(selected))
    weights_top = sorted([random.uniform(3, 12) for _ in range(n_top)], reverse=True)
    weights_rest = [random.uniform(0.5, 3) for _ in range(len(selected) - n_top)]
    weights = weights_top + weights_rest
    total_w = sum(weights)

    holdings = []
    for i, cusip in enumerate(selected):
        if cusip not in STOCKS:
            continue
        name, ticker = STOCKS[cusip]
        w = weights[i] / total_w
        value = total_value * w
        # Rough share estimate (fictional price of $100-2000)
        price = random.uniform(100, 2000)
        shares = int(value / price)
        holdings.append({
            "name": name,
            "cusip": cusip,
            "value": int(value),
            "shares": shares,
        })

    holdings.sort(key=lambda x: -x["value"])
    total = sum(h["value"] for h in holdings)
    for h in holdings:
        h["pct"] = round(h["value"] / total * 100, 4) if total > 0 else 0
    return holdings


def build_fund_data():
    """Generate complete fund data for all quarters."""
    all_data = {}

    for fund_name, profile in FUND_PROFILES.items():
        filings = []
        start_q = profile["start_q"]

        for i, period in enumerate(ALL_QUARTERS):
            if i < start_q:
                continue
            total_value = make_aum_value(profile, i)
            if total_value < 1e8:  # skip if < $100M (fund not yet started)
                continue

            holdings = generate_holdings(profile, total_value, i)

            filings.append({
                "period": period,
                "filed": period[:4] + "-" + str(int(period[5:7]) + 2).zfill(2) + "-14",
                "total_value": int(total_value),
                "num_holdings": len(holdings),
                "holdings": holdings[:200],
            })

        # Build derived metrics
        value_trend = [{"period": f["period"], "value": f["total_value"]} for f in filings]
        position_trend = [{"period": f["period"], "count": f["num_holdings"]} for f in filings]

        turnover = []
        for j in range(1, len(filings)):
            prev = {h["cusip"] for h in filings[j-1]["holdings"]}
            curr = {h["cusip"] for h in filings[j]["holdings"]}
            turnover.append({
                "period": filings[j]["period"],
                "new": len(curr - prev),
                "removed": len(prev - curr),
            })

        latest = filings[-1] if filings else None

        all_data[fund_name] = {
            "cik": profile["cik"],
            "entity_name": profile["entity_name"],
            "description": profile["description"],
            "filings": filings,
            "value_trend": value_trend,
            "position_trend": position_trend,
            "turnover": turnover,
            "latest_period": latest["period"] if latest else None,
            "latest_value": latest["total_value"] if latest else 0,
            "latest_num_positions": latest["num_holdings"] if latest else 0,
            "latest_top10": latest["holdings"][:10] if latest else [],
            "top10_concentration": round(
                sum(h["value"] for h in latest["holdings"][:10]) / latest["total_value"] * 100, 1
            ) if latest and latest["total_value"] > 0 else 0,
        }

    return all_data


def compute_metrics(all_data):
    """Compute cross-fund analytics."""
    from collections import defaultdict

    cusip_info = defaultdict(lambda: {"name": "", "funds": [], "total_value": 0})
    cusip_by_fund = defaultdict(dict)

    for fund_name, fund in all_data.items():
        if not fund.get("filings"):
            continue
        latest = fund["filings"][-1]
        for h in latest["holdings"]:
            c = h.get("cusip", "")
            if not c:
                continue
            if not cusip_info[c]["name"]:
                cusip_info[c]["name"] = h["name"]
            if fund_name not in cusip_info[c]["funds"]:
                cusip_info[c]["funds"].append(fund_name)
            cusip_info[c]["total_value"] += h["value"]
            cusip_by_fund[c][fund_name] = {"value": h["value"], "pct": h["pct"], "shares": h["shares"]}

    cross_holdings = [
        {
            "cusip": c,
            "name": info["name"],
            "num_funds": len(info["funds"]),
            "funds": info["funds"],
            "total_value": info["total_value"],
            "by_fund": cusip_by_fund[c],
        }
        for c, info in cusip_info.items()
        if len(info["funds"]) >= 2
    ]
    cross_holdings.sort(key=lambda x: (-x["num_funds"], -x["total_value"]))

    fund_names = [n for n, f in all_data.items() if f.get("filings")]
    overlap = {}
    for fa in fund_names:
        overlap[fa] = {}
        a_set = {h["cusip"] for h in all_data[fa]["filings"][-1]["holdings"] if h.get("cusip")}
        for fb in fund_names:
            b_set = {h["cusip"] for h in all_data[fb]["filings"][-1]["holdings"] if h.get("cusip")}
            union = len(a_set | b_set)
            inter = len(a_set & b_set)
            overlap[fa][fb] = round(inter / union * 100, 1) if union > 0 else 0

    return {
        "cross_holdings": cross_holdings[:50],
        "overlap": overlap,
        "fund_names": fund_names,
    }


def main():
    output = "13f_demo_report.html"

    print("Generating demo 13F dashboard...")
    all_data = build_fund_data()
    metrics = compute_metrics(all_data)

    # Print summary
    print(f"\n{'─'*60}")
    for name, fund in sorted(all_data.items(), key=lambda x: -(x[1].get("latest_value") or 0)):
        qs = len(fund.get("filings", []))
        aum = fund.get("latest_value", 0) / 1e9
        print(f"  {name:35s}  {qs:2d} quarters  ${aum:.1f}B")
    print(f"{'─'*60}\n")

    # Import HTML generator from analyze_13f.py
    sys.path.insert(0, str(Path(__file__).parent))
    try:
        from analyze_13f import generate_html
        generate_html(all_data, metrics, output)
        print(f"Demo report written to: {output}")
        print("Open in your browser to explore the full dashboard.\n")
        print("NOTE: This uses realistic synthetic data based on publicly known")
        print("fund information. Run analyze_13f.py to fetch actual SEC filings.\n")
    except ImportError as e:
        print(f"Error importing analyze_13f: {e}")
        print("Make sure analyze_13f.py is in the same directory.")


if __name__ == "__main__":
    main()
