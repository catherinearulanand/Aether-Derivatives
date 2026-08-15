"""The review gate — where model output becomes engine input.

This module is the enforcement point for the product's central rule. Extracted fields
are candidate values; :func:`freeze_terms` is the only way they become
:class:`~aether.core.csa_terms.CSATerms`, and it **refuses** while any field still
needs a human decision.

That refusal is the whole design. Without it, "a reviewer confirms low-confidence
fields" is a process everyone agrees to and someone eventually skips. With it, an
unreviewed extraction cannot physically reach the margin engine.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from aether.agents.schema import ExtractedField, ExtractionResult
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
from aether.core.money import Currency, Money, RoundingDirection

__all__ = ["ReviewRequired", "confirm_field", "freeze_terms", "pending_summary"]


class ReviewRequired(RuntimeError):
    """Raised when an extraction is frozen while fields still await a human."""

    def __init__(self, pending: tuple[ExtractedField, ...]) -> None:
        self.pending = pending
        paths = ", ".join(f.path for f in pending)
        super().__init__(
            f"{len(pending)} field(s) require reviewer confirmation before this "
            f"agreement can be frozen: {paths}. Model output does not reach the "
            f"margin engine unreviewed."
        )


@dataclass(frozen=True, slots=True)
class PendingItem:
    """One outstanding decision, phrased for the person who has to make it."""

    path: str
    current_value: str
    reason: str
    question: str
    alternative: str | None
    citation: str


def pending_summary(extraction: ExtractionResult) -> tuple[PendingItem, ...]:
    """Everything a reviewer must resolve, with the evidence for each."""
    items: list[PendingItem] = []

    for field in extraction.pending_review:
        alternative = None
        if field.conditional and field.conditional.value_if_triggered:
            alternative = _describe(field.conditional.value_if_triggered)

        citation = (
            f'p.{field.citation.page} para {field.citation.section}: "{field.citation.quote}"'
            if field.citation
            else "no citation supplied"
        )

        items.append(
            PendingItem(
                path=field.path,
                current_value=_describe(field.value),
                reason=field.review_reason.value if field.review_reason else "UNKNOWN",
                question=field.review_note or "Confirm this value.",
                alternative=alternative,
                citation=citation,
            )
        )

    return tuple(items)


def _describe(value: Any) -> str:
    if isinstance(value, dict) and "amount" in value and "currency" in value:
        return f"{value['currency']} {Decimal(str(value['amount'])):,.2f}"
    return str(value)


def confirm_field(
    extraction: ExtractionResult,
    path: str,
    reviewer: str,
    rationale: str,
    value: object = None,
) -> ExtractionResult:
    """Record a reviewer's decision on one field.

    ``value`` overrides the extracted value when the reviewer disagrees with it;
    omitted, the extracted value stands. Either way the decision, the reviewer and
    the rationale are recorded permanently.
    """
    field = extraction.field_map.get(path)
    if field is None:
        raise KeyError(f"No field '{path}' in extraction {extraction.document_id}.")
    if not rationale.strip():
        raise ValueError("A reviewer rationale is required. Decisions must be explainable.")

    return extraction.with_field(field.confirm(reviewer, rationale, value))


# ------------------------------------------------------------- freezing


def _money(raw: Any) -> Money:
    return Money(Decimal(str(raw["amount"])), Currency(raw["currency"]))


def _require(extraction: ExtractionResult, path: str) -> Any:
    field = extraction.field_map.get(path)
    if field is None:
        raise ReviewRequired(())
    return field.value


def _optional_decimal(raw: Any) -> Decimal | None:
    return None if raw is None else Decimal(str(raw))


def _build_eligible_item(raw: dict[str, Any]) -> EligibleCollateralItem:
    currency_raw = raw.get("currency")
    non_base_only = currency_raw == "ANY_ELIGIBLE_NON_BASE"
    currency = None if non_base_only or not currency_raw else Currency(currency_raw)

    return EligibleCollateralItem(
        ref=str(raw["ref"]),
        asset_class=AssetClass(raw["asset_class"]),
        valuation_percentage=Decimal(str(raw["valuation_pct"])),
        issuer_type=IssuerType(raw["issuer_type"]),
        issuer=raw.get("issuer"),
        currency=currency,
        non_base_currency_only=non_base_only,
        min_maturity_years=_optional_decimal(raw.get("min_maturity_years")),
        max_maturity_years=_optional_decimal(raw.get("max_maturity_years")),
        min_rating=raw.get("min_rating"),
        index_membership=tuple(raw.get("index_member", ())),
    )


def freeze_terms(
    extraction: ExtractionResult,
    agreement_id: str,
    netting_set_id: str,
    excluded_issuers: frozenset[str] = frozenset(),
    governing_law: str = "",
) -> CSATerms:
    """Convert a fully-reviewed extraction into frozen, computable terms.

    Raises :class:`ReviewRequired` while any field still awaits a human. This is the
    gate that makes "no LLM-generated number becomes an authoritative financial
    result" structurally true rather than merely stated.
    """
    if extraction.pending_review:
        raise ReviewRequired(extraction.pending_review)

    if extraction.uncited:
        paths = ", ".join(f.path for f in extraction.uncited)
        raise ValueError(
            f"Cannot freeze: {paths} have no citation. Every contractual value must "
            f"be traceable to the source document."
        )

    base = Currency(str(_require(extraction, "base_currency")))

    party_a = PartyTerms(
        party=Party.PARTY_A,
        threshold=_money(_require(extraction, "threshold.party_a")),
        minimum_transfer_amount=_money(_require(extraction, "minimum_transfer_amount.party_a")),
        independent_amount=_money(_require(extraction, "independent_amount.party_a")),
        legal_name=str(_require(extraction, "party_a.legal_name")),
    )
    party_b = PartyTerms(
        party=Party.PARTY_B,
        threshold=_money(_require(extraction, "threshold.party_b")),
        minimum_transfer_amount=_money(_require(extraction, "minimum_transfer_amount.party_b")),
        independent_amount=_money(_require(extraction, "independent_amount.party_b")),
        legal_name=str(_require(extraction, "party_b.legal_name")),
    )

    rounding = RoundingTerms(
        increment=_money(_require(extraction, "rounding.increment")),
        delivery_direction=RoundingDirection(
            str(_require(extraction, "rounding.delivery_direction"))
        ),
        return_direction=RoundingDirection(str(_require(extraction, "rounding.return_direction"))),
    )

    return CSATerms(
        agreement_id=agreement_id,
        netting_set_id=netting_set_id,
        base_currency=base,
        eligible_currencies=frozenset(
            Currency(c) for c in _require(extraction, "eligible_currencies")
        ),
        party_a=party_a,
        party_b=party_b,
        rounding=rounding,
        fx_haircut_pct=Decimal(str(_require(extraction, "fx_haircut_pct"))),
        eligible_collateral=tuple(
            _build_eligible_item(raw) for raw in _require(extraction, "eligible_collateral")
        ),
        concentration_limits=tuple(
            ConcentrationLimit(
                scope=ConcentrationScope(raw["scope"]),
                limit_percentage=Decimal(str(raw["limit_pct"])),
            )
            for raw in _require(extraction, "concentration_limits")
        ),
        mta_before_rounding=bool(_require(extraction, "mta_before_rounding")),
        excluded_issuers=excluded_issuers,
        governing_law=governing_law,
        terms_version=1,
    )
