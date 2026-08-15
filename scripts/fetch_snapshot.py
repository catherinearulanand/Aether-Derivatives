"""Ingest real published market data and pin it as a snapshot fixture.

    python scripts/fetch_snapshot.py                       # write fixtures/market/live/
    python scripts/fetch_snapshot.py --dry-run             # fetch and print, write nothing

.. rubric:: Why ingestion is separate from calculation

The Playbook asks for live market data. The reproducibility contract says a
calculation may never read a live feed. Both hold at once, because the network call
happens **here** and its result is written to a pinned snapshot with full provenance.
The engine then loads that file exactly as it loads any other snapshot, and two runs
against the same snapshot id still produce byte-identical audit hashes.

So: data is live at ingest, pinned at calculation. A snapshot is a photograph, and
this script is the shutter.

.. rubric:: Sources

Both are public, keyless and cite themselves in the fixture they produce:

- **FX** — the European Central Bank's daily reference rates, via ``frankfurter.app``.
- **USD yield curve** — the US Treasury's Daily Par Yield Curve Rates.

Neither is a trading source and neither is intraday. That is stated in the fixture,
and nothing in AETHER describes this as real-time or as market-executable data.

.. rubric:: This is never the demo path

``AETHER_MODE=replay`` and the committed simulated snapshots remain the demo. This
script exists so the claim "AETHER can ingest real published data" is true rather
than aspirational, and so that claim can be checked. If the network is unavailable it
fails loudly and changes nothing.
"""

from __future__ import annotations

import argparse
import json
import math
import ssl
import sys
import urllib.error
import urllib.request
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "fixtures" / "market" / "live"

FX_URL = "https://api.frankfurter.app/latest?from=USD&to=EUR,INR"
TREASURY_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "pages/xml?data=daily_treasury_yield_curve&field_tdr_date_value={year}"
)

#: Treasury par yield tenors, mapped to the pillar tenors AETHER's curves use.
TREASURY_TENORS: tuple[tuple[str, float], ...] = (
    ("BC_1MONTH", 0.0833),
    ("BC_3MONTH", 0.25),
    ("BC_6MONTH", 0.5),
    ("BC_1YEAR", 1.0),
    ("BC_2YEAR", 2.0),
    ("BC_3YEAR", 3.0),
    ("BC_5YEAR", 5.0),
    ("BC_7YEAR", 7.0),
    ("BC_10YEAR", 10.0),
    ("BC_20YEAR", 20.0),
    ("BC_30YEAR", 30.0),
)


def install_trust() -> None:
    """Use the Windows trust store.

    Outbound TLS on the build machine is intercepted by antivirus software, so the
    default context and ``certifi`` both fail CA validation. See docs/architecture.md
    decision D-001.
    """
    try:
        import truststore

        truststore.inject_into_ssl()
    except ImportError:
        print("  truststore not installed; using the default TLS context.")


def get(url: str, timeout: int = 20) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "AETHER/0.2 (prototype)"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body: bytes = response.read()
        return body


def fetch_fx() -> tuple[dict[str, str], str]:
    """ECB daily reference rates. Returns quotes in AETHER's pair convention."""
    payload = json.loads(get(FX_URL).decode("utf-8"))
    rates = payload["rates"]
    quotes = {
        # frankfurter gives USD->EUR; AETHER quotes EURUSD as USD per EUR.
        "EURUSD": f"{1.0 / float(rates['EUR']):.4f}",
        "USDINR": f"{float(rates['INR']):.4f}",
    }
    return quotes, str(payload["date"])


def par_to_zero(par_rate: float, tenor: float) -> float:
    """Convert a par yield to a continuously compounded zero rate.

    An approximation, and labelled as one: a proper bootstrap would solve the par
    bond's cash flows against the curve being built. For tenors this short and a
    prototype this size the difference is immaterial, but it is a difference, and the
    fixture says so rather than presenting the result as a bootstrapped curve.
    """
    semi = par_rate / 100.0
    return 2.0 * math.log(1.0 + semi / 2.0) if tenor >= 1.0 else semi


def fetch_treasury_curve() -> tuple[list[float], list[float], str]:
    """Latest US Treasury Daily Par Yield Curve, as pillars and zero rates."""
    url = TREASURY_URL.format(year=date.today().year)
    tree = ElementTree.fromstring(get(url).decode("utf-8"))

    namespaces = {
        "a": "http://www.w3.org/2005/Atom",
        "m": "http://schemas.microsoft.com/ado/2007/08/dataservices/metadata",
        "d": "http://schemas.microsoft.com/ado/2007/08/dataservices",
    }
    entries = tree.findall("a:entry", namespaces)
    if not entries:
        raise RuntimeError("Treasury feed returned no entries.")

    latest = entries[-1].find("a:content/m:properties", namespaces)
    if latest is None:
        raise RuntimeError("Treasury entry has no properties block.")

    observed = latest.findtext("d:NEW_DATE", default="", namespaces=namespaces)[:10]

    pillars: list[float] = []
    zeros: list[float] = []
    for tag, tenor in TREASURY_TENORS:
        text = latest.findtext(f"d:{tag}", default="", namespaces=namespaces)
        if not text:
            continue
        pillars.append(tenor)
        zeros.append(round(par_to_zero(float(text), tenor), 6))

    if len(pillars) < 4:
        raise RuntimeError(f"Treasury feed gave only {len(pillars)} usable tenors.")
    return pillars, zeros, observed


def build_fixture(
    fx: dict[str, str],
    fx_date: str,
    pillars: list[float],
    zeros: list[float],
    curve_date: str,
) -> dict[str, Any]:
    as_of = curve_date or fx_date
    return {
        "_provenance": {
            "simulated": False,
            # Affirmative marker required by load_ingested_json(). The simulated-only
            # loader refuses this file outright; only the explicitly-named ingested
            # door will read it, and only with all four conditions satisfied.
            "ingested": True,
            "source": (
                "US Treasury Daily Par Yield Curve Rates (home.treasury.gov) for the "
                "USD curve; European Central Bank daily reference rates via "
                "frankfurter.app for FX."
            ),
            "fetched_at": datetime.now(UTC).date().isoformat(),
            "observed_date": as_of,
            "method": (
                "Par yields converted to continuously compounded zero rates by an "
                "approximation, not a full bootstrap. EUR and INR curves are NOT "
                "sourced and are omitted."
            ),
            "warning": (
                "REAL PUBLISHED DATA, PINNED AT INGEST. End-of-day reference rates, "
                "not intraday or executable levels. AETHER never reads a live feed "
                "inside a calculation: this file is a pinned snapshot like any other."
            ),
        },
        "_conventions": {
            "rate_type": "Continuously compounded zero rates",
            "day_count": "ACT/365F",
            "interpolation": "Log-linear on discount factors between pillars",
        },
        "snapshots": [
            {
                "snapshot_id": f"MKT-{as_of}-LIVE",
                "label": "Ingested (US Treasury / ECB)",
                "as_of": as_of,
                "kind": "INGESTED",
                "description": (
                    "Real published end-of-day data, fetched once and pinned. Only the "
                    "USD curve is sourced, so this snapshot prices the USD book only."
                ),
                "curves": {"USD": {"pillars_years": pillars, "zero_rates": zeros}},
                "fx_spot": {
                    "_quote_convention": "Units of the second currency per one unit of the first.",
                    **fx,
                },
            }
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Fetch and print; write nothing.")
    args = parser.parse_args()

    print("\n  AETHER — market data ingestion")
    print("  " + "-" * 58)
    install_trust()

    try:
        fx, fx_date = fetch_fx()
        print(f"  FX        {fx} (ECB, {fx_date})")
        pillars, zeros, curve_date = fetch_treasury_curve()
        print(f"  USD curve {len(pillars)} pillars (US Treasury, {curve_date})")
    except (urllib.error.URLError, ssl.SSLError, TimeoutError, OSError) as exc:
        print(f"\n  FAILED: {exc}")
        print("  Nothing was written. The demo runs on the committed simulated")
        print("  snapshots and does not depend on this script.\n")
        return 1
    except (KeyError, ValueError, RuntimeError, ElementTree.ParseError) as exc:
        print(f"\n  FAILED to parse a source: {exc}")
        print("  Nothing was written.\n")
        return 1

    fixture = build_fixture(fx, fx_date, pillars, zeros, curve_date)
    snapshot_id = fixture["snapshots"][0]["snapshot_id"]

    if args.dry_run:
        print(f"\n  --dry-run: would write {snapshot_id}\n")
        print(json.dumps(fixture, indent=2)[:1200])
        return 0

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "ingested.json"
    out.write_text(json.dumps(fixture, indent=2) + "\n", encoding="utf-8")
    print(f"\n  wrote {out.relative_to(ROOT)}  ({snapshot_id})")
    print("  Pinned. The engine reads it exactly as it reads a simulated snapshot.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
