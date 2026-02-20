#!/usr/bin/env python3
"""
13F Filing Parser
Fetches and parses historical 13F-HR filings from SEC EDGAR for a set of
well-known hedge funds, producing JSON output with holdings, portfolio
percentages, and quarter-over-quarter change metadata.

Usage:
    python parse_13f.py                         # parse all funds
    python parse_13f.py --funds "Egerton" "TCI" # parse specific funds
    python parse_13f.py --start 2018-01-01      # custom start date
    python parse_13f.py --output ./data         # custom output directory
    python parse_13f.py --cache-dir ./cache     # cache raw filings locally
    python parse_13f.py --discover-only         # print found CIKs and exit
"""

import argparse
import json
import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DEFAULT_START_DATE = "2015-01-01"
DEFAULT_OUTPUT_DIR = "output"
DEFAULT_CACHE_DIR = ".cache"

EDGAR_WWW = "https://www.sec.gov"
EDGAR_DATA = "https://data.sec.gov"

# SEC requests a descriptive User-Agent with contact info.
USER_AGENT = "13F-Parser research@example.com"

# Rate-limit: SEC guidelines say max 10 requests/second.
# We use 150 ms between requests to stay safely under that.
MIN_REQUEST_INTERVAL = 0.15  # seconds

# Funds: display name → list of EDGAR search terms (tried in order)
FUND_SEARCH_TERMS: Dict[str, List[str]] = {
    "Egerton": ["Egerton Capital"],
    "TCI": ["Children's Investment Fund", "TCI Fund Management"],
    "Durable": ["Durable Capital"],
    "RV Capital": ["RV Capital"],
    "D1 Capital": ["D1 Capital Partners"],
    "Tiger Global": ["Tiger Global Management"],
    "Coatue": ["Coatue Management"],
    "ValueAct": ["ValueAct Capital", "VA Partners"],
    "Soroban": ["Soroban Capital"],
    "Surgo": ["Surgo"],
    "Whale Rock": ["Whale Rock Capital"],
    "Ruane Cunniff": ["Ruane Cunniff", "Ruane, Cunniff"],
    "Lone Pine": ["Lone Pine Capital"],
    "Greenoaks": ["Greenoaks Capital"],
}

# Known CIK overrides – avoids ambiguous search results for common names.
# Values are zero-padded 10-digit strings.
# Leave blank; the script will discover CIKs at runtime.
# You can pre-populate this dict after a --discover-only run.
KNOWN_CIKS: Dict[str, str] = {
    # "Tiger Global": "0001167483",
    # "Coatue":       "0001336528",
    # "Lone Pine":    "0001061219",
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# EDGAR HTTP client
# ---------------------------------------------------------------------------


class EdgarClient:
    """Thin wrapper around requests with rate-limiting and retries."""

    def __init__(self, user_agent: str = USER_AGENT):
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept-Encoding": "gzip, deflate",
            }
        )
        self._last_call: float = 0.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _wait(self) -> None:
        elapsed = time.monotonic() - self._last_call
        if elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)
        self._last_call = time.monotonic()

    def _get(self, url: str, **kwargs) -> requests.Response:
        self._wait()
        for attempt in range(4):
            try:
                resp = self.session.get(url, timeout=30, **kwargs)
                resp.raise_for_status()
                return resp
            except requests.RequestException as exc:
                if attempt == 3:
                    raise
                backoff = 2 ** (attempt + 1)
                log.warning("Request failed (%s), retrying in %ds…", exc, backoff)
                time.sleep(backoff)
        raise RuntimeError("Unreachable")  # pragma: no cover

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def find_cik(self, search_term: str) -> Optional[Tuple[str, str]]:
        """
        Search EDGAR for a company by name.
        Returns (cik_padded, company_name) for the first 13F filer match,
        or None if nothing is found.
        """
        url = f"{EDGAR_WWW}/cgi-bin/browse-edgar"
        params = {
            "company": search_term,
            "CIK": "",
            "type": "13F-HR",
            "dateb": "",
            "owner": "include",
            "count": "10",
            "search_text": "",
            "action": "getcompany",
            "output": "atom",
        }
        try:
            resp = self._get(url, params=params)
        except requests.RequestException as exc:
            log.error("CIK search failed for %r: %s", search_term, exc)
            return None

        # Parse Atom XML
        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as exc:
            log.error("Failed to parse EDGAR Atom response: %s", exc)
            return None

        ns = {"atom": "http://www.w3.org/2005/Atom"}
        entries = root.findall("atom:entry", ns)
        if not entries:
            return None

        # Pick the first entry; extract CIK from the id URL
        entry = entries[0]
        cik_elem = entry.find("atom:id", ns)
        name_elem = entry.find("atom:company-name", ns) or entry.find(
            "{http://www.sec.gov/cgi-bin/browse-edgar}company-name"
        )

        # company-name lives in the SEC-specific namespace
        company_name = ""
        for child in entry:
            if child.tag.endswith("company-name"):
                company_name = child.text or ""
                break

        if cik_elem is None:
            return None

        # id looks like: https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0001234567&...
        match = re.search(r"CIK=(\d+)", cik_elem.text or "")
        if not match:
            # Try the <cik> element
            for child in entry:
                if child.tag.endswith("cik"):
                    match = re.match(r"(\d+)", child.text or "")
                    break

        if not match:
            return None

        cik = match.group(1).zfill(10)
        return cik, company_name

    def get_submissions(self, cik: str) -> Dict:
        """
        Fetch the submissions JSON for a CIK from data.sec.gov.
        Also follows 'files' links for older filings.
        """
        url = f"{EDGAR_DATA}/submissions/CIK{cik}.json"
        resp = self._get(url)
        data: Dict = resp.json()

        # EDGAR paginates older filings via data["filings"]["files"]
        extra_files = data.get("filings", {}).get("files", [])
        for f in extra_files:
            name = f.get("name", "")
            if not name:
                continue
            extra_url = f"{EDGAR_DATA}/submissions/{name}"
            try:
                extra_resp = self._get(extra_url)
                extra_data = extra_resp.json()
                # Merge into data["filings"]["recent"]
                recent = data["filings"]["recent"]
                for key, values in extra_data.get("recent", {}).items():
                    if key in recent and isinstance(recent[key], list):
                        recent[key].extend(values)
            except Exception as exc:
                log.warning("Could not fetch extra submissions page %s: %s", name, exc)

        return data

    def get_filing_index(self, cik: str, accession: str) -> Optional[Dict]:
        """Return the JSON index (list of documents) for a single filing."""
        acc_clean = accession.replace("-", "")
        url = f"{EDGAR_WWW}/Archives/edgar/data/{cik.lstrip('0')}/{acc_clean}/{accession}-index.json"
        try:
            resp = self._get(url)
            return resp.json()
        except Exception as exc:
            log.warning("Could not fetch filing index %s: %s", accession, exc)
            return None

    def download_text(self, url: str) -> Optional[str]:
        """Download raw text from any EDGAR URL."""
        try:
            resp = self._get(url)
            return resp.text
        except Exception as exc:
            log.warning("Download failed %s: %s", url, exc)
            return None


# ---------------------------------------------------------------------------
# 13F XML parser
# ---------------------------------------------------------------------------


def _strip_ns(tag: str) -> str:
    """Remove Clark-notation namespace prefix: {uri}localname → localname."""
    return tag.split("}")[-1] if "}" in tag else tag


def _find_text(parent: ET.Element, local_name: str, default: str = "") -> str:
    """
    Find first child with the given local tag name (namespace-agnostic)
    and return its stripped text.
    """
    for child in parent:
        if _strip_ns(child.tag) == local_name:
            return (child.text or "").strip()
    return default


def _find_elem(parent: ET.Element, local_name: str) -> Optional[ET.Element]:
    for child in parent:
        if _strip_ns(child.tag) == local_name:
            return child
    return None


class Filing13FParser:
    """Parses the information-table XML file embedded in a 13F-HR filing."""

    def parse(self, xml_text: str) -> List[Dict]:
        """
        Parse raw XML and return a list of holding dicts.
        Returns an empty list on parse errors.
        """
        # Strip BOM and leading whitespace
        xml_text = xml_text.lstrip("\ufeff").strip()

        # Some older filings wrap the table in an outer element; handle both
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError:
            # Try wrapping in a root element to handle multiple top-level nodes
            try:
                root = ET.fromstring(f"<root>{xml_text}</root>")
            except ET.ParseError as exc:
                log.error("XML parse error: %s", exc)
                return []

        holdings = []
        for elem in root.iter():
            if _strip_ns(elem.tag) == "infoTable":
                holding = self._parse_entry(elem)
                if holding:
                    holdings.append(holding)

        return holdings

    def _parse_entry(self, entry: ET.Element) -> Optional[Dict]:
        name = _find_text(entry, "nameOfIssuer")
        cusip = _find_text(entry, "cusip")
        title = _find_text(entry, "titleOfClass")
        value_str = _find_text(entry, "value", "0")  # thousands of USD
        discretion = _find_text(entry, "investmentDiscretion")
        put_call = _find_text(entry, "putCall")

        shrs_elem = _find_elem(entry, "shrsOrPrnAmt")
        shares = 0
        share_type = ""
        if shrs_elem is not None:
            shares_str = _find_text(shrs_elem, "sshPrnamt", "0")
            share_type = _find_text(shrs_elem, "sshPrnamtType")
            try:
                shares = int(shares_str.replace(",", ""))
            except ValueError:
                shares = 0

        try:
            value_k = int(value_str.replace(",", ""))
        except ValueError:
            value_k = 0

        if not name and not cusip:
            return None

        return {
            "name": name,
            "cusip": cusip,
            "title_of_class": title,
            "investment_discretion": discretion,
            "put_call": put_call,  # non-empty only for options
            "share_type": share_type,  # "SH" or "PRN"
            "shares": shares,
            "value_usd": value_k * 1000,  # convert from thousands
        }


# ---------------------------------------------------------------------------
# Portfolio-level enrichment
# ---------------------------------------------------------------------------


class PortfolioProcessor:
    """Adds % of portfolio and quarter-over-quarter change metadata."""

    def enrich(
        self,
        holdings: List[Dict],
        previous: Optional[List[Dict]] = None,
    ) -> List[Dict]:
        total_value = sum(h["value_usd"] for h in holdings)
        prev_by_cusip = {h["cusip"]: h for h in (previous or [])} if previous else {}

        enriched = []
        for h in holdings:
            h = dict(h)
            h["pct_portfolio"] = (
                round(h["value_usd"] / total_value * 100, 4) if total_value else 0.0
            )
            self._add_change(h, prev_by_cusip)
            enriched.append(h)

        # Mark exited positions (in previous but not in current)
        current_cusips = {h["cusip"] for h in holdings}
        for cusip, prev_h in prev_by_cusip.items():
            if cusip not in current_cusips:
                exited = dict(prev_h)
                exited.update(
                    {
                        "shares": 0,
                        "value_usd": 0,
                        "pct_portfolio": 0.0,
                        "change_type": "exited",
                        "share_change": -prev_h["shares"],
                        "share_change_pct": -100.0,
                        "value_change_usd": -prev_h["value_usd"],
                    }
                )
                enriched.append(exited)

        enriched.sort(key=lambda h: h["value_usd"], reverse=True)
        return enriched

    # ------------------------------------------------------------------

    def _add_change(self, h: Dict, prev_by_cusip: Dict) -> None:
        cusip = h["cusip"]
        if not prev_by_cusip:
            h.update(
                {
                    "change_type": "unknown",
                    "share_change": None,
                    "share_change_pct": None,
                    "value_change_usd": None,
                }
            )
            return

        prev = prev_by_cusip.get(cusip)
        if prev is None:
            h.update(
                {
                    "change_type": "new",
                    "share_change": h["shares"],
                    "share_change_pct": None,
                    "value_change_usd": h["value_usd"],
                }
            )
            return

        share_delta = h["shares"] - prev["shares"]
        value_delta = h["value_usd"] - prev["value_usd"]
        pct_change = (
            round(share_delta / prev["shares"] * 100, 2) if prev["shares"] else None
        )

        if share_delta > 0:
            change_type = "increased"
        elif share_delta < 0:
            change_type = "decreased"
        else:
            change_type = "unchanged"

        h.update(
            {
                "change_type": change_type,
                "share_change": share_delta,
                "share_change_pct": pct_change,
                "value_change_usd": value_delta,
            }
        )


# ---------------------------------------------------------------------------
# High-level orchestration
# ---------------------------------------------------------------------------


def _quarter_label(report_date: str) -> str:
    """Convert '2023-12-31' to '2023-Q4'."""
    try:
        dt = datetime.strptime(report_date, "%Y-%m-%d")
        q = (dt.month - 1) // 3 + 1
        return f"{dt.year}-Q{q}"
    except ValueError:
        return report_date


def _find_infotable_url(
    client: EdgarClient, cik: str, accession: str
) -> Optional[str]:
    """
    Given a filing, locate the URL of the information-table XML document.
    Falls back to a heuristic URL if the index can't be fetched.
    """
    index = client.get_filing_index(cik, accession)
    if index:
        docs = index.get("documents") or index.get("directory", {}).get("item", [])
        for doc in docs:
            doc_type = (doc.get("type") or doc.get("Type") or "").lower()
            doc_name = (doc.get("filename") or doc.get("name") or doc.get("Filename") or "").lower()
            # Information table: type is "INFORMATION TABLE" or filename has "infotable"
            if "information table" in doc_type or "infotable" in doc_name:
                filename = doc.get("filename") or doc.get("name") or doc.get("Filename") or ""
                acc_clean = accession.replace("-", "")
                cik_num = cik.lstrip("0")
                return f"{EDGAR_WWW}/Archives/edgar/data/{cik_num}/{acc_clean}/{filename}"

    # Heuristic: try common filename patterns
    acc_clean = accession.replace("-", "")
    cik_num = cik.lstrip("0")
    base = f"{EDGAR_WWW}/Archives/edgar/data/{cik_num}/{acc_clean}"
    candidates = [
        f"{base}/{accession}-infotable.xml",
        f"{base}/infotable.xml",
        f"{base}/form13fInfoTable.xml",
    ]
    for url in candidates:
        return url  # Return first candidate; caller will handle failures

    return None


def parse_fund(
    fund_name: str,
    cik: str,
    submissions: Dict,
    client: EdgarClient,
    parser: Filing13FParser,
    processor: PortfolioProcessor,
    start_date: str,
    cache_dir: Optional[Path],
) -> Dict:
    """Fetch and parse all 13F filings for one fund since start_date."""

    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    filing_dates = recent.get("filingDate", [])
    accessions = recent.get("accessionNumber", [])
    report_dates = recent.get("reportDate", [])

    # Collect eligible filings (13F-HR only; amendments (13F-HR/A) are skipped
    # unless there is no original for that period).
    eligible = []
    for i, form in enumerate(forms):
        if form not in ("13F-HR", "13F-HR/A"):
            continue
        if filing_dates[i] < start_date:
            continue
        eligible.append(
            {
                "form": form,
                "filingDate": filing_dates[i],
                "accessionNumber": accessions[i],
                "reportDate": report_dates[i],
            }
        )

    # Sort chronologically
    eligible.sort(key=lambda x: x["filingDate"])

    # Prefer 13F-HR over 13F-HR/A for the same report period
    by_period: Dict[str, Dict] = {}
    for f in eligible:
        period = f["reportDate"]
        existing = by_period.get(period)
        if existing is None or (
            f["form"] == "13F-HR" and existing["form"] == "13F-HR/A"
        ):
            by_period[period] = f

    periods_sorted = sorted(by_period.keys())
    log.info("  %s: %d quarters found (CIK %s)", fund_name, len(periods_sorted), cik)

    filings_out = []
    previous_holdings: Optional[List[Dict]] = None

    for period_date in periods_sorted:
        filing = by_period[period_date]
        accession = filing["accessionNumber"]
        quarter = _quarter_label(period_date)
        log.info("    Fetching %s …", quarter)

        xml_text = _try_cache(cache_dir, cik, accession)
        if xml_text is None:
            infotable_url = _find_infotable_url(client, cik, accession)
            if infotable_url:
                xml_text = client.download_text(infotable_url)

            # If direct URL failed, scan the full filing index for XML docs
            if not xml_text:
                xml_text = _scan_filing_for_xml(client, cik, accession)

            if xml_text:
                _write_cache(cache_dir, cik, accession, xml_text)
            else:
                log.warning("    Could not retrieve XML for %s %s", fund_name, quarter)
                continue

        holdings_raw = parser.parse(xml_text)
        if not holdings_raw:
            log.warning("    No holdings parsed for %s %s", fund_name, quarter)
            continue

        total_value = sum(h["value_usd"] for h in holdings_raw)
        holdings_enriched = processor.enrich(holdings_raw, previous_holdings)
        previous_holdings = [h for h in holdings_raw]  # store for next quarter

        filings_out.append(
            {
                "period": quarter,
                "period_of_report": period_date,
                "filed_date": filing["filingDate"],
                "form_type": filing["form"],
                "accession_number": accession,
                "total_value_usd": total_value,
                "holdings_count": len(holdings_raw),
                "holdings": holdings_enriched,
            }
        )

    return {
        "fund_name": fund_name,
        "cik": cik,
        "last_updated": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "filings": filings_out,
    }


def _scan_filing_for_xml(
    client: EdgarClient, cik: str, accession: str
) -> Optional[str]:
    """
    Fetch the HTML index page and look for any XML document that contains
    13F information-table data.
    """
    acc_clean = accession.replace("-", "")
    cik_num = cik.lstrip("0")
    index_url = (
        f"{EDGAR_WWW}/Archives/edgar/data/{cik_num}/{acc_clean}/{accession}-index.htm"
    )
    html = client.download_text(index_url)
    if not html:
        return None

    # Find all .xml links
    xml_links = re.findall(
        r'href="(/Archives/edgar/data/[^"]+\.xml)"', html, re.IGNORECASE
    )
    for link in xml_links:
        url = f"{EDGAR_WWW}{link}"
        text = client.download_text(url)
        if text and "infoTable" in text:
            return text

    return None


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def _cache_path(cache_dir: Optional[Path], cik: str, accession: str) -> Optional[Path]:
    if cache_dir is None:
        return None
    return cache_dir / cik / f"{accession}.xml"


def _try_cache(cache_dir: Optional[Path], cik: str, accession: str) -> Optional[str]:
    p = _cache_path(cache_dir, cik, accession)
    if p and p.exists():
        return p.read_text(encoding="utf-8")
    return None


def _write_cache(
    cache_dir: Optional[Path], cik: str, accession: str, text: str
) -> None:
    p = _cache_path(cache_dir, cik, accession)
    if p:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Parse historical 13F-HR filings from SEC EDGAR.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--funds",
        nargs="+",
        metavar="FUND",
        help=(
            "Fund names to parse (subset of configured funds). "
            f"Available: {', '.join(FUND_SEARCH_TERMS)}"
        ),
    )
    p.add_argument(
        "--start",
        default=DEFAULT_START_DATE,
        metavar="YYYY-MM-DD",
        help="Earliest filing date to include.",
    )
    p.add_argument(
        "--output",
        default=DEFAULT_OUTPUT_DIR,
        metavar="DIR",
        help="Directory for JSON output files.",
    )
    p.add_argument(
        "--cache-dir",
        default=DEFAULT_CACHE_DIR,
        metavar="DIR",
        help="Directory for caching raw XML files (speeds up re-runs). Use 'none' to disable.",
    )
    p.add_argument(
        "--discover-only",
        action="store_true",
        help="Just discover CIK numbers and print them; do not parse filings.",
    )
    p.add_argument(
        "--user-agent",
        default=USER_AGENT,
        metavar="STRING",
        help="User-Agent header sent to EDGAR (format: 'Name email@domain.com').",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging.",
    )
    return p


def main() -> None:
    args = build_arg_parser().parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    cache_dir: Optional[Path]
    if args.cache_dir.lower() == "none":
        cache_dir = None
    else:
        cache_dir = Path(args.cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)

    # Determine which funds to process
    if args.funds:
        unknown = [f for f in args.funds if f not in FUND_SEARCH_TERMS]
        if unknown:
            log.error("Unknown fund name(s): %s", ", ".join(unknown))
            log.error("Available: %s", ", ".join(FUND_SEARCH_TERMS))
            return
        selected = {k: FUND_SEARCH_TERMS[k] for k in args.funds}
    else:
        selected = FUND_SEARCH_TERMS

    client = EdgarClient(user_agent=args.user_agent)
    parser = Filing13FParser()
    processor = PortfolioProcessor()

    # --- CIK discovery ---------------------------------------------------
    resolved_ciks: Dict[str, str] = {}  # fund_name → CIK

    log.info("Discovering CIKs for %d fund(s) …", len(selected))
    for fund_name, search_terms in selected.items():
        if fund_name in KNOWN_CIKS:
            resolved_ciks[fund_name] = KNOWN_CIKS[fund_name]
            log.info("  %s: using known CIK %s", fund_name, KNOWN_CIKS[fund_name])
            continue

        found = None
        for term in search_terms:
            result = client.find_cik(term)
            if result:
                found = result
                break

        if found:
            cik, company_name = found
            resolved_ciks[fund_name] = cik
            log.info("  %s → CIK %s (%s)", fund_name, cik, company_name)
        else:
            log.warning(
                "  %s: CIK not found via search terms %s – skipping", fund_name, search_terms
            )

    if args.discover_only:
        print("\nDiscovered CIKs:")
        for name, cik in resolved_ciks.items():
            print(f"  {name:20s}: {cik}")
        print("\nAdd confirmed CIKs to KNOWN_CIKS in the script for reproducibility.")
        return

    if not resolved_ciks:
        log.error("No funds resolved. Exiting.")
        return

    # --- Parse filings ---------------------------------------------------
    summary: Dict[str, Dict] = {}

    for fund_name, cik in resolved_ciks.items():
        log.info("Processing %s (CIK %s) …", fund_name, cik)
        try:
            submissions = client.get_submissions(cik)
        except Exception as exc:
            log.error("  Failed to fetch submissions for %s: %s", fund_name, exc)
            continue

        result = parse_fund(
            fund_name=fund_name,
            cik=cik,
            submissions=submissions,
            client=client,
            parser=parser,
            processor=processor,
            start_date=args.start,
            cache_dir=cache_dir,
        )

        # Save per-fund JSON
        out_file = output_dir / f"{fund_name.lower().replace(' ', '_')}_13f.json"
        out_file.write_text(json.dumps(result, indent=2), encoding="utf-8")
        log.info("  Saved → %s", out_file)

        summary[fund_name] = {
            "cik": cik,
            "filings_parsed": len(result["filings"]),
            "quarters": [f["period"] for f in result["filings"]],
            "output_file": str(out_file),
        }

    # Save summary index
    summary_file = output_dir / "_summary.json"
    summary_file.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    log.info("Summary written → %s", summary_file)

    log.info("Done. %d fund(s) processed.", len(summary))


if __name__ == "__main__":
    main()
