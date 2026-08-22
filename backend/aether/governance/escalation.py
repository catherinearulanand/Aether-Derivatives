"""How much scrutiny a decision attracts.

.. rubric:: The thresholds here are demo values

Every number in :data:`DEFAULT_POLICY` is a **placeholder chosen to demonstrate
the mechanism**, not a risk appetite. A real institution sets these from its own
limits, and the shape of this module is the point: the policy is data, passed in,
and the classifier holds none of it.

Nothing in AETHER should read a threshold from anywhere but a policy object. A
figure compiled into a branch is a figure nobody can change without a deployment,
and a control nobody can change is a control nobody owns.

.. rubric:: Bands

``LOW``       routine. Standard approval.
``MEDIUM``    unusual enough to read carefully. Enhanced review.
``HIGH``      material. A second approver.
``CRITICAL``  the decision is not safe to act on. Automatic hold — no approval
              path at all until the underlying condition is cleared.

``CRITICAL`` is deliberately not "very high". It is a different kind of state: the
other three say *how much review*, and ``CRITICAL`` says *stop*. A run whose audit
chain does not verify is not a large decision, it is an untrustworthy one, and
routing it to a more senior approver would be asking a person to sign for a number
the system cannot vouch for.

.. rubric:: Signals, not scores

Classification returns the reasons alongside the band. A band without its reasons
is a number a reviewer has to take on trust, which defeats the purpose of showing
it to them.

Pure: no I/O, no network, no clock. Money arrives as ``Decimal``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum

__all__ = [
    "DEFAULT_POLICY",
    "Assessment",
    "Band",
    "EscalationPolicy",
    "Signal",
    "classify",
]


class Band(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


_ORDER: dict[Band, int] = {Band.LOW: 0, Band.MEDIUM: 1, Band.HIGH: 2, Band.CRITICAL: 3}


@dataclass(frozen=True, slots=True)
class Signal:
    """One reason a decision was placed in a band."""

    code: str
    band: Band
    detail: str


@dataclass(frozen=True, slots=True)
class EscalationPolicy:
    """An institution's risk appetite, as data.

    .. rubric:: Provenance of the defaults

    ``medium_transfer`` and ``high_transfer`` are round numbers positioned around
    the demo fixtures so that the quiet-market scenario lands LOW and the
    rate-shock scenario lands HIGH. They are illustrative. ``concentration_*`` are
    likewise chosen to sit just inside and just outside the CSA's own
    concentration caps in the fixture Annex.
    """

    #: Transfer at or above this is unusual. Base currency units.
    medium_transfer: Decimal = Decimal("1000000")
    #: Transfer at or above this is material and attracts a second approver.
    high_transfer: Decimal = Decimal("5000000")

    #: Share of a single asset class in the posted collateral that counts as
    #: concentrated, expressed as a proportion.
    medium_concentration: Decimal = Decimal("0.40")
    high_concentration: Decimal = Decimal("0.60")

    #: Proportion of the requirement met by assets carrying an FX haircut.
    #: Cross-border collateral is not riskier per se, but it is the case a
    #: reviewer is most likely to want to see.
    medium_cross_border: Decimal = Decimal("0.25")

    #: A decision that moves this much against its baseline is a material
    #: deviation regardless of absolute size.
    high_deviation: Decimal = Decimal("0.50")

    #: Roles permitted to clear a CRITICAL hold. Empty means nobody, which is
    #: correct for integrity failures: they are cleared by fixing the condition,
    #: not by overriding it.
    critical_override_roles: frozenset[str] = field(default_factory=frozenset)

    #: Recorded on every assessment so an evidence pack says which appetite was
    #: in force when the decision was classified.
    policy_version: str = "escalation/demo-v1"
    is_demo: bool = True


#: The shipped defaults. Demo values — see the class docstring.
DEFAULT_POLICY = EscalationPolicy()


@dataclass(frozen=True, slots=True)
class Assessment:
    """A band, and why."""

    band: Band
    signals: tuple[Signal, ...]
    policy_version: str
    policy_is_demo: bool

    @property
    def requires_second_approver(self) -> bool:
        return self.band is Band.HIGH

    @property
    def is_held(self) -> bool:
        """``CRITICAL`` blocks approval entirely rather than escalating it."""
        return self.band is Band.CRITICAL

    @property
    def headline(self) -> str:
        if not self.signals:
            return "Routine decision. No escalation signal raised."
        return self.signals[0].detail

    def as_payload(self) -> dict[str, object]:
        return {
            "band": self.band.value,
            "requires_second_approver": self.requires_second_approver,
            "is_held": self.is_held,
            "policy_version": self.policy_version,
            "policy_is_demo": self.policy_is_demo,
            "signals": [
                {"code": s.code, "band": s.band.value, "detail": s.detail} for s in self.signals
            ],
        }


def classify(
    *,
    transfer_amount: Decimal,
    currency: str,
    integrity_failures: tuple[str, ...] = (),
    largest_class_share: Decimal | None = None,
    cross_border_share: Decimal | None = None,
    deviation_from_baseline: Decimal | None = None,
    unresolved_terms: int = 0,
    injection_detected: bool = False,
    policy: EscalationPolicy = DEFAULT_POLICY,
) -> Assessment:
    """Place a decision in a band and say why.

    Every argument is a fact the caller already computed. This function performs
    no financial calculation — it compares figures the engine produced against
    thresholds the policy declares.
    """
    signals: list[Signal] = []

    # ---- CRITICAL: the decision is not safe to act on.
    for failure in integrity_failures:
        signals.append(
            Signal(
                code="INTEGRITY_FAILURE",
                band=Band.CRITICAL,
                detail=(
                    f"{failure} A decision cannot be approved while an integrity "
                    "condition is failing — the hold clears by fixing the condition, "
                    "not by overriding it."
                ),
            )
        )

    if unresolved_terms > 0:
        signals.append(
            Signal(
                code="UNRESOLVED_TERMS",
                band=Band.CRITICAL,
                detail=(
                    f"{unresolved_terms} contractual term(s) still await a human "
                    "decision. The calculation must not proceed on an unreviewed "
                    "interpretation."
                ),
            )
        )

    if injection_detected:
        signals.append(
            Signal(
                code="DOCUMENT_INJECTION",
                band=Band.CRITICAL,
                detail=(
                    "The source document contains text that attempts to instruct the "
                    "reader. The extraction must be reviewed by a person before any "
                    "term derived from it is frozen."
                ),
            )
        )

    # ---- HIGH / MEDIUM: size, shape and deviation.
    if transfer_amount >= policy.high_transfer:
        signals.append(
            Signal(
                code="TRANSFER_SIZE",
                band=Band.HIGH,
                detail=(
                    f"Transfer of {currency} {transfer_amount} is at or above the "
                    f"material threshold of {currency} {policy.high_transfer}."
                ),
            )
        )
    elif transfer_amount >= policy.medium_transfer:
        signals.append(
            Signal(
                code="TRANSFER_SIZE",
                band=Band.MEDIUM,
                detail=(
                    f"Transfer of {currency} {transfer_amount} is at or above the "
                    f"enhanced-review threshold of {currency} {policy.medium_transfer}."
                ),
            )
        )

    if largest_class_share is not None:
        if largest_class_share >= policy.high_concentration:
            signals.append(
                Signal(
                    code="CONCENTRATION",
                    band=Band.HIGH,
                    detail=(
                        f"A single asset class carries {largest_class_share:.0%} of the "
                        f"posted collateral, at or above the {policy.high_concentration:.0%} "
                        "material threshold."
                    ),
                )
            )
        elif largest_class_share >= policy.medium_concentration:
            signals.append(
                Signal(
                    code="CONCENTRATION",
                    band=Band.MEDIUM,
                    detail=(
                        f"A single asset class carries {largest_class_share:.0%} of the "
                        "posted collateral."
                    ),
                )
            )

    if cross_border_share is not None and cross_border_share >= policy.medium_cross_border:
        signals.append(
            Signal(
                code="CROSS_BORDER",
                band=Band.MEDIUM,
                detail=(
                    f"{cross_border_share:.0%} of the requirement is met by collateral "
                    "carrying an FX haircut."
                ),
            )
        )

    if (
        deviation_from_baseline is not None
        and abs(deviation_from_baseline) >= policy.high_deviation
    ):
        signals.append(
            Signal(
                code="DEVIATION",
                band=Band.HIGH,
                detail=(
                    f"The decision moves {abs(deviation_from_baseline):.0%} against its "
                    "baseline, a material deviation independent of absolute size."
                ),
            )
        )

    band = max((s.band for s in signals), key=lambda b: _ORDER[b], default=Band.LOW)
    signals.sort(key=lambda s: _ORDER[s.band], reverse=True)

    return Assessment(
        band=band,
        signals=tuple(signals),
        policy_version=policy.policy_version,
        policy_is_demo=policy.is_demo,
    )
