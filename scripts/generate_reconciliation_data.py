"""Generate the collateral reconciliation dataset.

Produces the two files a collateral operations team reconciles every morning:

``fixtures/reconciliation/internal_ledger.csv``
    The bank's own record of collateral positions posted and received.

``fixtures/reconciliation/custodian_statement.csv``
    The external daily statement, as a custodian would send it.

``fixtures/reconciliation/injection_manifest.json``
    **The ground truth.** Every break this script deliberately introduced, by
    position, with its class and expected magnitude. A reconciliation engine's
    output can be scored against this file, which is what makes the dataset a
    benchmark rather than a demo prop.

.. rubric:: Why the breaks are injected rather than found

A dataset in which the two sides agree perfectly proves nothing about a
reconciliation screen. A dataset with *undocumented* differences proves nothing
either, because there is no way to tell a detected break from a missed one. So the
generator starts from an internally consistent pair of files and injects a known,
seeded, enumerated set of differences. The manifest is the answer key.

.. rubric:: Determinism

Every random draw comes from a seeded generator (``SEED``). Re-running this script
reproduces both files and the manifest byte for byte. That matters because the
committed fixtures and the manifest must agree, and because a break rate that
drifted between runs would make the score meaningless.

.. rubric:: This data is simulated

Counterparties, custodians, BICs, account numbers, staff names and every price are
synthetic. The asset identifiers are ISIN-*shaped* and are not real ISINs. Nothing
here was observed in a market and none of it may be used for any purpose beyond
demonstrating AETHER.

Run::

    pip install -e ".[data]"
    python scripts/generate_reconciliation_data.py
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_EVEN, Decimal
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from faker import Faker

# --------------------------------------------------------------------- config

SEED = 20260817
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "fixtures" / "reconciliation"

#: Statement date. Matches the stress scenario's snapshot so the reconciliation
#: sits on the same valuation date as the margin run it belongs to.
AS_OF = date(2026, 8, 17)

#: Positions to generate before injection. Large enough that a percentage break
#: rate is meaningful, small enough to read on one screen after filtering.
POSITION_COUNT = 148

#: A price difference at or below this is a rounding artefact, not a break. Real
#: reconciliation runs carry a tolerance; a screen without one drowns in noise.
TOLERANCE_BPS = Decimal("5")

fake = Faker("en_GB")
Faker.seed(SEED)
rng = np.random.default_rng(SEED)


# ------------------------------------------------------------------ reference

#: The twelve assets AETHER's optimizer actually allocates, mirrored from
#: ``fixtures/collateral/aether_inventory.json``. Including them ties the
#: reconciliation to the same asset universe the margin run posts from, so a break
#: on a posted asset is visibly a break on collateral the desk delivered this
#: morning — not an unrelated table.
#: ``(asset_id, description, asset_class, currency, par_price)``.
AETHER_ASSETS: tuple[tuple[str, str, str, str, str], ...] = (
    ("CASH-USD", "USD cash", "CASH", "USD", "100"),
    ("CASH-EUR", "EUR cash", "CASH", "EUR", "100"),
    ("US0000T6M01", "US Treasury bill, 6m", "SOVEREIGN_BOND", "USD", "99.42"),
    ("US0000T3Y02", "US Treasury note, 3y", "SOVEREIGN_BOND", "USD", "98.15"),
    ("US0000T7Y03", "US Treasury note, 7y", "SOVEREIGN_BOND", "USD", "96.80"),
    ("DE0000B5Y04", "German Bund, 5y", "SOVEREIGN_BOND", "EUR", "101.35"),
    ("IN0000G6Y05", "Government of India bond, 6y", "SOVEREIGN_BOND", "INR", "97.60"),
    (
        "US0000C3Y06",
        "Northwind Tech senior unsecured, 3y",
        "CORPORATE_BOND",
        "USD",
        "99.05",
    ),
    (
        "US0000C4Y07",
        "Contoso Industries senior unsecured, 4y",
        "CORPORATE_BOND",
        "USD",
        "97.90",
    ),
    ("US0000E0Y08", "Equity basket, S&P 500 constituents", "EQUITY", "USD", "100"),
    (
        "US0000C2Y09",
        "Meridian Global senior unsecured, 2y",
        "CORPORATE_BOND",
        "USD",
        "98.40",
    ),
    ("XAU-ALLOC-01", "Allocated gold, LBMA good delivery", "GOLD", "USD", "100"),
)


def _asset(index: int) -> dict[str, Any]:
    """One reference asset as a mapping, with its par price as a Decimal."""
    asset_id, description, asset_class, currency, par = AETHER_ASSETS[index]
    return {
        "asset_id": asset_id,
        "description": description,
        "asset_class": asset_class,
        "currency": currency,
        "par": Decimal(par),
    }


def _random_asset() -> dict[str, Any]:
    return _asset(int(rng.integers(0, len(AETHER_ASSETS))))


#: Custodians. Synthetic names and BICs in the correct shape; none is a real
#: institution and no connectivity to any of them exists.
CUSTODIANS: tuple[tuple[str, str], ...] = (
    ("Harbourgate Securities Services", "HRBGGB2LXXX"),
    ("Northmoor Global Custody", "NMORUS33XXX"),
    ("Sentinel Trust (IFSC)", "SNTLINBBXXX"),
    ("Calder Depositary AG", "CLDRDEFFXXX"),
)

#: Counterparties, each with the agreement it collateralises.
COUNTERPARTIES: tuple[tuple[str, str], ...] = (
    ("Meridian Global Markets", "CSA-MERIDIAN-2026"),
    ("Halberd Capital Partners", "CSA-HALBERD-2025"),
    ("Aurelia Bank International", "CSA-AURELIA-2026"),
)

ASSET_CLASS_VOL_BPS: dict[str, float] = {
    "CASH": 0.0,
    "SOVEREIGN_BOND": 45.0,
    "CORPORATE_BOND": 110.0,
    "EQUITY": 320.0,
    "GOLD": 180.0,
}


# ----------------------------------------------------------------- injection


@dataclass
class InjectionSpec:
    """One class of deliberate break, and how often it is applied."""

    code: str
    label: str
    rate: float
    mechanic: str
    expected_outcome: str


#: The injection plan. Rates are proportions of the generated position count and
#: are applied to disjoint samples, so a position carries at most one break — a
#: row with two overlapping defects cannot be scored cleanly.
#:
#: The classes are the ones a collateral operations team actually sees. The
#: account misdirection is the closest thing here to a fraud signal: collateral
#: booked to a sibling account that the internal ledger does not name.
INJECTIONS: tuple[InjectionSpec, ...] = (
    InjectionSpec(
        code="PRICE_NOISE_WITHIN_TOLERANCE",
        label="Valuation difference inside tolerance",
        rate=0.088,
        mechanic=(
            "Custodian price moved by 1-4 basis points against the internal mark. "
            "Two vendors pricing the same bond will not agree to the last cent."
        ),
        expected_outcome=(
            f"MATCHED. The difference is at or below the {TOLERANCE_BPS} bp "
            "tolerance and must not be raised as a break."
        ),
    ),
    InjectionSpec(
        code="VALUATION_BREAK",
        label="Valuation difference outside tolerance",
        rate=0.018,
        mechanic=(
            "Custodian price moved by 40-350 basis points. Typically a stale vendor "
            "feed or a disputed mark on an illiquid line."
        ),
        expected_outcome="MISMATCH on market value. Must be raised.",
    ),
    InjectionSpec(
        code="QUANTITY_BREAK",
        label="Nominal difference",
        rate=0.012,
        mechanic=(
            "Custodian nominal is 55-95% of the internal nominal — a partial "
            "settlement where only part of the delivery reached the account."
        ),
        expected_outcome="MISMATCH on nominal and market value. Must be raised.",
    ),
    InjectionSpec(
        code="MISSING_EXTERNAL",
        label="Present internally, absent at the custodian",
        rate=0.016,
        mechanic=(
            "Row removed from the custodian statement. The classic settlement-in-"
            "flight break: the bank has booked a delivery the custodian has not yet "
            "received."
        ),
        expected_outcome="MISSING_EXTERNAL. Must be raised and aged.",
    ),
    InjectionSpec(
        code="STALE_PRICE",
        label="Custodian priced as of the prior business day",
        rate=0.012,
        mechanic=(
            "Custodian row carries the previous day's price and a price_as_of of "
            "T-1. The size of the resulting difference depends on the asset class's "
            "daily volatility, so some stale marks fall inside tolerance and some "
            "do not — which is exactly the ambiguity a real screen must handle."
        ),
        expected_outcome=(
            "MISMATCH where the move exceeds tolerance, MATCHED where it does not. "
            "price_as_of is the evidence either way."
        ),
    ),
    InjectionSpec(
        code="ACCOUNT_MISDIRECTION",
        label="Booked to a sibling safekeeping account",
        rate=0.008,
        mechanic=(
            "Custodian booked the position to a different account at the same "
            "custodian. Benign as a keying error; the shape of a misappropriation "
            "if it is not."
        ),
        expected_outcome=(
            "MISSING_EXTERNAL on the expected account and MISSING_INTERNAL on the "
            "receiving account. A reconciliation that nets these two into 'matched' "
            "has hidden the finding."
        ),
    ),
    InjectionSpec(
        code="CURRENCY_MISLABEL",
        label="Currency code disagrees",
        rate=0.006,
        mechanic=(
            "Custodian reports the position in a different currency code while the "
            "amount is unchanged. An edge case that breaks naive comparison, because "
            "the numbers match and the values do not."
        ),
        expected_outcome=(
            "MISMATCH. Comparing amounts without comparing currency is the defect "
            "this case exists to catch."
        ),
    ),
)

#: Injections whose only signal is a difference in value or quantity. If the
#: position is worth nothing on both sides, they leave no trace and are not
#: recorded in the answer key. The structural injections — a booking on the wrong
#: account, a mislabelled currency — are excluded from this set because they are
#: detectable whatever the amount.
VALUE_BASED_INJECTIONS: frozenset[str] = frozenset(
    {
        "PRICE_NOISE_WITHIN_TOLERANCE",
        "VALUATION_BREAK",
        "STALE_PRICE",
        "QUANTITY_BREAK",
    }
)

#: Extra custodian rows with no internal counterpart. Not a proportion of the
#: internal ledger, because these positions do not exist there at all.
UNEXPECTED_RECEIPTS = 3


# ------------------------------------------------------------------ helpers


def _money(value: Decimal) -> str:
    """Two decimal places, banker's rounding. Money is never a float here."""
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN))


def _price(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN))


def _account(custodian_index: int, sequence: int) -> str:
    return f"SAFE-{custodian_index + 1:02d}-{sequence:05d}"


def _nominal_for(asset_class: str) -> Decimal:
    """A realistic lot size, including the odd lots that break naive formatting.

    Round millions dominate, but a real ledger also carries fragments left behind
    by partial returns and corporate actions, and the occasional fully amortised
    line sitting at zero. Both are included deliberately.
    """
    draw = rng.random()
    if draw < 0.04:
        return Decimal("0")  # fully returned or amortised — an edge case
    if draw < 0.16:
        return Decimal(str(round(float(rng.uniform(1_000, 90_000)), 2)))  # odd lot
    if asset_class == "CASH":
        return Decimal(int(rng.integers(1, 40)) * 250_000)
    return Decimal(int(rng.integers(1, 25)) * 500_000)


def _price_for(par: Decimal, asset_class: str) -> Decimal:
    """Clean price around par, dispersed by the asset class's daily volatility."""
    if asset_class == "CASH":
        return Decimal("100")
    vol = ASSET_CLASS_VOL_BPS[asset_class]
    shift = Decimal(str(round(float(rng.normal(0.0, vol / 100.0)), 4)))
    return max(par + shift, Decimal("1"))


def _market_value(nominal: Decimal, price: Decimal) -> Decimal:
    return (nominal * price / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)


# ---------------------------------------------------------------- generation


@dataclass
class Break:
    """One injected difference, recorded for the answer key."""

    position_id: str
    injection: str
    asset_id: str
    safekeeping_account: str
    detail: str
    internal_market_value: str
    external_market_value: str | None
    difference: str | None
    extra: dict[str, Any] = field(default_factory=dict)


def build_internal_ledger() -> pd.DataFrame:
    """The bank's own collateral record.

    Positions are spread unevenly across custodians and counterparties, because a
    real book concentrates: one custodian holds most of it and the tail is thin.
    """
    weights = np.array([0.44, 0.28, 0.19, 0.09])
    rows: list[dict[str, Any]] = []

    for sequence in range(POSITION_COUNT):
        asset = _random_asset()
        custodian_index = int(rng.choice(len(CUSTODIANS), p=weights))
        custodian, bic = CUSTODIANS[custodian_index]
        counterparty, agreement_id = COUNTERPARTIES[int(rng.integers(0, len(COUNTERPARTIES)))]

        nominal = _nominal_for(asset["asset_class"])
        price = _price_for(asset["par"], asset["asset_class"])
        rows.append(
            {
                "position_id": f"AE-POS-{sequence + 1:05d}",
                "as_of_date": AS_OF.isoformat(),
                "counterparty": counterparty,
                "agreement_id": agreement_id,
                "custodian": custodian,
                "custodian_bic": bic,
                "safekeeping_account": _account(custodian_index, sequence + 1),
                "asset_id": asset["asset_id"],
                "description": asset["description"],
                "asset_class": asset["asset_class"],
                "currency": asset["currency"],
                "nominal": str(nominal),
                "clean_price": _price(price),
                "market_value": _money(_market_value(nominal, price)),
                "direction": "POSTED" if rng.random() < 0.72 else "RECEIVED",
                "booked_by": fake.name(),
                "booking_reference": f"BKG-{fake.bothify('??####??').upper()}",
            }
        )

    return pd.DataFrame(rows)


def _disjoint_samples(size: int) -> dict[str, list[int]]:
    """Assign each injection class a disjoint sample of row indices.

    Disjoint because a position carrying two defects cannot be scored: a screen
    that reports one of the two is neither right nor wrong.
    """
    order = rng.permutation(size)
    cursor = 0
    assigned: dict[str, list[int]] = {}
    for spec in INJECTIONS:
        count = round(spec.rate * size)
        assigned[spec.code] = sorted(int(i) for i in order[cursor : cursor + count])
        cursor += count
    return assigned


def build_custodian_statement(
    internal: pd.DataFrame,
) -> tuple[pd.DataFrame, list[Break], dict[str, list[int]]]:
    """Mirror the internal ledger, then inject the documented breaks."""
    assigned = _disjoint_samples(len(internal))
    lookup = {code: set(rows) for code, rows in assigned.items()}
    breaks: list[Break] = []
    rows: list[dict[str, Any]] = []

    for index, position in internal.iterrows():
        nominal = Decimal(position["nominal"])
        price = Decimal(position["clean_price"])
        currency = position["currency"]
        account = position["safekeeping_account"]
        price_as_of = AS_OF
        internal_mv = Decimal(position["market_value"])
        applied: str | None = None
        detail = ""
        extra: dict[str, Any] = {}

        if index in lookup["MISSING_EXTERNAL"]:
            breaks.append(
                Break(
                    position_id=position["position_id"],
                    injection="MISSING_EXTERNAL",
                    asset_id=position["asset_id"],
                    safekeeping_account=account,
                    detail="Row withheld from the custodian statement.",
                    internal_market_value=str(internal_mv),
                    external_market_value=None,
                    difference=str(internal_mv),
                )
            )
            continue

        if index in lookup["PRICE_NOISE_WITHIN_TOLERANCE"]:
            applied = "PRICE_NOISE_WITHIN_TOLERANCE"
            bump = Decimal(str(round(float(rng.uniform(1, 4)), 2))) / Decimal("10000")
            price = price * (Decimal("1") + bump * _sign())
            detail = "Vendor price disagreement of 1-4 bp."

        elif index in lookup["VALUATION_BREAK"]:
            applied = "VALUATION_BREAK"
            bump = Decimal(str(round(float(rng.uniform(40, 350)), 2))) / Decimal("10000")
            price = price * (Decimal("1") + bump * _sign())
            detail = "Vendor price disagreement of 40-350 bp."

        elif index in lookup["QUANTITY_BREAK"]:
            applied = "QUANTITY_BREAK"
            fraction = Decimal(str(round(float(rng.uniform(0.55, 0.95)), 4)))
            nominal = (nominal * fraction).quantize(Decimal("0.01"))
            detail = f"Partial settlement: custodian holds {fraction:%} of the nominal."

        elif index in lookup["STALE_PRICE"]:
            applied = "STALE_PRICE"
            vol = ASSET_CLASS_VOL_BPS[position["asset_class"]]
            move = Decimal(str(round(float(rng.normal(0.0, vol / 100.0)), 4)))
            price = max(price + move, Decimal("1"))
            price_as_of = AS_OF - timedelta(days=1)
            detail = "Custodian carried the prior business day's price."
            extra["price_as_of"] = price_as_of.isoformat()

        elif index in lookup["ACCOUNT_MISDIRECTION"]:
            applied = "ACCOUNT_MISDIRECTION"
            sibling = f"{account[:-5]}{int(account[-5:]) + 500:05d}"
            detail = f"Custodian booked the position to {sibling}, not {account}."
            extra["expected_account"] = account
            extra["actual_account"] = sibling
            account = sibling

        elif index in lookup["CURRENCY_MISLABEL"]:
            applied = "CURRENCY_MISLABEL"
            currency = "EUR" if currency != "EUR" else "USD"
            detail = (
                f"Custodian reported {currency} against an internal "
                f"{position['currency']} position."
            )
            extra["internal_currency"] = position["currency"]
            extra["external_currency"] = currency

        market_value = _market_value(nominal, price)

        rows.append(
            {
                "statement_id": f"STMT-{AS_OF:%Y%m%d}-{position['custodian_bic'][:4]}",
                "statement_date": AS_OF.isoformat(),
                "custodian": position["custodian"],
                "custodian_bic": position["custodian_bic"],
                "safekeeping_account": account,
                "asset_id": position["asset_id"],
                "description": position["description"],
                "asset_class": position["asset_class"],
                "currency": currency,
                "nominal": str(nominal),
                "price": _price(price),
                "price_as_of": price_as_of.isoformat(),
                "market_value": _money(market_value),
                "custodian_reference": f"CST-{fake.bothify('########').upper()}",
            }
        )

        # A price or quantity move applied to a zero-nominal position produces no
        # difference at all: both sides value at zero and carry the same nominal.
        # Recording that as an injected break would put a row in the answer key
        # that no reconciliation can detect, and would score a correct engine as
        # having missed something.
        #
        # Only the value-based classes are eligible for this. A misdirected
        # booking or a mislabelled currency is detectable regardless of amount —
        # that is the entire point of those two cases.
        if applied in VALUE_BASED_INJECTIONS and internal_mv == market_value:
            applied = None

        if applied:
            breaks.append(
                Break(
                    position_id=position["position_id"],
                    injection=applied,
                    asset_id=position["asset_id"],
                    safekeeping_account=position["safekeeping_account"],
                    detail=detail,
                    internal_market_value=str(internal_mv),
                    external_market_value=str(market_value),
                    difference=str(internal_mv - market_value),
                    extra=extra,
                )
            )

    rows.extend(_unexpected_receipts(breaks))
    return pd.DataFrame(rows), breaks, assigned


def _sign() -> Decimal:
    return Decimal("1") if rng.random() < 0.5 else Decimal("-1")


def _unexpected_receipts(breaks: list[Break]) -> list[dict[str, Any]]:
    """Custodian rows with no internal counterpart.

    An unexpected receipt is the mirror image of a settlement-in-flight break: the
    custodian holds something the ledger does not know about. Left undetected, the
    bank under-reports its collateral.
    """
    rows: list[dict[str, Any]] = []
    for sequence in range(UNEXPECTED_RECEIPTS):
        asset = _random_asset()
        custodian_index = int(rng.integers(0, len(CUSTODIANS)))
        custodian, bic = CUSTODIANS[custodian_index]
        account = _account(custodian_index, 900 + sequence)
        nominal = _nominal_for(asset["asset_class"])
        price = _price_for(asset["par"], asset["asset_class"])
        market_value = _market_value(nominal, price)

        rows.append(
            {
                "statement_id": f"STMT-{AS_OF:%Y%m%d}-{bic[:4]}",
                "statement_date": AS_OF.isoformat(),
                "custodian": custodian,
                "custodian_bic": bic,
                "safekeeping_account": account,
                "asset_id": asset["asset_id"],
                "description": asset["description"],
                "asset_class": asset["asset_class"],
                "currency": asset["currency"],
                "nominal": str(nominal),
                "price": _price(price),
                "price_as_of": AS_OF.isoformat(),
                "market_value": _money(market_value),
                "custodian_reference": f"CST-{fake.bothify('########').upper()}",
            }
        )
        breaks.append(
            Break(
                position_id="",
                injection="MISSING_INTERNAL",
                asset_id=asset["asset_id"],
                safekeeping_account=account,
                detail="Custodian holds a position the internal ledger does not carry.",
                internal_market_value="0.00",
                external_market_value=str(market_value),
                difference=str(-market_value),
            )
        )
    return rows


# -------------------------------------------------------------------- output

PROVENANCE: dict[str, Any] = {
    "simulated": True,
    "authored": "2026-08-21",
    "basis": (
        "Synthetic. Position structure modelled on a tri-party collateral "
        "safekeeping statement; break classes modelled on the standard collateral "
        "reconciliation exception types."
    ),
    "generator": "scripts/generate_reconciliation_data.py",
    "seed": SEED,
    "warning": "SIMULATED DATA - not real institutional data.",
    "identifiers": (
        "Asset identifiers are ISIN-shaped and are not real ISINs. Custodian names, "
        "BICs, account numbers, counterparties and staff names are invented."
    ),
}


def write_manifest(
    internal: pd.DataFrame,
    external: pd.DataFrame,
    breaks: list[Break],
    assigned: dict[str, list[int]],
) -> dict[str, Any]:
    """The answer key, and the documentation of how it was produced."""
    counts: dict[str, int] = {}
    for item in breaks:
        counts[item.injection] = counts.get(item.injection, 0) + 1

    manifest = {
        "_provenance": PROVENANCE,
        "as_of": AS_OF.isoformat(),
        "tolerance_bps": str(TOLERANCE_BPS),
        "tolerance_note": (
            "A market value difference at or below this tolerance is a rounding or "
            "vendor-pricing artefact and reconciles as MATCHED. Above it, the row is "
            "a break. Injected PRICE_NOISE_WITHIN_TOLERANCE rows exist to prove the "
            "tolerance is applied rather than ignored."
        ),
        "internal_rows": len(internal),
        "external_rows": len(external),
        "injected_differences": len(breaks),
        "injected_exceptions": len(breaks) - counts.get("PRICE_NOISE_WITHIN_TOLERANCE", 0),
        "exception_rate": round(
            (len(breaks) - counts.get("PRICE_NOISE_WITHIN_TOLERANCE", 0)) / len(internal), 4
        ),
        "noise_rate": round(counts.get("PRICE_NOISE_WITHIN_TOLERANCE", 0) / len(internal), 4),
        "rate_note": (
            "Two rates, deliberately separated. exception_rate is what a "
            "reconciliation should raise. noise_rate is within-tolerance price "
            "disagreement that it should absorb silently. A single blended figure "
            "would flatter any engine that raises everything."
        ),
        "injection_classes": [
            {
                **asdict(spec),
                "planned_rows": len(assigned.get(spec.code, [])),
                "injected_rows": counts.get(spec.code, 0),
            }
            for spec in INJECTIONS
        ]
        + [
            {
                "code": "MISSING_INTERNAL",
                "label": "Present at the custodian, absent internally",
                "rate": round(UNEXPECTED_RECEIPTS / len(internal), 4),
                "mechanic": (
                    f"{UNEXPECTED_RECEIPTS} custodian rows added on accounts the "
                    "internal ledger does not carry - an unexpected receipt."
                ),
                "expected_outcome": "MISSING_INTERNAL. Must be raised.",
                "planned_rows": UNEXPECTED_RECEIPTS,
                "injected_rows": counts.get("MISSING_INTERNAL", 0),
            }
        ],
        "matching_key": ["safekeeping_account", "asset_id"],
        "matching_note": (
            "Account plus asset is the natural key a collateral team reconciles on. "
            "It is deliberately not position_id: the custodian has never seen the "
            "bank's internal position identifier, which is what makes the "
            "ACCOUNT_MISDIRECTION case detectable at all."
        ),
        "planned_vs_injected": (
            "planned_rows is how many positions each class was applied to. "
            "injected_rows is how many produced an observable difference. They "
            "differ where a price move landed on a zero-nominal position, which "
            "values at zero on both sides: no difference exists, so none is "
            "claimed in the answer key."
        ),
        "edge_cases": [
            "Zero-nominal positions, fully returned or amortised.",
            "Odd lots with fractional nominals, left by partial returns.",
            "A three-currency book: USD, EUR and INR amounts are not summable "
            "without an FX conversion, and the reconciliation does not perform one.",
            "Uneven custodian concentration - one custodian holds most of the book.",
        ],
        "scoring": (
            "Treat 'breaks' below as ground truth. Precision and recall over the "
            "raised exceptions measure a reconciliation engine; a row listed as "
            "PRICE_NOISE_WITHIN_TOLERANCE that is raised as a break is a false "
            "positive, not a catch."
        ),
        "breaks": [asdict(item) for item in breaks],
    }
    return manifest


def csv_header() -> str:
    return (
        f"# SIMULATED DATA - generated by scripts/generate_reconciliation_data.py, "
        f"seed {SEED}, as of {AS_OF.isoformat()}.\n"
        f"# Not real institutional data. Identifiers are format-shaped and invented.\n"
    )


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    internal = build_internal_ledger()
    external, breaks, assigned = build_custodian_statement(internal)
    manifest = write_manifest(internal, external, breaks, assigned)

    for name, frame in (
        ("internal_ledger.csv", internal),
        ("custodian_statement.csv", external),
    ):
        path = OUT / name
        path.write_text(
            csv_header() + frame.to_csv(index=False, lineterminator="\n"),
            encoding="utf-8",
        )
        print(f"  {path.relative_to(ROOT)}  {len(frame)} rows")

    manifest_path = OUT / "injection_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"  {manifest_path.relative_to(ROOT)}  {len(breaks)} documented breaks")

    print()
    print(
        f"  exceptions {manifest['exception_rate']:.1%}  "
        f"within-tolerance noise {manifest['noise_rate']:.1%}  "
        f"across {len(internal)} positions"
    )
    for entry in manifest["injection_classes"]:
        print(f"    {entry['code']:<30} {entry['injected_rows']:>3}")


if __name__ == "__main__":
    main()
