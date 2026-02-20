#!/usr/bin/env python3
"""
SEC 13F Filing Analyzer
=======================
Fetches and analyzes 10 years of historical SEC 13F filings for major hedge funds.
Generates an interactive HTML dashboard with portfolio analytics.

Usage:
    python analyze_13f.py                    # analyze all funds
    python analyze_13f.py --funds "Tiger Global,Coatue"
    python analyze_13f.py --output my_report.html
    python analyze_13f.py --no-cache         # force fresh fetch
"""

import argparse
import json
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime
from xml.etree import ElementTree as ET

import requests

# ─── Configuration ───────────────────────────────────────────────────────────

START_YEAR = 2015
CACHE_FILE = "13f_cache.json"
OUTPUT_FILE = "13f_report.html"

# SEC requires a User-Agent header identifying the requester
SEC_HEADERS = {
    "User-Agent": "TBCapital-Research contact@tbcapital.com.br",
    "Accept-Encoding": "gzip, deflate",
}
RATE_DELAY = 0.15  # 150ms between requests — SEC allows up to 10/sec

# ─── Fund Registry ───────────────────────────────────────────────────────────
# CIK numbers (10-digit, leading zeros optional) for SEC EDGAR.
# None = will attempt auto-discovery via full-text search.

FUNDS = {
    "Egerton Capital": {
        "cik": None,
        "q": "Egerton Capital Limited",
        "description": "London-based long/short equity, founded 1994 by John Armitage",
    },
    "TCI Fund Management": {
        "cik": "1346807",
        "q": "TCI Fund Management",
        "description": "London-based activist fund, founded 2003 by Chris Hohn",
    },
    "Durable Capital Partners": {
        "cik": "1775850",
        "q": "Durable Capital Partners",
        "description": "Founded 2019 by Henry Ellenbogen (ex-T. Rowe Price)",
    },
    "RV Capital": {
        "cik": None,
        "q": "RV Capital",
        "description": "German-based concentrated long-term equity fund",
    },
    "D1 Capital Partners": {
        "cik": "1741830",
        "q": "D1 Capital Partners",
        "description": "Founded 2018 by Dan Sundheim (ex-Viking Global)",
    },
    "Tiger Global Management": {
        "cik": "1167483",
        "q": "Tiger Global Management",
        "description": "Founded 2001 by Chase Coleman, Tiger Cub hedge fund",
    },
    "Coatue Management": {
        "cik": "1418814",
        "q": "Coatue Management",
        "description": "Founded 1999 by Philippe Laffont, tech-focused hedge fund",
    },
    "ValueAct Capital": {
        "cik": "1111874",
        "q": "ValueAct Capital",
        "description": "San Francisco-based activist value fund, founded 2000",
    },
    "Soroban Capital Partners": {
        "cik": "1548198",
        "q": "Soroban Capital Partners",
        "description": "Founded 2010 by Eric Mandelblatt (ex-TPG-Axon)",
    },
    "Surgo Capital": {
        "cik": None,
        "q": "Surgo Capital Management",
        "description": "Surgo Capital Management hedge fund",
    },
    "Whale Rock Capital": {
        "cik": "1516655",
        "q": "Whale Rock Capital Management",
        "description": "Founded 2012 by Alex Sacerdote (ex-Fidelity)",
    },
    "Ruane Cunniff & Goldfarb": {
        "cik": "315066",
        "q": "Ruane Cunniff Goldfarb",
        "description": "Value managers of the Sequoia Fund, founded 1970",
    },
    "Lone Pine Capital": {
        "cik": "1061165",
        "q": "Lone Pine Capital",
        "description": "Founded 1997 by Steve Mandel (ex-Tiger Management)",
    },
    "GreenOaks Capital": {
        "cik": "1540159",
        "q": "GreenOaks Capital Partners",
        "description": "Founded 2012 by Neil Mehta, concentrated long-term growth",
    },
}


# ─── SEC EDGAR API Helpers ───────────────────────────────────────────────────

def edgar_get(url, retries=3):
    """Rate-limited GET request to SEC EDGAR with retry logic."""
    for attempt in range(retries):
        time.sleep(RATE_DELAY)
        try:
            r = requests.get(url, headers=SEC_HEADERS, timeout=30)
            if r.status_code == 429:
                wait = 2 ** attempt * 2
                print(f"    Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            r.raise_for_status()
            return r
        except requests.exceptions.RequestException as e:
            if attempt == retries - 1:
                raise
            time.sleep(2 ** attempt)
    return None


def search_cik(query):
    """Search EDGAR for a company CIK using full-text search."""
    url = (
        f"https://efts.sec.gov/LATEST/search-index?q=%22{requests.utils.quote(query)}%22"
        f"&forms=13F-HR&dateRange=custom&startdt={START_YEAR}-01-01&enddt=2025-12-31"
    )
    try:
        data = edgar_get(url).json()
        hits = data.get("hits", {}).get("hits", [])
        if hits:
            src = hits[0]["_source"]
            # entity_id is the CIK
            cik = src.get("entity_id", "").lstrip("0")
            if cik:
                return cik
    except Exception as e:
        print(f"    Search failed for '{query}': {e}")
    return None


def get_submissions(cik):
    """Get all submissions for a CIK."""
    padded = str(cik).zfill(10)
    url = f"https://data.sec.gov/submissions/CIK{padded}.json"
    return edgar_get(url).json()


def get_13f_filings(cik):
    """
    Return list of 13F-HR filings since START_YEAR.
    Handles EDGAR pagination (older filings in additional files).
    """
    data = get_submissions(cik)
    entity_name = data.get("name", "Unknown")

    all_filings = []

    def _extract_filings(recent):
        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        accessions = recent.get("accessionNumber", [])
        periods = recent.get("reportDate", [])
        for i, form in enumerate(forms):
            if form in ("13F-HR", "13F-HR/A"):
                period = (periods[i] if i < len(periods) else dates[i][:10]) or ""
                year = int(period[:4]) if len(period) >= 4 else 0
                if year >= START_YEAR:
                    all_filings.append({
                        "form": form,
                        "filed": dates[i] if i < len(dates) else "",
                        "period": period,
                        "accession": accessions[i] if i < len(accessions) else "",
                    })

    # Recent filings
    recent = data.get("filings", {}).get("recent", {})
    _extract_filings(recent)

    # Older paginated filings
    for page_info in data.get("filings", {}).get("files", []):
        fname = page_info.get("name", "")
        if fname:
            try:
                padded = str(cik).zfill(10)
                page_url = f"https://data.sec.gov/submissions/CIK{padded}/{fname}"
                page_data = edgar_get(page_url).json()
                _extract_filings(page_data)
            except Exception:
                pass

    return entity_name, all_filings


def find_infotable_url(cik, accession_raw):
    """
    Find the URL of the 13F information table XML within a filing.
    accession_raw is formatted like '0001234567-24-123456'
    """
    accession_nodash = accession_raw.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_raw}/"
    idx_url = f"{base}{accession_nodash}-index.htm"

    try:
        r = edgar_get(idx_url)
        text = r.text

        # Priority patterns for infotable file
        patterns = [
            r'href="([^"]*(?:infotable|informationtable|13finfotable|form13finfotable)[^"]*\.xml)"',
            r'href="([^"]*\.xml)"',
        ]
        for pat in patterns:
            matches = re.findall(pat, text, re.IGNORECASE)
            for m in matches:
                if "primary_doc" not in m.lower() and "xslt" not in m.lower():
                    # Build absolute URL
                    if m.startswith("http"):
                        return m
                    fname = m.lstrip("/").split("/")[-1]
                    return base + fname
    except Exception as e:
        pass

    # Fallback: try common file names
    for candidate in [
        f"{accession_nodash}-infotable.xml",
        "infotable.xml",
        "form13fInfoTable.xml",
        "13fInfoTable.xml",
    ]:
        url = base + candidate
        try:
            r = edgar_get(url)
            if r.status_code == 200 and "<infoTable" in r.text.lower():
                return url
        except Exception:
            pass

    return None


def parse_13f_xml(xml_text):
    """
    Parse 13F information table XML.
    Handles multiple namespace variants used over the years.
    Returns list of holdings dicts.
    """
    holdings = []

    # Clean up potential entity issues
    xml_text = re.sub(r'&(?!(amp|lt|gt|quot|apos);)', '&amp;', xml_text)

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"      XML parse error: {e}")
        return holdings

    # Detect namespace
    ns_match = re.search(r'xmlns(?::\w+)?="([^"]*thirteenf[^"]*)"', xml_text[:3000])
    ns = ns_match.group(1) if ns_match else None

    def find_tag(parent, tag):
        """Find element by tag, trying with/without namespace."""
        candidates = [
            tag, tag.upper(), tag[0].upper() + tag[1:],
        ]
        for t in candidates:
            elem = parent.find(f"{{{ns}}}{t}" if ns else t)
            if elem is None:
                elem = parent.find(f".//{{{ns}}}{t}" if ns else f".//{t}")
            if elem is not None:
                return elem
        return None

    def find_text(parent, tag):
        elem = find_tag(parent, tag)
        return elem.text.strip() if elem is not None and elem.text else ""

    # Find all infoTable elements
    info_tables = []
    for tag in ["infoTable", "InfoTable", "INFOTABLE"]:
        path = f".//{{{ns}}}{tag}" if ns else f".//{tag}"
        found = root.findall(path)
        if found:
            info_tables = found
            break

    for table in info_tables:
        name = find_text(table, "nameOfIssuer")
        cusip = find_text(table, "cusip")
        value_str = find_text(table, "value")

        # Shares nested inside shrsOrPrnAmt
        shares_elem = find_tag(table, "sshPrnamt")
        shares_str = shares_elem.text.strip() if shares_elem is not None and shares_elem.text else "0"

        if name and value_str:
            try:
                value_k = int(re.sub(r'[^\d]', '', value_str))
                shares = int(re.sub(r'[^\d]', '', shares_str))
                holdings.append({
                    "name": name.title(),
                    "cusip": cusip,
                    "value": value_k * 1000,  # convert $K → $
                    "shares": shares,
                })
            except (ValueError, TypeError):
                pass

    return holdings


# ─── Data Fetching ───────────────────────────────────────────────────────────

def fetch_fund_data(fund_name, config, cache):
    """Fetch all 13F filings for a fund. Returns structured data dict."""

    print(f"\n{'─'*60}")
    print(f"  {fund_name}")
    print(f"{'─'*60}")

    # Resolve CIK
    cik = config.get("cik")
    if not cik:
        print(f"  Searching for CIK via '{config['q']}'...")
        cik = search_cik(config["q"])
        if not cik:
            print(f"  ✗ CIK not found — skipping {fund_name}")
            return None
        print(f"  Found CIK: {cik}")

    # Fetch filing list
    try:
        entity_name, filings_list = get_13f_filings(cik)
        print(f"  Entity: {entity_name}")
    except Exception as e:
        print(f"  ✗ Error getting filings: {e}")
        return None

    if not filings_list:
        print(f"  ✗ No 13F filings found since {START_YEAR}")
        return None

    # Deduplicate by period — prefer amendments (13F-HR/A)
    by_period = {}
    for f in filings_list:
        p = f["period"]
        if p not in by_period or f["form"] == "13F-HR/A":
            by_period[p] = f
    quarters = sorted(by_period.values(), key=lambda x: x["period"])
    print(f"  Found {len(quarters)} quarters of 13F data ({quarters[0]['period']} → {quarters[-1]['period']})")

    result = {
        "cik": str(cik),
        "entity_name": entity_name,
        "description": config.get("description", ""),
        "filings": [],
    }

    for i, filing in enumerate(quarters):
        period = filing["period"]
        accession = filing["accession"]

        # Check cache
        cache_key = f"{cik}_{accession}"
        if cache_key in cache:
            result["filings"].append(cache[cache_key])
            print(f"  [{i+1:2d}/{len(quarters)}] {period}  (cached ✓)")
            continue

        print(f"  [{i+1:2d}/{len(quarters)}] {period} ... ", end="", flush=True)

        try:
            url = find_infotable_url(cik, accession)
            if not url:
                print("no infotable found")
                continue

            r = edgar_get(url)
            holdings = parse_13f_xml(r.text)

            if not holdings:
                print("no holdings parsed")
                continue

            total_value = sum(h["value"] for h in holdings)
            holdings.sort(key=lambda x: x["value"], reverse=True)

            for h in holdings:
                h["pct"] = round(h["value"] / total_value * 100, 4) if total_value > 0 else 0

            filing_data = {
                "period": period,
                "filed": filing["filed"],
                "total_value": total_value,
                "num_holdings": len(holdings),
                "holdings": holdings[:200],  # cap at 200 per filing for size
            }

            result["filings"].append(filing_data)
            cache[cache_key] = filing_data
            print(f"✓  {len(holdings)} positions | ${total_value/1e9:.2f}B")

        except Exception as e:
            print(f"error: {e}")

    return result if result["filings"] else None


# ─── Analysis ────────────────────────────────────────────────────────────────

def compute_metrics(all_data):
    """Compute cross-fund and per-fund analytics."""

    # --- Per-fund metrics ---
    for name, fund in all_data.items():
        filings = fund.get("filings", [])
        if not filings:
            continue

        # Portfolio value trend
        fund["value_trend"] = [
            {"period": f["period"], "value": f["total_value"]}
            for f in filings
        ]

        # Top 10 holdings in latest quarter
        latest = filings[-1]
        fund["latest_period"] = latest["period"]
        fund["latest_value"] = latest["total_value"]
        fund["latest_top10"] = latest["holdings"][:10]
        fund["latest_num_positions"] = latest["num_holdings"]

        # Concentration: % in top 10
        top10_val = sum(h["value"] for h in latest["holdings"][:10])
        fund["top10_concentration"] = round(top10_val / latest["total_value"] * 100, 1) if latest["total_value"] > 0 else 0

        # Position count trend
        fund["position_trend"] = [
            {"period": f["period"], "count": f["num_holdings"]}
            for f in filings
        ]

        # Turnover: new + removed positions quarter-over-quarter
        turnover = []
        for i in range(1, len(filings)):
            prev_cusips = {h["cusip"] for h in filings[i-1]["holdings"] if h["cusip"]}
            curr_cusips = {h["cusip"] for h in filings[i]["holdings"] if h["cusip"]}
            new_pos = curr_cusips - prev_cusips
            removed = prev_cusips - curr_cusips
            turnover.append({
                "period": filings[i]["period"],
                "new": len(new_pos),
                "removed": len(removed),
            })
        fund["turnover"] = turnover

    # --- Cross-fund analysis ---

    # Count how many funds hold each stock (by CUSIP) in latest filings
    cusip_count = defaultdict(lambda: {"name": "", "funds": [], "total_value": 0})
    cusip_by_fund = defaultdict(dict)  # cusip → {fund: {value, pct, shares}}

    for fund_name, fund in all_data.items():
        if not fund.get("filings"):
            continue
        latest = fund["filings"][-1]
        for h in latest["holdings"]:
            c = h.get("cusip", "")
            if not c:
                continue
            if not cusip_count[c]["name"]:
                cusip_count[c]["name"] = h["name"]
            if fund_name not in cusip_count[c]["funds"]:
                cusip_count[c]["funds"].append(fund_name)
            cusip_count[c]["total_value"] += h["value"]
            cusip_by_fund[c][fund_name] = {
                "value": h["value"],
                "pct": h["pct"],
                "shares": h["shares"],
            }

    # Top stocks by number of funds
    cross_holdings = []
    for cusip, info in cusip_count.items():
        if len(info["funds"]) >= 2:
            cross_holdings.append({
                "cusip": cusip,
                "name": info["name"],
                "num_funds": len(info["funds"]),
                "funds": info["funds"],
                "total_value": info["total_value"],
                "by_fund": cusip_by_fund[cusip],
            })
    cross_holdings.sort(key=lambda x: (-x["num_funds"], -x["total_value"]))

    # Portfolio overlap matrix (Jaccard index on CUSIPs)
    fund_names = [n for n, f in all_data.items() if f.get("filings")]
    overlap = {}
    for i, fa in enumerate(fund_names):
        overlap[fa] = {}
        a_cusips = {h["cusip"] for h in all_data[fa]["filings"][-1]["holdings"] if h.get("cusip")}
        for j, fb in enumerate(fund_names):
            b_cusips = {h["cusip"] for h in all_data[fb]["filings"][-1]["holdings"] if h.get("cusip")}
            union = len(a_cusips | b_cusips)
            inter = len(a_cusips & b_cusips)
            overlap[fa][fb] = round(inter / union * 100, 1) if union > 0 else 0

    return {
        "cross_holdings": cross_holdings[:50],
        "overlap": overlap,
        "fund_names": fund_names,
    }


# ─── HTML Report Generator ───────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>13F Analysis — Major Hedge Funds 2015–2025</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.4/dist/chart.umd.min.js"></script>
<style>
:root {
  --bg: #F7F5F0;
  --bg-warm: #EDE9E0;
  --bg-card: #FEFDFB;
  --text: #1A1A18;
  --text-muted: #6B6760;
  --text-light: #9C978E;
  --accent: #2C3E2D;
  --accent-light: #3D5A3E;
  --border: #D8D3C8;
  --positive: #2C6E49;
  --negative: #8B2635;
  --serif: 'Georgia', serif;
  --sans: -apple-system, 'DM Sans', 'Segoe UI', sans-serif;
}
* { margin:0; padding:0; box-sizing:border-box; }
html { scroll-behavior:smooth; }
body { font-family:var(--sans); background:var(--bg); color:var(--text); font-size:14px; line-height:1.6; -webkit-font-smoothing:antialiased; }

/* NAV */
nav { position:fixed; top:0; left:0; right:0; z-index:100; height:64px; display:flex; align-items:center; justify-content:space-between; padding:0 40px; background:rgba(247,245,240,0.92); backdrop-filter:blur(20px); border-bottom:1px solid var(--border); }
.nav-brand { font-family:var(--serif); font-size:18px; color:var(--accent); letter-spacing:0.02em; }
.nav-tabs { display:flex; gap:4px; }
.tab-btn { background:none; border:none; padding:8px 18px; border-radius:4px; font-size:13px; font-weight:500; color:var(--text-muted); cursor:pointer; transition:all 0.2s; }
.tab-btn:hover { background:var(--bg-warm); color:var(--text); }
.tab-btn.active { background:var(--accent); color:#fff; }
.nav-meta { font-size:12px; color:var(--text-light); }

/* LAYOUT */
.main { padding-top:80px; max-width:1400px; margin:0 auto; padding-left:24px; padding-right:24px; padding-bottom:60px; }
.page { display:none; }
.page.active { display:block; }

/* CARDS */
.cards-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(240px, 1fr)); gap:16px; margin:24px 0; }
.card { background:var(--bg-card); border:1px solid var(--border); border-radius:6px; padding:20px; }
.card-label { font-size:11px; font-weight:600; letter-spacing:0.08em; text-transform:uppercase; color:var(--text-light); margin-bottom:6px; }
.card-value { font-size:28px; font-family:var(--serif); color:var(--text); }
.card-sub { font-size:12px; color:var(--text-muted); margin-top:4px; }

/* SECTION TITLES */
.section-title { font-family:var(--serif); font-size:22px; color:var(--accent); margin:32px 0 8px; }
.section-sub { font-size:13px; color:var(--text-muted); margin-bottom:20px; }

/* CHART CONTAINERS */
.chart-wrap { background:var(--bg-card); border:1px solid var(--border); border-radius:6px; padding:24px; margin:16px 0; }
.chart-title { font-size:13px; font-weight:600; color:var(--text-muted); margin-bottom:16px; text-transform:uppercase; letter-spacing:0.06em; }
.chart-canvas-wrap { position:relative; height:300px; }

/* FUND CARDS GRID */
.fund-grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(300px, 1fr)); gap:16px; margin:24px 0; }
.fund-card { background:var(--bg-card); border:1px solid var(--border); border-radius:6px; padding:20px; cursor:pointer; transition:all 0.2s; }
.fund-card:hover { border-color:var(--accent); box-shadow:0 2px 8px rgba(44,62,45,0.12); }
.fund-card.active { border-color:var(--accent); background:#f0f4f0; }
.fund-name { font-family:var(--serif); font-size:16px; margin-bottom:4px; }
.fund-aum { font-size:20px; font-weight:600; color:var(--accent); }
.fund-detail { font-size:12px; color:var(--text-muted); margin-top:4px; }
.fund-desc { font-size:11px; color:var(--text-light); margin-top:8px; line-height:1.5; }

/* TABLES */
.table-wrap { overflow-x:auto; margin:16px 0; }
table { width:100%; border-collapse:collapse; font-size:13px; }
thead th { background:var(--bg-warm); border-bottom:2px solid var(--border); padding:10px 12px; text-align:left; font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.07em; color:var(--text-muted); white-space:nowrap; }
tbody td { padding:9px 12px; border-bottom:1px solid var(--border); }
tbody tr:last-child td { border-bottom:none; }
tbody tr:hover td { background:var(--bg-warm); }
.td-right { text-align:right; font-variant-numeric:tabular-nums; }
.td-bar { width:100px; }
.bar-inner { height:6px; background:var(--accent); border-radius:3px; opacity:0.7; }
.badge { display:inline-block; background:var(--bg-warm); border:1px solid var(--border); border-radius:3px; padding:1px 6px; font-size:10px; font-weight:600; color:var(--text-muted); }
.badge-green { background:#e8f4ec; border-color:#b3d9bc; color:var(--positive); }

/* FUND DETAIL */
.fund-detail-header { display:flex; justify-content:space-between; align-items:flex-start; margin:24px 0 16px; flex-wrap:wrap; gap:16px; }
.fund-selector { padding:10px 14px; border:1px solid var(--border); border-radius:4px; background:var(--bg-card); font-size:14px; color:var(--text); min-width:280px; }
.fund-stats-row { display:grid; grid-template-columns:repeat(auto-fill, minmax(160px, 1fr)); gap:12px; margin:16px 0; }
.stat-box { background:var(--bg-card); border:1px solid var(--border); border-radius:4px; padding:14px; }
.stat-label { font-size:10px; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; color:var(--text-light); margin-bottom:4px; }
.stat-value { font-size:18px; font-family:var(--serif); }

/* OVERLAP MATRIX */
.overlap-grid { overflow-x:auto; margin:16px 0; }
.overlap-table { border-collapse:collapse; font-size:11px; }
.overlap-table th { padding:6px 8px; text-align:center; font-size:10px; font-weight:600; color:var(--text-muted); white-space:nowrap; max-width:80px; overflow:hidden; text-overflow:ellipsis; }
.overlap-table td { padding:5px 8px; text-align:center; font-variant-numeric:tabular-nums; border:1px solid var(--border); border-radius:2px; font-size:11px; }

/* SEARCH */
.search-box { padding:10px 14px; border:1px solid var(--border); border-radius:4px; background:var(--bg-card); font-size:14px; color:var(--text); width:100%; max-width:400px; outline:none; }
.search-box:focus { border-color:var(--accent); }

/* RESPONSIVE */
@media(max-width:768px) {
  nav { padding:0 16px; }
  .nav-tabs { gap:2px; }
  .tab-btn { padding:6px 10px; font-size:12px; }
  .main { padding-left:12px; padding-right:12px; }
}

/* NO DATA */
.no-data { text-align:center; padding:40px; color:var(--text-muted); font-style:italic; }
</style>
</head>
<body>

<nav>
  <div class="nav-brand">13F Analysis</div>
  <div class="nav-tabs">
    <button class="tab-btn active" onclick="showTab('overview')">Overview</button>
    <button class="tab-btn" onclick="showTab('funds')">Fund Detail</button>
    <button class="tab-btn" onclick="showTab('crossfund')">Cross-Fund</button>
    <button class="tab-btn" onclick="showTab('tracker')">Stock Tracker</button>
  </div>
  <div class="nav-meta">SEC 13F Filings · 2015–2025</div>
</nav>

<div class="main">

<!-- ══════════════════════════════════════════════════════════ OVERVIEW ══ -->
<div id="tab-overview" class="page active">
  <div style="padding-top:12px">
    <h1 class="section-title" style="margin-top:8px">13F Filings — Major Hedge Funds</h1>
    <p class="section-sub">10-year analysis of SEC 13F filings · __PERIOD_RANGE__ · __FUND_COUNT__ funds tracked</p>
  </div>

  <div class="cards-grid" id="overview-cards"></div>

  <div class="chart-wrap">
    <div class="chart-title">Combined AUM Trend (Sum of Reported 13F Long Equity)</div>
    <div class="chart-canvas-wrap"><canvas id="combined-aum-chart"></canvas></div>
  </div>

  <h2 class="section-title">All Funds</h2>
  <p class="section-sub">Sorted by latest reported AUM. Click a fund for detail.</p>
  <div class="fund-grid" id="fund-cards-grid"></div>
</div>

<!-- ═══════════════════════════════════════════════════════ FUND DETAIL ══ -->
<div id="tab-funds" class="page">
  <div class="fund-detail-header">
    <div>
      <h2 class="section-title" style="margin-top:8px">Fund Detail</h2>
      <p class="section-sub">Drill into individual fund portfolios over time</p>
    </div>
    <select class="fund-selector" id="fund-select" onchange="renderFundDetail()">
      __FUND_OPTIONS__
    </select>
  </div>

  <div class="fund-stats-row" id="fund-stats-row"></div>

  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;flex-wrap:wrap" id="fund-charts-grid">
    <div class="chart-wrap">
      <div class="chart-title">Portfolio AUM ($B)</div>
      <div class="chart-canvas-wrap"><canvas id="fund-aum-chart"></canvas></div>
    </div>
    <div class="chart-wrap">
      <div class="chart-title">Number of Positions</div>
      <div class="chart-canvas-wrap"><canvas id="fund-positions-chart"></canvas></div>
    </div>
  </div>

  <div class="chart-wrap">
    <div class="chart-title">Top 10 Holdings — Latest Quarter</div>
    <div class="chart-canvas-wrap" style="height:260px"><canvas id="fund-top10-chart"></canvas></div>
  </div>

  <div class="chart-wrap">
    <div class="chart-title">Portfolio Turnover — New & Removed Positions per Quarter</div>
    <div class="chart-canvas-wrap"><canvas id="fund-turnover-chart"></canvas></div>
  </div>

  <div class="chart-wrap">
    <div class="chart-title">All Holdings — Latest Quarter</div>
    <div class="table-wrap">
      <table id="holdings-table">
        <thead>
          <tr>
            <th>#</th>
            <th>Company</th>
            <th>CUSIP</th>
            <th class="td-right">Value ($M)</th>
            <th class="td-right">Shares</th>
            <th class="td-right">% Portfolio</th>
            <th>Weight</th>
          </tr>
        </thead>
        <tbody id="holdings-tbody"></tbody>
      </table>
    </div>
  </div>
</div>

<!-- ══════════════════════════════════════════════════════ CROSS-FUND ══ -->
<div id="tab-crossfund" class="page">
  <h2 class="section-title" style="margin-top:8px">Cross-Fund Analysis</h2>
  <p class="section-sub">Holdings overlap and consensus positions across all funds — latest quarter</p>

  <div class="chart-wrap">
    <div class="chart-title">Most Widely Held Stocks (# of Funds)</div>
    <div class="chart-canvas-wrap" style="height:340px"><canvas id="cross-bar-chart"></canvas></div>
  </div>

  <h2 class="section-title">Consensus Holdings</h2>
  <p class="section-sub">Stocks held by 2+ funds in their latest 13F filing</p>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>#</th>
          <th>Company</th>
          <th>CUSIP</th>
          <th class="td-right"># Funds</th>
          <th class="td-right">Combined Value ($M)</th>
          <th>Funds Holding</th>
        </tr>
      </thead>
      <tbody id="cross-holdings-tbody"></tbody>
    </table>
  </div>

  <h2 class="section-title">Portfolio Overlap Matrix</h2>
  <p class="section-sub">Jaccard similarity — % of shared positions (by CUSIP) between pairs of funds in their latest filing</p>
  <div class="overlap-grid">
    <table class="overlap-table" id="overlap-table"></table>
  </div>
</div>

<!-- ══════════════════════════════════════════════════════ STOCK TRACKER ══ -->
<div id="tab-tracker" class="page">
  <h2 class="section-title" style="margin-top:8px">Stock Tracker</h2>
  <p class="section-sub">Search for any stock and see how all funds' positions evolved over time</p>

  <input class="search-box" id="stock-search" placeholder="Search by company name or CUSIP..." oninput="filterStockSearch()" />

  <div class="table-wrap" style="margin-top:16px">
    <table>
      <thead>
        <tr>
          <th>Company</th>
          <th>CUSIP</th>
          <th class="td-right"># Funds (latest)</th>
          <th class="td-right">Total Value ($M, latest)</th>
          <th>Funds</th>
        </tr>
      </thead>
      <tbody id="tracker-tbody"></tbody>
    </table>
  </div>

  <div id="tracker-detail" style="display:none">
    <h2 class="section-title" id="tracker-stock-name">—</h2>
    <div class="chart-wrap">
      <div class="chart-title">Position Value per Fund Over Time ($M)</div>
      <div class="chart-canvas-wrap" style="height:340px"><canvas id="tracker-chart"></canvas></div>
    </div>
  </div>
</div>

</div><!-- .main -->

<script>
// ─── Injected Data ───────────────────────────────────────────────────────────
const ALL_DATA = __ALL_DATA__;
const METRICS = __METRICS__;

// ─── Colour palette ──────────────────────────────────────────────────────────
const PALETTE = [
  '#2C3E2D','#3D5A3E','#5C8A6A','#8AB5A1','#B5D4C8',
  '#6B4E3D','#A07855','#C9A87C','#E8C99A','#F5E6D2',
  '#2D3A5A','#3D5280','#5C7AAB','#8AA5C9','#C2D5E8',
  '#5A2D2D','#804040','#AB6060','#C98888','#E8C0C0',
];

const ACCENT = '#2C3E2D';

// ─── Chart registry (for destroy before re-render) ───────────────────────────
const charts = {};
function destroyChart(id) { if (charts[id]) { charts[id].destroy(); delete charts[id]; } }

// ─── Tab navigation ──────────────────────────────────────────────────────────
function showTab(name) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  event.target.classList.add('active');

  if (name === 'funds' && !fundsInitialized) initFundsTab();
  if (name === 'crossfund' && !crossInitialized) initCrossFundTab();
  if (name === 'tracker' && !trackerInitialized) initTrackerTab();
}

// ─── Helpers ─────────────────────────────────────────────────────────────────
function fmtB(v) { return v >= 1e9 ? (v/1e9).toFixed(2)+'B' : v >= 1e6 ? (v/1e6).toFixed(1)+'M' : v.toLocaleString(); }
function fmtM(v) { return (v/1e6).toFixed(1); }
function fmtPct(v) { return v.toFixed(1)+'%'; }
function quarterLabel(p) { if(!p||p.length<7) return p; const q = Math.ceil(parseInt(p.slice(5,7))/3); return `${p.slice(0,4)} Q${q}`; }

const fundNames = Object.keys(ALL_DATA);
const fundList  = fundNames.sort((a,b) => (ALL_DATA[b].latest_value||0) - (ALL_DATA[a].latest_value||0));

// ─── OVERVIEW TAB ────────────────────────────────────────────────────────────
(function initOverview() {
  // Summary cards
  const activeFunds = fundList.filter(n => ALL_DATA[n].filings && ALL_DATA[n].filings.length);
  const totalAUM = activeFunds.reduce((s,n) => s + (ALL_DATA[n].latest_value||0), 0);
  const allCUSIPs = new Set();
  activeFunds.forEach(n => { (ALL_DATA[n].filings.slice(-1)[0]?.holdings||[]).forEach(h => h.cusip && allCUSIPs.add(h.cusip)); });

  const cards = [
    { label:'Funds Analyzed', value: activeFunds.length, sub:'with 13F filings found' },
    { label:'Combined 13F AUM', value:'$' + fmtB(totalAUM), sub:'sum of latest reported long equity' },
    { label:'Unique Stocks', value: allCUSIPs.size.toLocaleString(), sub:'across all latest portfolios' },
    { label:'Data Range', value:'10 Years', sub:'Q1 2015 – latest quarter' },
  ];

  const cardEl = document.getElementById('overview-cards');
  cards.forEach(c => {
    cardEl.innerHTML += `<div class="card">
      <div class="card-label">${c.label}</div>
      <div class="card-value">${c.value}</div>
      <div class="card-sub">${c.sub}</div>
    </div>`;
  });

  // Combined AUM chart — per quarter, sum of all funds
  const periodSet = new Set();
  activeFunds.forEach(n => (ALL_DATA[n].value_trend||[]).forEach(p => periodSet.add(p.period)));
  const periods = [...periodSet].sort();

  const combined = periods.map(p => {
    return activeFunds.reduce((s,n) => {
      const item = (ALL_DATA[n].value_trend||[]).find(x => x.period===p);
      return s + (item ? item.value : 0);
    }, 0);
  });

  const ctx = document.getElementById('combined-aum-chart').getContext('2d');
  charts['combined-aum'] = new Chart(ctx, {
    type:'line',
    data:{
      labels: periods.map(quarterLabel),
      datasets:[{
        label:'Combined 13F Long Equity ($B)',
        data: combined.map(v => +(v/1e9).toFixed(2)),
        borderColor: ACCENT, backgroundColor: 'rgba(44,62,45,0.08)',
        fill:true, tension:0.3, pointRadius:2, borderWidth:2,
      }]
    },
    options:{ responsive:true, maintainAspectRatio:false, plugins:{ legend:{display:false} }, scales:{y:{beginAtZero:false, ticks:{ callback: v => '$'+v+'B' } }} }
  });

  // Fund cards
  const grid = document.getElementById('fund-cards-grid');
  fundList.forEach((name, i) => {
    const f = ALL_DATA[name];
    if (!f.filings || !f.filings.length) return;
    grid.innerHTML += `
      <div class="fund-card" onclick="openFundDetail('${name.replace(/'/g,"\\'")}')">
        <div class="fund-name">${name}</div>
        <div class="fund-aum">$${fmtB(f.latest_value||0)}</div>
        <div class="fund-detail">
          ${f.latest_period ? quarterLabel(f.latest_period) : '—'} ·
          ${f.latest_num_positions||0} positions ·
          Top 10: ${f.top10_concentration||0}%
        </div>
        <div class="fund-desc">${f.description||''}</div>
      </div>`;
  });
})();

function openFundDetail(name) {
  showTab('funds');
  // Update tab buttons manually
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.querySelector('.tab-btn:nth-child(2)').classList.add('active');
  if (!fundsInitialized) initFundsTab();
  document.getElementById('fund-select').value = name;
  renderFundDetail();
}

// ─── FUND DETAIL TAB ─────────────────────────────────────────────────────────
let fundsInitialized = false;
function initFundsTab() {
  fundsInitialized = true;
  renderFundDetail();
}

function renderFundDetail() {
  const name = document.getElementById('fund-select').value;
  const fund = ALL_DATA[name];
  if (!fund || !fund.filings || !fund.filings.length) {
    document.getElementById('fund-stats-row').innerHTML = '<div class="no-data">No data available for this fund.</div>';
    return;
  }

  const filings = fund.filings;
  const latest = filings[filings.length-1];

  // Stats row
  document.getElementById('fund-stats-row').innerHTML = `
    <div class="stat-box"><div class="stat-label">Latest AUM</div><div class="stat-value">$${fmtB(fund.latest_value||0)}</div></div>
    <div class="stat-box"><div class="stat-label">Positions</div><div class="stat-value">${fund.latest_num_positions||0}</div></div>
    <div class="stat-box"><div class="stat-label">Top 10 Weight</div><div class="stat-value">${fund.top10_concentration||0}%</div></div>
    <div class="stat-box"><div class="stat-label">Latest Quarter</div><div class="stat-value">${quarterLabel(fund.latest_period)}</div></div>
    <div class="stat-box"><div class="stat-label">Total Quarters</div><div class="stat-value">${filings.length}</div></div>
    <div class="stat-box"><div class="stat-label">Entity</div><div class="stat-value" style="font-size:12px">${fund.entity_name||'—'}</div></div>
  `;

  const vt = fund.value_trend || [];
  const pt = fund.position_trend || [];
  const labels = vt.map(x => quarterLabel(x.period));

  // AUM chart
  destroyChart('fund-aum');
  charts['fund-aum'] = new Chart(document.getElementById('fund-aum-chart').getContext('2d'), {
    type:'line',
    data:{ labels, datasets:[{ label:'AUM ($B)', data:vt.map(x => +(x.value/1e9).toFixed(2)),
      borderColor:ACCENT, backgroundColor:'rgba(44,62,45,0.08)', fill:true, tension:0.3, pointRadius:2, borderWidth:2 }] },
    options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}},
      scales:{y:{beginAtZero:false, ticks:{callback:v=>'$'+v+'B'}}} }
  });

  // Positions chart
  const plabels = pt.map(x => quarterLabel(x.period));
  destroyChart('fund-positions');
  charts['fund-positions'] = new Chart(document.getElementById('fund-positions-chart').getContext('2d'), {
    type:'line',
    data:{ labels:plabels, datasets:[{ label:'# Positions', data:pt.map(x=>x.count),
      borderColor:'#6B4E3D', backgroundColor:'rgba(107,78,61,0.08)', fill:true, tension:0.3, pointRadius:2, borderWidth:2 }] },
    options:{ responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}},
      scales:{y:{beginAtZero:false}} }
  });

  // Top 10 bar
  const top10 = (fund.latest_top10||[]);
  destroyChart('fund-top10');
  charts['fund-top10'] = new Chart(document.getElementById('fund-top10-chart').getContext('2d'), {
    type:'bar',
    data:{
      labels: top10.map(h=>h.name),
      datasets:[{ label:'% Portfolio', data:top10.map(h=>h.pct),
        backgroundColor: top10.map((_,i)=>PALETTE[i%PALETTE.length]+'cc'), borderRadius:3 }]
    },
    options:{ indexAxis:'y', responsive:true, maintainAspectRatio:false, plugins:{legend:{display:false}},
      scales:{x:{ticks:{callback:v=>v+'%'}}} }
  });

  // Turnover chart
  const to = fund.turnover || [];
  destroyChart('fund-turnover');
  charts['fund-turnover'] = new Chart(document.getElementById('fund-turnover-chart').getContext('2d'), {
    type:'bar',
    data:{
      labels: to.map(x=>quarterLabel(x.period)),
      datasets:[
        { label:'New Positions', data:to.map(x=>x.new), backgroundColor:'rgba(44,110,73,0.7)', borderRadius:2 },
        { label:'Removed Positions', data:to.map(x=>-x.removed), backgroundColor:'rgba(139,38,53,0.7)', borderRadius:2 },
      ]
    },
    options:{ responsive:true, maintainAspectRatio:false,
      plugins:{ legend:{position:'top'} },
      scales:{ y:{ ticks:{ callback:v=>Math.abs(v) } } }
    }
  });

  // Holdings table
  const tbody = document.getElementById('holdings-tbody');
  tbody.innerHTML = '';
  const maxVal = latest.holdings[0]?.value || 1;
  latest.holdings.forEach((h,i) => {
    const barW = Math.round(h.value/maxVal*100);
    tbody.innerHTML += `<tr>
      <td>${i+1}</td>
      <td><b>${h.name}</b></td>
      <td><span class="badge">${h.cusip||'—'}</span></td>
      <td class="td-right">$${fmtM(h.value)}</td>
      <td class="td-right">${h.shares?.toLocaleString()||'—'}</td>
      <td class="td-right">${fmtPct(h.pct)}</td>
      <td class="td-bar"><div class="bar-inner" style="width:${barW}%"></div></td>
    </tr>`;
  });
}

// ─── CROSS-FUND TAB ──────────────────────────────────────────────────────────
let crossInitialized = false;
function initCrossFundTab() {
  crossInitialized = true;
  const cross = METRICS.cross_holdings || [];

  // Bar chart — top 20 most held
  const top20 = cross.slice(0,20);
  destroyChart('cross-bar');
  charts['cross-bar'] = new Chart(document.getElementById('cross-bar-chart').getContext('2d'), {
    type:'bar',
    data:{
      labels: top20.map(x=>x.name),
      datasets:[{
        label:'# Funds', data:top20.map(x=>x.num_funds),
        backgroundColor: top20.map((_,i)=>PALETTE[i%PALETTE.length]+'cc'), borderRadius:3
      }]
    },
    options:{ indexAxis:'y', responsive:true, maintainAspectRatio:false,
      plugins:{ legend:{display:false} },
      scales:{ x:{ticks:{stepSize:1}} }
    }
  });

  // Consensus holdings table
  const tbody = document.getElementById('cross-holdings-tbody');
  tbody.innerHTML = '';
  cross.forEach((s,i) => {
    const badges = s.funds.map(f=>`<span class="badge badge-green">${f.split(' ')[0]}</span>`).join(' ');
    tbody.innerHTML += `<tr>
      <td>${i+1}</td>
      <td><b>${s.name}</b></td>
      <td><span class="badge">${s.cusip}</span></td>
      <td class="td-right"><b>${s.num_funds}</b></td>
      <td class="td-right">$${fmtM(s.total_value)}</td>
      <td>${badges}</td>
    </tr>`;
  });

  // Overlap matrix
  const overlap = METRICS.overlap || {};
  const funds = METRICS.fund_names || [];
  const tbl = document.getElementById('overlap-table');
  let html = '<thead><tr><th></th>';
  funds.forEach(f => { html += `<th title="${f}">${f.split(' ')[0]}</th>`; });
  html += '</tr></thead><tbody>';
  funds.forEach(ra => {
    html += `<tr><th style="text-align:left;white-space:nowrap">${ra.split(' ').slice(0,2).join(' ')}</th>`;
    funds.forEach(rb => {
      const v = overlap[ra]?.[rb] ?? 0;
      const intensity = Math.round(v/100*180);
      const bg = ra===rb ? '#e8f4ec' : v>30 ? `rgba(44,62,45,${v/100})` : v>15 ? `rgba(44,110,73,${v/60})` : '';
      const color = v>40 ? '#fff' : 'inherit';
      html += `<td style="background:${bg};color:${color}">${ra===rb?'—':v+'%'}</td>`;
    });
    html += '</tr>';
  });
  html += '</tbody>';
  tbl.innerHTML = html;
}

// ─── STOCK TRACKER TAB ───────────────────────────────────────────────────────
let trackerInitialized = false;
let allStocksIndex = [];

function initTrackerTab() {
  trackerInitialized = true;

  // Build a full index of all stocks across all funds & quarters
  const stockMap = {}; // cusip → {name, funds_latest, value_latest, history: {fund: [{period, value}]}}

  fundList.forEach(fundName => {
    const fund = ALL_DATA[fundName];
    if (!fund.filings) return;
    fund.filings.forEach(filing => {
      filing.holdings.forEach(h => {
        if (!h.cusip) return;
        if (!stockMap[h.cusip]) stockMap[h.cusip] = { name:h.name, cusip:h.cusip, latest_funds:[], latest_value:0, history:{} };
        if (!stockMap[h.cusip].history[fundName]) stockMap[h.cusip].history[fundName] = [];
        stockMap[h.cusip].history[fundName].push({ period:filing.period, value:h.value });
      });
    });

    // Latest holdings
    const latest = fund.filings[fund.filings.length-1];
    if (latest) {
      latest.holdings.forEach(h => {
        if (!h.cusip || !stockMap[h.cusip]) return;
        if (!stockMap[h.cusip].latest_funds.includes(fundName)) {
          stockMap[h.cusip].latest_funds.push(fundName);
          stockMap[h.cusip].latest_value += h.value;
        }
      });
    }
  });

  allStocksIndex = Object.values(stockMap)
    .filter(s => s.latest_funds.length >= 1)
    .sort((a,b) => b.latest_funds.length - a.latest_funds.length || b.latest_value - a.latest_value);

  window._stockMap = stockMap;
  renderTrackerTable(allStocksIndex.slice(0,100));
}

function filterStockSearch() {
  const q = document.getElementById('stock-search').value.toLowerCase();
  const filtered = q ? allStocksIndex.filter(s => s.name.toLowerCase().includes(q) || s.cusip.includes(q)) : allStocksIndex;
  renderTrackerTable(filtered.slice(0,100));
}

function renderTrackerTable(stocks) {
  const tbody = document.getElementById('tracker-tbody');
  tbody.innerHTML = '';
  stocks.forEach(s => {
    const badges = s.latest_funds.map(f=>`<span class="badge badge-green">${f.split(' ')[0]}</span>`).join(' ');
    tbody.innerHTML += `<tr onclick="showTrackerDetail('${s.cusip.replace(/'/g,"\\'")}','${s.name.replace(/'/g,"\\'")}')">
      <td><b>${s.name}</b></td>
      <td><span class="badge">${s.cusip}</span></td>
      <td class="td-right"><b>${s.latest_funds.length}</b></td>
      <td class="td-right">$${fmtM(s.latest_value)}</td>
      <td>${badges}</td>
    </tr>`;
  });
}

function showTrackerDetail(cusip, name) {
  document.getElementById('tracker-detail').style.display = 'block';
  document.getElementById('tracker-stock-name').textContent = name + '  (' + cusip + ')';

  const stockMap = window._stockMap || {};
  const stock = stockMap[cusip];
  if (!stock) return;

  // Build period-aligned dataset per fund
  const periodSet = new Set();
  Object.values(stock.history).forEach(arr => arr.forEach(p => periodSet.add(p.period)));
  const periods = [...periodSet].sort();

  const datasets = Object.entries(stock.history).map(([fundName, arr], i) => {
    const byPeriod = {};
    arr.forEach(p => { byPeriod[p.period] = p.value; });
    return {
      label: fundName,
      data: periods.map(p => byPeriod[p] ? +(byPeriod[p]/1e6).toFixed(1) : null),
      borderColor: PALETTE[i%PALETTE.length],
      backgroundColor: 'transparent',
      tension:0.3, pointRadius:3, borderWidth:2, spanGaps:false
    };
  });

  destroyChart('tracker');
  charts['tracker'] = new Chart(document.getElementById('tracker-chart').getContext('2d'), {
    type:'line',
    data:{ labels:periods.map(quarterLabel), datasets },
    options:{ responsive:true, maintainAspectRatio:false,
      plugins:{ legend:{position:'right'} },
      scales:{ y:{ ticks:{callback:v=>'$'+v+'M'} } }
    }
  });

  document.getElementById('tracker-detail').scrollIntoView({behavior:'smooth', block:'start'});
}
</script>
</body>
</html>
"""


def fmt_billions(v):
    if v >= 1e9:
        return f"${v/1e9:.1f}B"
    if v >= 1e6:
        return f"${v/1e6:.0f}M"
    return f"${v:,.0f}"


def generate_html(all_data, metrics, output_path):
    """Inject data into the HTML template and write report."""

    active_funds = [n for n, f in all_data.items() if f and f.get("filings")]

    # Build period range
    all_periods = []
    for f in all_data.values():
        if f and f.get("filings"):
            all_periods.extend(f["period"] for f in f["filings"])
    all_periods = sorted(set(all_periods))
    period_range = f"{all_periods[0]} to {all_periods[-1]}" if all_periods else "—"

    # Fund selector options HTML
    fund_opts = "\n".join(
        f'      <option value="{n}">{n}</option>'
        for n in sorted(active_funds)
    )

    html = HTML_TEMPLATE
    html = html.replace("__PERIOD_RANGE__", period_range)
    html = html.replace("__FUND_COUNT__", str(len(active_funds)))
    html = html.replace("__FUND_OPTIONS__", fund_opts)
    html = html.replace("__ALL_DATA__", json.dumps(all_data, ensure_ascii=False))
    html = html.replace("__METRICS__", json.dumps(metrics, ensure_ascii=False))

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n✓ Report written to: {output_path}")


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Analyze SEC 13F filings for major hedge funds")
    parser.add_argument("--funds", help="Comma-separated fund names to analyze (default: all)")
    parser.add_argument("--output", default=OUTPUT_FILE, help=f"Output HTML file (default: {OUTPUT_FILE})")
    parser.add_argument("--cache", default=CACHE_FILE, help=f"Cache file (default: {CACHE_FILE})")
    parser.add_argument("--no-cache", action="store_true", help="Ignore existing cache")
    args = parser.parse_args()

    # Load cache
    cache = {}
    if not args.no_cache and os.path.exists(args.cache):
        try:
            with open(args.cache, "r") as f:
                cache = json.load(f)
            print(f"Loaded cache: {len(cache)} entries from {args.cache}")
        except Exception as e:
            print(f"Warning: could not load cache: {e}")

    # Select funds
    selected_funds = FUNDS
    if args.funds:
        keys = [k.strip() for k in args.funds.split(",")]
        selected_funds = {k: v for k, v in FUNDS.items() if k in keys}
        if not selected_funds:
            print(f"Error: none of the requested funds found in registry.")
            sys.exit(1)

    print(f"\n{'═'*60}")
    print(f"  SEC 13F Filing Analyzer")
    print(f"  Funds: {len(selected_funds)}  |  Period: {START_YEAR}–present")
    print(f"{'═'*60}")

    all_data = {}
    for fund_name, config in selected_funds.items():
        try:
            data = fetch_fund_data(fund_name, config, cache)
            if data:
                all_data[fund_name] = data
            else:
                all_data[fund_name] = {"filings": [], "description": config.get("description", "")}
        except KeyboardInterrupt:
            print("\nInterrupted — saving partial results...")
            break
        except Exception as e:
            print(f"\n  Error processing {fund_name}: {e}")
            all_data[fund_name] = {"filings": [], "description": config.get("description", "")}

    # Save updated cache
    try:
        with open(args.cache, "w") as f:
            json.dump(cache, f)
        print(f"\nCache saved: {len(cache)} entries → {args.cache}")
    except Exception as e:
        print(f"Warning: could not save cache: {e}")

    # Compute analytics
    print("\nComputing cross-fund analytics...")
    metrics = compute_metrics(all_data)

    # Generate report
    generate_html(all_data, metrics, args.output)

    # Summary
    print(f"\n{'═'*60}")
    print(f"  Done! {len([n for n,f in all_data.items() if f.get('filings')])} funds with data")
    for name, fund in sorted(all_data.items(), key=lambda x: -(x[1].get("latest_value") or 0)):
        if fund.get("filings"):
            print(f"  {name:35s}  {len(fund['filings'])} quarters  "
                  f"${fund.get('latest_value',0)/1e9:.2f}B")
    print(f"{'═'*60}")
    print(f"\n  Open {args.output} in your browser to explore the dashboard.\n")


if __name__ == "__main__":
    main()
