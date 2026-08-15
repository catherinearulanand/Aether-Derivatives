"""Credit Support Amount — quantitative function F6.

The core CSA calculation, and the one every other part of the system exists to serve.

.. rubric:: The calculation

::

    CreditSupportAmount = max(0, IA + max(0, Exposure) - Threshold)
    DeliveryAmount      = CreditSupportAmount - PostedValue      if > 0
    ReturnAmount        = PostedValue - CreditSupportAmount      if > 0

    gate   |Amount| < MTA  ->  no transfer
    round  ROUND_UP for delivery, ROUND_DOWN for return

.. rubric:: Which party's terms apply

Every CSA parameter is party-specific, and the party whose terms apply is the
**Transferor** — the one who must post. That is determined by the sign of exposure:

- Exposure positive: the counterparty owes us, so Party B is the Transferor and
  Party B's Threshold, Independent Amount and Minimum Transfer Amount govern.
- Exposure negative: we owe, so Party A is the Transferor and Party A's terms govern.

Getting this backwards produces a number that looks entirely reasonable and is
wrong, which is why the resolution is explicit and tested in both directions.

.. rubric:: MTA before or after rounding

Whether the Minimum Transfer Amount is tested on the rounded or unrounded amount is
genuinely ambiguous across CSA vintages and is a real source of collateral disputes.
The Meridian agreement resolves it at Paragraph 3(b) — the test applies to the
unrounded amount — but the engine supports both conventions via
:attr:`~aether.core.csa_terms.CSATerms.mta_before_rounding` and **records which one
was applied** in the trace.

Part of the deterministic core: no I/O, no clock, no framework dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from enum import StrEnum

from aether.core.csa_terms import CSATerms, Party
from aether.core.exposure import ExposureResult
from aether.core.money import Currency, Money, round_to_increment

__all__ = [
    "CallDirection",
    "MarginCallResult",
    "TraceStep",
    "compute_margin_call",
]

#: Bumped whenever the calculation changes. Recorded in every result.
ENGINE_VERSION = "0.1.0"


class CallDirection(StrEnum):
    """Which way collateral moves, if at all."""

    DELIVERY = "DELIVERY"
    RETURN = "RETURN"
    NONE = "NONE"


@dataclass(frozen=True, slots=True)
class TraceStep:
    """One line of the margin waterfall.

    The trace is not logging — it is the evidence that backs the final number, and it
    is what the waterfall screen renders. Each step names the clause it comes from.
    """

    label: str
    value: Money
    clause: str
    explanation: str
    is_gate: bool = False


@dataclass(frozen=True, slots=True)
class MarginCallResult:
    """A complete, reproducible margin call."""

    agreement_id: str
    netting_set_id: str
    snapshot_id: str
    as_of: date
    base_currency: Currency

    exposure: Money
    transferor: Party
    threshold: Money
    independent_amount: Money
    minimum_transfer_amount: Money
    initial_margin: Money

    credit_support_amount: Money
    posted_value: Money
    unrounded_amount: Money
    rounded_amount: Money
    call_amount: Money
    direction: CallDirection

    gated_by_mta: bool
    mta_before_rounding: bool
    trace: tuple[TraceStep, ...]
    engine_version: str = ENGINE_VERSION

    @property
    def has_call(self) -> bool:
        return self.direction is not CallDirection.NONE and not self.call_amount.is_zero

    @property
    def summary(self) -> str:
        if not self.has_call:
            reason = "below Minimum Transfer Amount" if self.gated_by_mta else "no amount due"
            return f"No transfer required ({reason})."
        verb = "must post" if self.direction is CallDirection.DELIVERY else "receives back"
        return f"{self.transferor.value} {verb} {self.call_amount}."


def compute_margin_call(
    terms: CSATerms,
    exposure_result: ExposureResult,
    posted_value: Money | None = None,
    initial_margin: Money | None = None,
) -> MarginCallResult:
    """Compute the Credit Support Amount and resulting transfer.

    ``exposure_result`` must already be expressed in the agreement's base currency
    and must belong to the agreement's netting set — both are checked, because
    valuing against the wrong Master Agreement is a correctness failure.

    ``initial_margin`` is added to the Credit Support Amount when supplied. It is
    computed separately in :mod:`aether.core.im`.
    """
    base = terms.base_currency

    if exposure_result.base_currency is not base:
        raise ValueError(
            f"Exposure is in {exposure_result.base_currency} but agreement "
            f"{terms.agreement_id} has base currency {base}."
        )
    if exposure_result.netting_set_id != terms.netting_set_id:
        raise ValueError(
            f"Exposure belongs to netting set {exposure_result.netting_set_id} but "
            f"agreement {terms.agreement_id} covers {terms.netting_set_id}. "
            "Trades under different Master Agreements must never net."
        )

    posted = posted_value if posted_value is not None else Money.zero(base)
    im = initial_margin if initial_margin is not None else Money.zero(base)
    for label, value in (("Posted value", posted), ("Initial margin", im)):
        if value.currency is not base:
            raise ValueError(f"{label} must be in {base}, got {value.currency}.")

    exposure = exposure_result.exposure

    # --- who posts -----------------------------------------------------
    # Positive exposure: the counterparty owes us, so they are the Transferor.
    transferor = Party.PARTY_B if exposure.is_positive else Party.PARTY_A
    party_terms = terms.terms_for(transferor)

    # The Transferee's exposure to the Transferor, floored at zero.
    secured_exposure = abs(exposure) if not exposure.is_zero else Money.zero(base)

    trace: list[TraceStep] = [
        TraceStep(
            label="Net exposure",
            value=exposure,
            clause="Paragraph 2(c)",
            explanation=(
                f"Netted mark-to-market across {exposure_result.trade_count} trades in "
                f"netting set {exposure_result.netting_set_id}."
            ),
        ),
        TraceStep(
            label="Transferor",
            value=secured_exposure,
            clause="Paragraph 2(a)",
            explanation=(
                f"{transferor.value} must post: exposure is "
                f"{'positive' if exposure.is_positive else 'negative'}, so "
                f"{transferor.value}'s terms govern this call."
            ),
        ),
    ]

    # --- credit support amount -----------------------------------------
    gross = secured_exposure + party_terms.independent_amount + im
    credit_support_amount = (gross - party_terms.threshold).max_with_zero()

    trace.append(
        TraceStep(
            label="Independent Amount",
            value=party_terms.independent_amount,
            clause="Paragraph 11(b)(ii)",
            explanation=f"Independent Amount for {transferor.value}.",
        )
    )
    if not im.is_zero:
        trace.append(
            TraceStep(
                label="Initial Margin",
                value=im,
                clause="Schedule IM",
                explanation="Standardised schedule initial margin. Not certified SIMM.",
            )
        )
    trace.append(
        TraceStep(
            label="Threshold",
            value=-party_terms.threshold,
            clause="Paragraph 11(b)(iii)(A)",
            explanation=(
                f"Unsecured exposure {transferor.value} is permitted before any "
                f"collateral is called."
            ),
        )
    )
    trace.append(
        TraceStep(
            label="Credit Support Amount",
            value=credit_support_amount,
            clause="Paragraph 2(c)",
            explanation="max(0, Independent Amount + Exposure - Threshold).",
        )
    )

    # --- delivery or return --------------------------------------------
    trace.append(
        TraceStep(
            label="Value of Credit Support Balance",
            value=posted,
            clause="Paragraph 2(a)/(b)",
            explanation="Post-haircut value of collateral already held.",
        )
    )

    difference = credit_support_amount - posted
    if difference.is_positive:
        direction = CallDirection.DELIVERY
        unrounded = difference
        rounding_direction = terms.rounding.delivery_direction
    elif difference.is_negative:
        direction = CallDirection.RETURN
        unrounded = -difference
        rounding_direction = terms.rounding.return_direction
    else:
        direction = CallDirection.NONE
        unrounded = Money.zero(base)
        rounding_direction = terms.rounding.delivery_direction

    trace.append(
        TraceStep(
            label=f"{direction.value.title()} Amount (unrounded)"
            if direction is not CallDirection.NONE
            else "Amount due (unrounded)",
            value=unrounded,
            clause="Paragraph 2(a)/(b)",
            explanation=(
                "Credit Support Amount less collateral already held."
                if direction is CallDirection.DELIVERY
                else "Collateral held in excess of the Credit Support Amount."
            ),
        )
    )

    # --- MTA gate and rounding, in the elected order ---------------------
    mta = party_terms.minimum_transfer_amount

    def apply_rounding(amount: Money) -> Money:
        return round_to_increment(amount, terms.rounding.increment, rounding_direction)

    if terms.mta_before_rounding:
        gated = unrounded < mta
        after_gate = Money.zero(base) if gated else unrounded
        rounded = apply_rounding(after_gate)
        final = rounded
        order_note = (
            "MTA tested on the unrounded amount, then rounding applied "
            "(Paragraph 3(b) of this Annex)."
        )
    else:
        rounded = apply_rounding(unrounded)
        gated = rounded < mta
        final = Money.zero(base) if gated else rounded
        order_note = "Rounding applied first, then the MTA test."

    gate_outcome = (
        "Gated: amount is below the MTA, so no transfer is made."
        if gated
        else "Passed: amount meets the MTA."
    )
    trace.append(
        TraceStep(
            label="Minimum Transfer Amount",
            value=mta,
            clause="Paragraph 11(b)(iii)(B)",
            explanation=f"{gate_outcome} {order_note}",
            is_gate=True,
        )
    )
    trace.append(
        TraceStep(
            label="Rounding",
            value=terms.rounding.increment,
            clause="Paragraph 11(b)(iii)(D)",
            explanation=(
                f"{direction.value.title()} amounts round "
                f"{rounding_direction.value.lower()} to the nearest multiple of "
                f"{terms.rounding.increment}."
            ),
        )
    )

    if gated or final.is_zero:
        direction = CallDirection.NONE

    trace.append(
        TraceStep(
            label="Transfer required",
            value=final,
            clause="Paragraph 2",
            explanation=(
                f"Final amount {transferor.value} must transfer."
                if direction is CallDirection.DELIVERY
                else "No transfer required."
                if direction is CallDirection.NONE
                else f"Amount returned to {transferor.value}."
            ),
        )
    )

    return MarginCallResult(
        agreement_id=terms.agreement_id,
        netting_set_id=terms.netting_set_id,
        snapshot_id=exposure_result.snapshot_id,
        as_of=exposure_result.as_of,
        base_currency=base,
        exposure=exposure,
        transferor=transferor,
        threshold=party_terms.threshold,
        independent_amount=party_terms.independent_amount,
        minimum_transfer_amount=mta,
        initial_margin=im,
        credit_support_amount=credit_support_amount,
        posted_value=posted,
        unrounded_amount=unrounded,
        rounded_amount=rounded,
        call_amount=final,
        direction=direction,
        gated_by_mta=gated,
        mta_before_rounding=terms.mta_before_rounding,
        trace=tuple(trace),
    )


def zero_threshold(terms: CSATerms, party: Party) -> CSATerms:
    """Return ``terms`` with ``party``'s Threshold set to zero.

    Models a ratings-contingent Threshold override — the Meridian CSA's Paragraph
    11(g)(ii) drops Party B's Threshold to zero while a Ratings Event is continuing.
    Applying it is a reviewer decision, never an inference the engine makes on its own.
    """
    party_terms = terms.terms_for(party)
    zeroed = replace(party_terms, threshold=Money.zero(terms.base_currency))
    if party is Party.PARTY_A:
        return replace(terms, party_a=zeroed)
    return replace(terms, party_b=zeroed)


def credit_support_amount_only(
    exposure: Money, independent_amount: Money, threshold: Money
) -> Money:
    """The bare formula, exposed for property tests and cross-checking."""
    return (exposure.max_with_zero() + independent_amount - threshold).max_with_zero()
