"""Collateral assets and balances.

An inventory of assets available to post, and the balance already posted under an
agreement. Both are plain immutable values; eligibility and haircut logic lives in
:mod:`aether.core.haircut`, and allocation in :mod:`aether.core.optimize`.

Part of the deterministic core: no I/O, no clock, no framework dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from aether.core.csa_terms import AssetClass, IssuerType
from aether.core.money import Currency, Money

__all__ = ["CollateralAsset", "CollateralInventory", "PostedCollateral"]


@dataclass(frozen=True, slots=True)
class CollateralAsset:
    """One line of the collateral inventory.

    ``funding_spread_bps`` is the annualised cost of encumbering the asset — the
    opportunity cost of not being able to deploy or repo it elsewhere. It is the
    objective coefficient of the optimizer, and it is why cash is expensive despite
    a 100% valuation percentage.
    """

    asset_id: str
    description: str
    asset_class: AssetClass
    issuer: str
    issuer_type: IssuerType
    currency: Currency
    available_market_value: Decimal
    funding_spread_bps: Decimal
    remaining_maturity_years: Decimal | None = None
    rating: str | None = None
    index_membership: str | None = None

    def __post_init__(self) -> None:
        if self.available_market_value < 0:
            raise ValueError(f"{self.asset_id}: available market value must not be negative.")
        if self.funding_spread_bps < 0:
            raise ValueError(f"{self.asset_id}: funding spread must not be negative.")

    @property
    def available(self) -> Money:
        return Money(self.available_market_value, self.currency)


@dataclass(frozen=True, slots=True)
class CollateralInventory:
    """Assets a party has available to post."""

    inventory_id: str
    owner: str
    assets: tuple[CollateralAsset, ...]
    simulated: bool = True

    def __post_init__(self) -> None:
        seen: set[str] = set()
        for asset in self.assets:
            if asset.asset_id in seen:
                raise ValueError(f"Duplicate asset id {asset.asset_id} in {self.inventory_id}.")
            seen.add(asset.asset_id)

    def by_id(self, asset_id: str) -> CollateralAsset:
        for asset in self.assets:
            if asset.asset_id == asset_id:
                return asset
        raise KeyError(f"No asset {asset_id} in inventory {self.inventory_id}.")

    def __len__(self) -> int:
        return len(self.assets)


@dataclass(frozen=True, slots=True)
class PostedCollateral:
    """One line of an existing Credit Support Balance."""

    asset_id: str
    market_value: Money
    posted_by: str
