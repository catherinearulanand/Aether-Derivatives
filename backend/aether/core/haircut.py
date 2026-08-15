"""Eligibility and haircuts — quantitative function F8.

Two things happen here, and the order matters:

1. **Eligibility.** An asset must match a row of the CSA's Eligible Credit Support
   table on asset class, issuer, currency, remaining maturity, rating and index
   membership. It must also survive the wrong-way exclusion — CSA Paragraph
   11(g)(iv) forbids posting paper issued by the Transferor, its affiliates, or any
   entity whose creditworthiness is materially correlated with the Transferor's. In
   practice for this prototype that means **the counterparty's own paper is never
   eligible**, however cheap and however well it matches the table.

2. **Valuation.** The effective valuation percentage is the table's percentage
   reduced multiplicatively by the FX haircut when the asset is not denominated in
   the base currency::

       effective_pct = valuation_pct * (1 - fx_haircut_pct)

   The Meridian CSA states this at Paragraph 11(g)(i) and supplies its own worked
   example — ``94% x 92% = 86.48%`` — which the golden tests use as an expected
   value authored independently of this code.

Part of the deterministic core: no I/O, no clock, no framework dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from aether.core.collateral import CollateralAsset
from aether.core.csa_terms import (
    CSATerms,
    EligibleCollateralItem,
    IssuerType,
    rating_meets,
)
from aether.core.market import MarketSnapshot
from aether.core.money import Currency, Money, quantize_money

__all__ = [
    "EligibilityResult",
    "assess_eligibility",
    "effective_valuation_percentage",
    "effective_value",
    "post_haircut_value",
]


@dataclass(frozen=True, slots=True)
class EligibilityResult:
    """Whether an asset may be posted, and at what effective valuation."""

    asset_id: str
    eligible: bool
    reason: str
    matched_item: EligibleCollateralItem | None = None
    valuation_percentage: Decimal = Decimal(0)
    fx_haircut_applied: bool = False
    effective_percentage: Decimal = Decimal(0)


def _matches_kind(item: EligibleCollateralItem, asset: CollateralAsset) -> bool:
    if item.asset_class is not asset.asset_class or item.issuer_type is not asset.issuer_type:
        return False
    return item.issuer is None or item.issuer == asset.issuer


def _matches_currency(item: EligibleCollateralItem, asset: CollateralAsset, base: Currency) -> bool:
    """Cash rows are currency-specific: one for the base currency, one for the rest."""
    if item.currency is not None and item.currency is not asset.currency:
        return False
    return not (item.non_base_currency_only and asset.currency is base)


def _matches_maturity(item: EligibleCollateralItem, asset: CollateralAsset) -> bool:
    """Bands are exclusive at the lower bound and inclusive at the upper.

    That is how the CSA phrases them: "more than one year but not more than five
    years". An asset with no maturity (cash) cannot satisfy a banded row.
    """
    if item.min_maturity_years is None and item.max_maturity_years is None:
        return True
    if asset.remaining_maturity_years is None:
        return False
    if (
        item.min_maturity_years is not None
        and asset.remaining_maturity_years <= item.min_maturity_years
    ):
        return False
    return not (
        item.max_maturity_years is not None
        and asset.remaining_maturity_years > item.max_maturity_years
    )


def _matches_credit(item: EligibleCollateralItem, asset: CollateralAsset) -> bool:
    if item.min_rating is None:
        return True
    return asset.rating is not None and rating_meets(asset.rating, item.min_rating)


def _matches_index(item: EligibleCollateralItem, asset: CollateralAsset) -> bool:
    if not item.index_membership:
        return True
    return asset.index_membership in item.index_membership


def _matches(item: EligibleCollateralItem, asset: CollateralAsset, base: Currency) -> bool:
    """Does ``asset`` satisfy every condition of this eligibility row?"""
    return (
        _matches_kind(item, asset)
        and _matches_currency(item, asset, base)
        and _matches_maturity(item, asset)
        and _matches_credit(item, asset)
        and _matches_index(item, asset)
    )


def effective_valuation_percentage(
    valuation_percentage: Decimal,
    asset_currency: Currency,
    terms: CSATerms,
) -> tuple[Decimal, bool]:
    """Apply the FX haircut multiplicatively. Returns ``(effective_pct, fx_applied)``."""
    if asset_currency is terms.base_currency:
        return valuation_percentage, False
    effective = valuation_percentage * (Decimal(1) - terms.fx_haircut_pct)
    return effective, True


def assess_eligibility(
    asset: CollateralAsset,
    terms: CSATerms,
    transferor_excluded_issuers: frozenset[str] = frozenset(),
) -> EligibilityResult:
    """Decide whether ``asset`` may be posted under ``terms``.

    ``transferor_excluded_issuers`` carries the wrong-way exclusion: the Transferor
    itself, its affiliates, and — critically for this prototype — the counterparty
    receiving the collateral.
    """
    excluded = terms.excluded_issuers | transferor_excluded_issuers
    if asset.issuer in excluded:
        return EligibilityResult(
            asset_id=asset.asset_id,
            eligible=False,
            reason=(
                f"Wrong-way risk: {asset.issuer} is an excluded issuer under CSA "
                f"Paragraph 11(g)(iv)."
            ),
        )

    if asset.currency not in terms.eligible_currencies:
        return EligibilityResult(
            asset_id=asset.asset_id,
            eligible=False,
            reason=f"{asset.currency} is not an Eligible Currency under this Annex.",
        )

    for item in terms.eligible_collateral:
        if not _matches(item, asset, terms.base_currency):
            continue

        effective, fx_applied = effective_valuation_percentage(
            item.valuation_percentage, asset.currency, terms
        )
        detail = f"Eligible under item ({item.ref})"
        if fx_applied:
            detail += (
                f"; valuation {item.valuation_percentage:%} reduced by "
                f"{terms.fx_haircut_pct:%} FX haircut to {effective:%}"
            )
        return EligibilityResult(
            asset_id=asset.asset_id,
            eligible=True,
            reason=detail,
            matched_item=item,
            valuation_percentage=item.valuation_percentage,
            fx_haircut_applied=fx_applied,
            effective_percentage=effective,
        )

    return EligibilityResult(
        asset_id=asset.asset_id,
        eligible=False,
        reason="No row of the Eligible Credit Support schedule matches this asset.",
    )


def effective_value(
    market_value: Money,
    effective_percentage: Decimal,
    snapshot: MarketSnapshot,
    base_currency: Currency,
) -> Money:
    """Post-haircut value of ``market_value``, converted to the base currency."""
    haircut_native = Money(
        quantize_money(market_value.amount * effective_percentage), market_value.currency
    )
    return snapshot.convert(haircut_native, base_currency)


def post_haircut_value(
    asset: CollateralAsset,
    market_value: Money,
    terms: CSATerms,
    snapshot: MarketSnapshot,
) -> Money:
    """Convenience: assess eligibility then value. Raises if the asset is ineligible."""
    assessment = assess_eligibility(asset, terms)
    if not assessment.eligible:
        raise ValueError(f"{asset.asset_id} is not eligible: {assessment.reason}")
    return effective_value(
        market_value, assessment.effective_percentage, snapshot, terms.base_currency
    )


def issuer_type_of(asset: CollateralAsset) -> IssuerType:
    """Exposed for the optimizer's concentration constraints."""
    return asset.issuer_type
