"""What must hold before a workflow may proceed.

.. rubric:: Never silently continue a compromised financial workflow

The failure this module exists to prevent is not a crash. It is a run that
completes, renders a number, and gets approved, while something underneath it was
wrong — a broken audit chain, an unreviewed term, a model that is not the one the
registry says should be serving.

Those conditions do not raise on their own. Exposure still computes when the audit
chain is broken; the optimiser still solves when the extraction was never
reviewed. So they are checked explicitly, before the result is offered for
authorisation, and a failure stops the workflow rather than annotating it.

.. rubric:: Degrade, don't disappear

A failed check does not hide the run. Concealing the evidence at the moment
something goes wrong is the opposite of what an operator needs: they need to see
the figures *and* the reason those figures cannot be acted on. So a preflight
failure marks the workflow ``HELD`` — visible, inspectable, exportable, and
unapprovable — rather than returning an error page.

That is also why nothing here deletes or rolls back. Preserving the evidence is
part of the incident response, not incidental to it.

.. rubric:: Severity

``BLOCKING``  the workflow may not be authorised. Escalates to ``CRITICAL``.
``DEGRADED``  proceed, but a reviewer must see this. Escalates to ``MEDIUM``.

There is no "warning that does nothing" level. A check whose failure changes
nothing is not a control, and having one trains people to ignore the rest.

Pure: no I/O, no network, no clock.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

__all__ = [
    "CheckResult",
    "Preflight",
    "Severity",
    "preflight",
]


class Severity(StrEnum):
    BLOCKING = "BLOCKING"
    DEGRADED = "DEGRADED"


@dataclass(frozen=True, slots=True)
class CheckResult:
    """One failed condition. Passing checks are counted, not enumerated."""

    code: str
    severity: Severity
    detail: str
    #: What a person should do about it. A finding without a remedy is a dead end.
    remedy: str


@dataclass(frozen=True, slots=True)
class Preflight:
    """The verdict on whether a workflow may proceed to authorisation."""

    checks_run: int
    failures: tuple[CheckResult, ...]

    @property
    def blocking(self) -> tuple[CheckResult, ...]:
        return tuple(f for f in self.failures if f.severity is Severity.BLOCKING)

    @property
    def is_safe(self) -> bool:
        """Whether the workflow may be authorised."""
        return not self.blocking

    @property
    def is_clean(self) -> bool:
        return not self.failures

    def as_escalation_signals(self) -> tuple[str, ...]:
        """Blocking failures, phrased for :func:`escalation.classify`."""
        return tuple(f"{f.code}: {f.detail}" for f in self.blocking)

    def as_payload(self) -> dict[str, object]:
        return {
            "checks_run": self.checks_run,
            "is_safe": self.is_safe,
            "is_clean": self.is_clean,
            "failures": [
                {
                    "code": f.code,
                    "severity": f.severity.value,
                    "detail": f.detail,
                    "remedy": f.remedy,
                }
                for f in self.failures
            ],
        }


def preflight(
    *,
    audit_verified: bool,
    audit_break_at: int | None = None,
    unresolved_terms: tuple[str, ...] = (),
    snapshot_id: str | None = None,
    snapshot_as_of: str | None = None,
    valuation_as_of: str | None = None,
    model_available: bool = True,
    model_reason: str = "",
    expected_registry_key: str | None = None,
    actual_registry_key: str | None = None,
    injection_severity: str | None = None,
) -> Preflight:
    """Run every integrity condition and report what failed.

    Each argument is a fact the caller already holds. This function performs no
    I/O and no calculation; it decides whether the facts are consistent with
    proceeding.
    """
    failures: list[CheckResult] = []
    checks = 0

    # ---- the audit chain
    checks += 1
    if not audit_verified:
        where = f" at event {audit_break_at}" if audit_break_at is not None else ""
        failures.append(
            CheckResult(
                code="AUDIT_CHAIN_BROKEN",
                severity=Severity.BLOCKING,
                detail=(
                    f"The audit chain does not verify{where}. Every hash after that "
                    "point is unreliable, so the lineage behind this decision cannot "
                    "be trusted."
                ),
                remedy=(
                    "Do not approve. Preserve the chain as it stands and escalate — "
                    "a broken chain is an incident, and re-running to obtain a clean "
                    "one destroys the evidence of what happened."
                ),
            )
        )

    # ---- human review
    checks += 1
    if unresolved_terms:
        listed = ", ".join(unresolved_terms[:5])
        more = f" (+{len(unresolved_terms) - 5} more)" if len(unresolved_terms) > 5 else ""
        failures.append(
            CheckResult(
                code="UNRESOLVED_CONTRACTUAL_TERMS",
                severity=Severity.BLOCKING,
                detail=(
                    f"{len(unresolved_terms)} contractual term(s) await a human "
                    f"decision: {listed}{more}. The calculation would rest on an "
                    "unreviewed interpretation."
                ),
                remedy=(
                    "Resolve each flagged term on the Contracts screen, then freeze the agreement."
                ),
            )
        )

    # ---- market data
    checks += 1
    if not snapshot_id:
        failures.append(
            CheckResult(
                code="NO_MARKET_SNAPSHOT",
                severity=Severity.BLOCKING,
                detail="The result does not name the market snapshot it was computed against.",
                remedy="Re-run against a pinned snapshot. An unpinned figure is not reproducible.",
            )
        )

    checks += 1
    if snapshot_as_of and valuation_as_of and snapshot_as_of != valuation_as_of:
        failures.append(
            CheckResult(
                code="STALE_MARKET_SNAPSHOT",
                severity=Severity.BLOCKING,
                detail=(
                    f"The snapshot is as of {snapshot_as_of} but the valuation date is "
                    f"{valuation_as_of}. A calculation dated one day and priced another "
                    "is wrong in a way that does not announce itself."
                ),
                remedy="Re-run against the snapshot pinned to the valuation date.",
            )
        )

    # ---- model governance
    checks += 1
    if not model_available:
        failures.append(
            CheckResult(
                code="MODEL_UNAVAILABLE",
                severity=Severity.DEGRADED,
                detail=(f"No model is cleared to serve this use case. {model_reason}".strip()),
                remedy=(
                    "Extraction falls back to the cached replay, which is a recorded "
                    "prior result rather than a fresh reading. Confirm that is "
                    "acceptable before freezing terms from it."
                ),
            )
        )

    checks += 1
    if (
        expected_registry_key
        and actual_registry_key
        and expected_registry_key != actual_registry_key
    ):
        failures.append(
            CheckResult(
                code="MODEL_VERSION_MISMATCH",
                severity=Severity.BLOCKING,
                detail=(
                    f"This result was produced by {actual_registry_key}, but "
                    f"{expected_registry_key} is the deployed model. The decision and "
                    "the registry disagree about what produced it."
                ),
                remedy=(
                    "Re-run under the deployed model, or retrieve the historical card "
                    "if this is an intentional replay of an older decision."
                ),
            )
        )

    # ---- document integrity
    checks += 1
    if injection_severity in {"SUSPICIOUS", "HOSTILE"}:
        failures.append(
            CheckResult(
                code="DOCUMENT_INJECTION_DETECTED",
                severity=(
                    Severity.BLOCKING if injection_severity == "HOSTILE" else Severity.DEGRADED
                ),
                detail=(
                    f"The source document carries {injection_severity.lower()} content "
                    "that attempts to instruct the reader rather than state a term."
                ),
                remedy=(
                    "Review the flagged spans on the Contracts screen before freezing "
                    "any term derived from this document."
                ),
            )
        )

    return Preflight(checks_run=checks, failures=tuple(failures))
