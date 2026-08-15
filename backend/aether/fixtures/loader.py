"""Fixture loading.

Parses the simulated JSON fixtures in ``/fixtures`` into deterministic-core value
objects. This module performs I/O, so it lives **outside** ``aether.core`` — the core
receives fully-formed values and never reads a file itself.

Two loaders, two guarantees, deliberately not merged:

:func:`load_json`
    **Simulated only.** ``_provenance.simulated`` must be exactly ``true``. Every
    fixture the demo path reads comes through here, so no real data can reach the
    engine by this route. Not negotiable per-file.

:func:`load_ingested_json`
    **Real published data, pinned at ingest.** Requires ``simulated: false``, an
    affirmative ``ingested: true`` marker, a named source and a parseable ISO
    ``fetched_at``. Nothing on the demo path calls it.

Keeping them apart means supporting sourced external data never required relaxing the
simulated-only guarantee, and a reader can grep one name to find every place real
data could possibly be read.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any

from aether.core.collateral import CollateralAsset, CollateralInventory
from aether.core.csa_terms import (
    AssetClass,
    ConcentrationLimit,
    ConcentrationScope,
    CSATerms,
    EligibleCollateralItem,
    IssuerType,
    Party,
    PartyTerms,
    RoundingTerms,
)
from aether.core.curves import DiscountCurve
from aether.core.instruments import (
    FXForward,
    InterestRateSwap,
    Portfolio,
    SwapDirection,
    Trade,
)
from aether.core.market import MarketSnapshot
from aether.core.money import Currency, Money, RoundingDirection

__all__ = [
    "FIXTURES_ROOT",
    "ProvenanceError",
    "load_agreement",
    "load_ingested_json",
    "load_inventory",
    "load_json",
    "load_portfolio",
    "load_snapshot",
    "load_snapshots",
]

#: Repository ``fixtures/`` directory, resolved from this file's location so the
#: loader works regardless of the process working directory.
FIXTURES_ROOT: Path = Path(__file__).resolve().parents[3] / "fixtures"


class ProvenanceError(RuntimeError):
    """Raised when a fixture does not account for where its data came from."""


def _read_object(relative_path: str | Path) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """Read a fixture and return its path, body and ``_provenance`` block.

    Shared by both loaders so the parsing is identical and only the provenance
    *policy* differs between them.
    """
    path = FIXTURES_ROOT / relative_path
    if not path.exists():
        raise FileNotFoundError(f"Fixture not found: {path}")

    data: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must contain a JSON object at the top level.")

    provenance = data.get("_provenance")
    if not isinstance(provenance, dict):
        raise ProvenanceError(
            f"{path.name} has no '_provenance' block. Every fixture must account for "
            "where its data came from."
        )
    return path, data, provenance


def load_json(relative_path: str | Path) -> dict[str, Any]:
    """Read a **simulated** fixture and verify its provenance before returning it.

    ``simulated: true`` is required, explicitly, with no alternative. Every fixture
    the demo path loads — agreements, portfolios, inventories, market snapshots —
    comes through here, so the guarantee is a single bit and it is total: **no real
    data can enter the engine through this function.**

    That matters beyond tidiness. The product claims everywhere that its data is
    simulated, and CLAUDE.md forbids confidential or real institutional documents.
    This check is what makes both structurally true rather than merely written down,
    and it is deliberately not negotiable per-file.

    Real published data has its own door: :func:`load_ingested_json`. Keeping the two
    separate means the strict guarantee here never has to be relaxed to accommodate
    it, and a reader can grep for the ingested path to find every place real data
    could possibly be read.
    """
    path, data, provenance = _read_object(relative_path)
    if provenance.get("simulated") is not True:
        raise ProvenanceError(
            f"{path.name} does not declare '_provenance.simulated: true'. The demo "
            f"fixture path is simulated-only. Real published data must be loaded "
            f"through load_ingested_json(), which requires an explicit 'ingested' "
            f"marker, a named source and a valid fetch date."
        )
    return data


def load_ingested_json(relative_path: str | Path) -> dict[str, Any]:
    """Read a fixture holding **real published data**, pinned at ingest.

    A separate, explicitly-named door. Four conditions, all required:

    ``simulated: false``   the file does not pretend to be synthetic
    ``ingested: true``     an affirmative marker, so this branch is never reached
                           by omission or by a missing key
    ``source``             a non-trivial named origin
    ``fetched_at``         an ISO date that actually parses

    Written by ``scripts/fetch_snapshot.py``. The engine still reads only a pinned
    file: ingestion happens *before* a calculation, never inside one, so determinism
    is unaffected — data is live at ingest and pinned at calculation.

    Nothing on the demo path calls this. It exists so that "AETHER can ingest real
    published market data" is a checkable claim rather than an aspiration, without
    widening the guarantee that :func:`load_json` provides.
    """
    path, data, provenance = _read_object(relative_path)

    if provenance.get("simulated") is not False:
        raise ProvenanceError(
            f"{path.name} must declare '_provenance.simulated: false' to be loaded as "
            f"ingested data. Simulated fixtures belong in load_json()."
        )
    if provenance.get("ingested") is not True:
        raise ProvenanceError(
            f"{path.name} does not declare '_provenance.ingested: true'. Real data "
            f"must say so affirmatively; this path is never reached by omission."
        )

    source = provenance.get("source")
    if not isinstance(source, str) or len(source.strip()) < 8:
        raise ProvenanceError(
            f"{path.name} does not name a usable '_provenance.source'. Real data must "
            f"say where it came from."
        )

    fetched_at = provenance.get("fetched_at")
    if not isinstance(fetched_at, str):
        raise ProvenanceError(f"{path.name} has no '_provenance.fetched_at' date.")
    try:
        date.fromisoformat(fetched_at)
    except ValueError as exc:
        raise ProvenanceError(
            f"{path.name} has '_provenance.fetched_at' = {fetched_at!r}, which is not "
            f"a valid ISO date. An unparseable date is not a provenance record."
        ) from exc

    return data


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


# ---------------------------------------------------------------- market


def _build_curve(currency: Currency, as_of: date, raw: dict[str, Any]) -> DiscountCurve:
    return DiscountCurve(
        currency=currency,
        as_of=as_of,
        pillars_years=tuple(float(t) for t in raw["pillars_years"]),
        zero_rates=tuple(float(z) for z in raw["zero_rates"]),
    )


def _build_snapshot(raw: dict[str, Any]) -> MarketSnapshot:
    as_of = _parse_date(raw["as_of"])
    curves = {
        Currency(code): _build_curve(Currency(code), as_of, curve_raw)
        for code, curve_raw in raw["curves"].items()
    }
    fx_spot = {
        pair: Decimal(rate) for pair, rate in raw["fx_spot"].items() if not pair.startswith("_")
    }
    return MarketSnapshot(
        snapshot_id=raw["snapshot_id"],
        as_of=as_of,
        label=raw["label"],
        curves=curves,
        fx_spot=fx_spot,
        simulated=True,
    )


@lru_cache(maxsize=1)
def load_snapshots(path: str = "market/snapshots.json") -> dict[str, MarketSnapshot]:
    """Load every market snapshot, keyed by ``snapshot_id``."""
    data = load_json(path)
    return {raw["snapshot_id"]: _build_snapshot(raw) for raw in data["snapshots"]}


def load_snapshot(snapshot_id: str, path: str = "market/snapshots.json") -> MarketSnapshot:
    """Load one pinned snapshot by id."""
    snapshots = load_snapshots(path)
    try:
        return snapshots[snapshot_id]
    except KeyError:
        raise KeyError(
            f"Unknown snapshot '{snapshot_id}'. Available: {sorted(snapshots)}."
        ) from None


# ------------------------------------------------------------- portfolio


def _build_trade(raw: dict[str, Any]) -> Trade:
    kind = raw["type"]

    if kind == "INTEREST_RATE_SWAP":
        return InterestRateSwap(
            trade_id=raw["trade_id"],
            netting_set_id=raw["netting_set_id"],
            notional=Decimal(raw["notional"]),
            currency=Currency(raw["currency"]),
            direction=SwapDirection(raw["direction"]),
            fixed_rate=Decimal(raw["fixed_rate"]),
            payment_frequency_months=int(raw["payment_frequency_months"]),
            effective_date=_parse_date(raw["effective_date"]),
            maturity_date=_parse_date(raw["maturity_date"]),
            float_index=raw.get("float_index", ""),
        )

    if kind == "FX_FORWARD":
        return FXForward(
            trade_id=raw["trade_id"],
            netting_set_id=raw["netting_set_id"],
            buy_currency=Currency(raw["buy_currency"]),
            buy_notional=Decimal(raw["buy_notional"]),
            sell_currency=Currency(raw["sell_currency"]),
            strike=Decimal(raw["strike"]),
            maturity_date=_parse_date(raw["maturity_date"]),
        )

    raise ValueError(f"Unsupported trade type '{kind}' in fixture.")


def load_portfolio(path: str = "portfolios/meridian_netting_set.json") -> Portfolio:
    """Load the simulated derivatives book as a single-netting-set portfolio."""
    data = load_json(path)
    return Portfolio(
        portfolio_id=data["portfolio_id"],
        netting_set_id=data["netting_set_id"],
        trades=tuple(_build_trade(raw) for raw in data["trades"]),
        book_owner=data.get("book_owner", "PARTY_A"),
    )


# ------------------------------------------------------------- agreement


def _money(raw: dict[str, Any]) -> Money:
    return Money(Decimal(raw["amount"]), Currency(raw["currency"]))


def _optional_decimal(value: Any) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _build_party_terms(raw: dict[str, Any]) -> PartyTerms:
    return PartyTerms(
        party=Party(raw["party"]),
        threshold=_money(raw["threshold"]),
        minimum_transfer_amount=_money(raw["minimum_transfer_amount"]),
        independent_amount=_money(raw["independent_amount"]),
        legal_name=str(raw.get("legal_name", "")),
    )


def _build_eligible_item(raw: dict[str, Any]) -> EligibleCollateralItem:
    currency = raw.get("currency")
    return EligibleCollateralItem(
        ref=raw["ref"],
        asset_class=AssetClass(raw["asset_class"]),
        valuation_percentage=Decimal(raw["valuation_percentage"]),
        issuer_type=IssuerType(raw["issuer_type"]),
        issuer=raw.get("issuer"),
        currency=Currency(currency) if currency else None,
        non_base_currency_only=bool(raw.get("non_base_currency_only", False)),
        min_maturity_years=_optional_decimal(raw.get("min_maturity_years")),
        max_maturity_years=_optional_decimal(raw.get("max_maturity_years")),
        min_rating=raw.get("min_rating"),
        index_membership=tuple(raw.get("index_membership", ())),
    )


def load_agreement(path: str = "agreements/meridian_agreement.json") -> CSATerms:
    """Load frozen, reviewer-confirmed CSA terms.

    In the live pipeline these come from a confirmed terms version produced by the
    Legal-Clause Agent. The fixture exists so the deterministic engine can be built
    and tested before the agent does.
    """
    data = load_json(path)
    return CSATerms(
        agreement_id=data["agreement_id"],
        netting_set_id=data["netting_set_id"],
        base_currency=Currency(data["base_currency"]),
        eligible_currencies=frozenset(Currency(c) for c in data["eligible_currencies"]),
        party_a=_build_party_terms(data["party_a"]),
        party_b=_build_party_terms(data["party_b"]),
        rounding=RoundingTerms(
            increment=_money(data["rounding"]["increment"]),
            delivery_direction=RoundingDirection(data["rounding"]["delivery_direction"]),
            return_direction=RoundingDirection(data["rounding"]["return_direction"]),
        ),
        fx_haircut_pct=Decimal(data["fx_haircut_pct"]),
        eligible_collateral=tuple(_build_eligible_item(raw) for raw in data["eligible_collateral"]),
        concentration_limits=tuple(
            ConcentrationLimit(
                scope=ConcentrationScope(raw["scope"]),
                limit_percentage=Decimal(raw["limit_percentage"]),
            )
            for raw in data["concentration_limits"]
        ),
        mta_before_rounding=bool(data.get("mta_before_rounding", True)),
        excluded_issuers=frozenset(data.get("excluded_issuers", ())),
        csa_type=data.get("csa_type", "2016_ISDA_VM_CSA"),
        governing_law=data.get("governing_law", ""),
        terms_version=int(data.get("terms_version", 1)),
    )


# ------------------------------------------------------------- inventory


def load_inventory(path: str = "collateral/aether_inventory.json") -> CollateralInventory:
    """Load the simulated collateral inventory available to post."""
    data = load_json(path)
    assets = tuple(
        CollateralAsset(
            asset_id=raw["asset_id"],
            description=raw["description"],
            asset_class=AssetClass(raw["asset_class"]),
            issuer=raw["issuer"],
            issuer_type=IssuerType(raw["issuer_type"]),
            currency=Currency(raw["currency"]),
            available_market_value=Decimal(raw["available_market_value"]),
            funding_spread_bps=Decimal(str(raw["funding_spread_bps"])),
            remaining_maturity_years=_optional_decimal(raw.get("remaining_maturity_years")),
            rating=raw.get("rating"),
            index_membership=raw.get("index_membership"),
        )
        for raw in data["assets"]
    )
    return CollateralInventory(
        inventory_id=data["inventory_id"],
        owner=data["owner"],
        assets=assets,
    )
