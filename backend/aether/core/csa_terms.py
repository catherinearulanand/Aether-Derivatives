"""Typed CSA terms — the boundary between extraction and computation.

This is the schema every contractual value must cross through. The Legal-Clause Agent
(Phase 5) produces a candidate; a reviewer confirms it; the confirmed version is
frozen into an agreement. From that point the deterministic engine reads *only* this
structure, and no model output reaches a calculation.

Terms are expressed from each party's own perspective, because a CSA parameter is
always party-specific: Party A's Threshold is not Party B's. Which party's terms
apply to a given margin call depends on who the Transferor is, which in turn depends
on the sign of the exposure. That resolution happens in :mod:`aether.core.csa`.

Part of the deterministic core: no I/O, no clock, no framework dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

from aether.core.money import Currency, Money, RoundingDirection

__all__ = [
    "AssetClass",
    "CSATerms",
    "ConcentrationLimit",
    "ConcentrationScope",
    "EligibleCollateralItem",
    "IssuerType",
    "Party",
    "PartyTerms",
    "RoundingTerms",
]


class Party(StrEnum):
    PARTY_A = "PARTY_A"
    PARTY_B = "PARTY_B"

    @property
    def other(self) -> Party:
        return Party.PARTY_B if self is Party.PARTY_A else Party.PARTY_A


class AssetClass(StrEnum):
    CASH = "CASH"
    SOVEREIGN_BOND = "SOVEREIGN_BOND"
    CORPORATE_BOND = "CORPORATE_BOND"
    EQUITY = "EQUITY"
    #: Allocated bullion. A distinct class because it is neither an issuer's
    #: liability nor an equity claim: it has no credit rating and no maturity, so
    #: the eligibility predicates that key on those must not apply to it.
    GOLD = "GOLD"


class IssuerType(StrEnum):
    CASH = "CASH"
    SOVEREIGN = "SOVEREIGN"
    CORPORATE = "CORPORATE"
    #: Bullion has no issuer. Named rather than left blank so eligibility matching
    #: stays total and a missing issuer type can never silently match a row.
    NONE = "NONE"


class ConcentrationScope(StrEnum):
    """What a concentration limit is measured over."""

    SINGLE_NON_SOVEREIGN_ISSUER = "SINGLE_NON_SOVEREIGN_ISSUER"
    CORPORATE_BOND = "CORPORATE_BOND"
    EQUITY = "EQUITY"
    GOLD = "GOLD"


#: Credit ratings ordered best to worst, for eligibility comparison.
_RATING_ORDER: tuple[str, ...] = (
    "AAA",
    "AA+",
    "AA",
    "AA-",
    "A+",
    "A",
    "A-",
    "BBB+",
    "BBB",
    "BBB-",
    "BB+",
    "BB",
    "BB-",
    "B+",
    "B",
    "B-",
)


def rating_meets(actual: str, minimum: str) -> bool:
    """True when ``actual`` is at least as good as ``minimum``."""
    if actual not in _RATING_ORDER:
        raise ValueError(f"Unknown rating '{actual}'.")
    if minimum not in _RATING_ORDER:
        raise ValueError(f"Unknown minimum rating '{minimum}'.")
    return _RATING_ORDER.index(actual) <= _RATING_ORDER.index(minimum)


@dataclass(frozen=True, slots=True)
class EligibleCollateralItem:
    """One row of the CSA's Eligible Credit Support table.

    ``valuation_percentage`` is the headline haircut from the agreement. The FX
    haircut in :attr:`CSATerms.fx_haircut_pct` applies on top, multiplicatively, and
    is handled in :mod:`aether.core.haircut` rather than baked in here.
    """

    ref: str
    asset_class: AssetClass
    valuation_percentage: Decimal
    issuer_type: IssuerType
    issuer: str | None = None
    currency: Currency | None = None
    non_base_currency_only: bool = False
    min_maturity_years: Decimal | None = None
    max_maturity_years: Decimal | None = None
    min_rating: str | None = None
    index_membership: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not (Decimal(0) < self.valuation_percentage <= Decimal(1)):
            raise ValueError(
                f"Item {self.ref}: valuation percentage must be in (0, 1], "
                f"got {self.valuation_percentage}."
            )


@dataclass(frozen=True, slots=True)
class ConcentrationLimit:
    """A cap on how much of the posted balance may come from one scope."""

    scope: ConcentrationScope
    limit_percentage: Decimal

    def __post_init__(self) -> None:
        if not (Decimal(0) < self.limit_percentage <= Decimal(1)):
            raise ValueError(
                f"Concentration limit for {self.scope} must be in (0, 1], "
                f"got {self.limit_percentage}."
            )


@dataclass(frozen=True, slots=True)
class RoundingTerms:
    """CSA rounding provision. Delivery and return round in opposite directions."""

    increment: Money
    delivery_direction: RoundingDirection = RoundingDirection.UP
    return_direction: RoundingDirection = RoundingDirection.DOWN


@dataclass(frozen=True, slots=True)
class PartyTerms:
    """Terms that attach to one party in its capacity as Transferor."""

    party: Party
    threshold: Money
    minimum_transfer_amount: Money
    independent_amount: Money
    #: Legal entity name, as it appears on the execution page of the Annex. Carried
    #: because a settlement instruction has to name the parties, not label them "A".
    legal_name: str = ""

    def __post_init__(self) -> None:
        for label, value in (
            ("threshold", self.threshold),
            ("minimum transfer amount", self.minimum_transfer_amount),
            ("independent amount", self.independent_amount),
        ):
            if value.is_negative:
                raise ValueError(f"{self.party} {label} must not be negative, got {value}.")


@dataclass(frozen=True, slots=True)
class CSATerms:
    """The complete set of contractual parameters the engine consumes."""

    agreement_id: str
    netting_set_id: str
    base_currency: Currency
    eligible_currencies: frozenset[Currency]
    party_a: PartyTerms
    party_b: PartyTerms
    rounding: RoundingTerms
    fx_haircut_pct: Decimal
    eligible_collateral: tuple[EligibleCollateralItem, ...]
    concentration_limits: tuple[ConcentrationLimit, ...]
    mta_before_rounding: bool = True
    excluded_issuers: frozenset[str] = field(default_factory=frozenset)
    csa_type: str = "2016_ISDA_VM_CSA"
    governing_law: str = ""
    terms_version: int = 1
    simulated: bool = True

    def __post_init__(self) -> None:
        if self.base_currency not in self.eligible_currencies:
            raise ValueError(f"Base currency {self.base_currency} must be an eligible currency.")
        if not (Decimal(0) <= self.fx_haircut_pct < Decimal(1)):
            raise ValueError(f"FX haircut must be in [0, 1), got {self.fx_haircut_pct}.")
        if not self.eligible_collateral:
            raise ValueError(f"{self.agreement_id}: no eligible collateral schedule.")

        for terms in (self.party_a, self.party_b):
            if terms.threshold.currency is not self.base_currency:
                raise ValueError(
                    f"{terms.party} threshold is in {terms.threshold.currency} but the "
                    f"base currency is {self.base_currency}."
                )

    def terms_for(self, party: Party) -> PartyTerms:
        return self.party_a if party is Party.PARTY_A else self.party_b

    def concentration_limit(self, scope: ConcentrationScope) -> Decimal | None:
        for limit in self.concentration_limits:
            if limit.scope is scope:
                return limit.limit_percentage
        return None
