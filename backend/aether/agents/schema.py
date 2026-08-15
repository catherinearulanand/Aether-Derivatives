"""The extraction contract.

This is the typed schema every contractual value must cross through on its way from a
legal document into the deterministic engine. It is the mechanism behind the product's
central rule:

    **Language models extract. Deterministic engines compute.**

An :class:`ExtractedField` carries a value, the span of source text it came from, and
a confidence. It never carries a calculation. Turning extracted fields into
:class:`~aether.core.csa_terms.CSATerms` requires every low-confidence field to have
been confirmed by a reviewer — enforced in :func:`aether.agents.review.freeze_terms`,
not left to discipline.
"""

from __future__ import annotations

import re
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

__all__ = [
    "Citation",
    "ExtractedField",
    "ExtractionResult",
    "FieldSource",
    "ReviewReason",
]


def _normalise_text(text: str) -> str:
    """Collapse whitespace and strip markdown emphasis, for citation matching."""
    return re.sub(r"\s+", " ", text.replace("**", "").replace("*", "")).strip()


class FieldSource(StrEnum):
    """Where a field's current value came from.

    ``AGENT`` values are model output. ``HUMAN`` values were entered or confirmed by
    a reviewer. The audit trail keeps them distinguishable forever.
    """

    AGENT = "AGENT"
    HUMAN = "HUMAN"


class ReviewReason(StrEnum):
    """Why a field was routed to a human."""

    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    CONDITIONAL_CLAUSE = "CONDITIONAL_CLAUSE"
    AMBIGUOUS = "AMBIGUOUS"
    NOT_FOUND = "NOT_FOUND"
    CONFLICTING_CLAUSES = "CONFLICTING_CLAUSES"


class Citation(BaseModel):
    """Where in the document a value came from.

    A field without a citation is an assertion, not an extraction. The agent is
    instructed never to emit one, and :class:`ExtractionResult` reports any that
    slip through.
    """

    model_config = ConfigDict(frozen=True)

    page: int = Field(ge=1, description="1-indexed page of the source document")
    section: str = Field(description="Clause reference, e.g. '11(b)(iii)(A)'")
    quote: str = Field(min_length=1, description="Verbatim text supporting the value")

    def overlaps(self, other: Citation, threshold: float = 0.6) -> bool:
        """Word-level overlap against another citation, for eval scoring."""
        if self.page != other.page:
            return False
        mine = set(self.quote.lower().split())
        theirs = set(other.quote.lower().split())
        if not theirs:
            return False
        return len(mine & theirs) / len(theirs) >= threshold

    def appears_in(self, document_text: str) -> bool:
        """Does this quote actually occur in the source document?

        Whitespace is normalised on both sides and markdown emphasis markers are
        stripped, because a document line-wraps wherever it happens to and a quote
        spanning a line break is still the same quote. Without this, a correct
        citation would fail purely on where the source text was wrapped.
        """
        return _normalise_text(self.quote) in _normalise_text(document_text)


class ConditionalValue(BaseModel):
    """A value that depends on a state the document cannot resolve on its own.

    The Meridian CSA's Threshold is the worked example: Paragraph 11(b)(iii)(A)
    states USD 5,000,000 "subject to Paragraph 11(g)(ii)", which drops it to zero
    while a ratings downgrade is continuing. The document says what happens; it
    cannot say whether it *is* happening. That is a reviewer's call.
    """

    model_config = ConfigDict(frozen=True)

    trigger: str
    condition: str
    value_if_triggered: dict[str, str] | None = None
    trigger_citation: Citation | None = None


class ExtractedField(BaseModel):
    """One contractual value, with its evidence."""

    model_config = ConfigDict(frozen=True)

    path: str = Field(description="Dotted path, e.g. 'threshold.party_b'")
    value: object = Field(description="Extracted value. Money is {amount, currency}.")
    confidence: float = Field(ge=0.0, le=1.0)
    citation: Citation | None = None
    source: FieldSource = FieldSource.AGENT

    requires_review: bool = False
    review_reason: ReviewReason | None = None
    review_note: str = ""
    conditional: ConditionalValue | None = None

    reviewer: str | None = None
    reviewer_rationale: str = ""

    @property
    def is_resolved(self) -> bool:
        """A field is resolved when it needs no review, or a human has confirmed it."""
        return not self.requires_review or self.source is FieldSource.HUMAN

    def confirm(self, reviewer: str, rationale: str, value: object = None) -> ExtractedField:
        """Return a confirmed copy, recording who decided and why.

        Confirming does not clear ``requires_review`` — the flag is history. What
        changes is ``source``, which is what :attr:`is_resolved` tests.
        """
        return self.model_copy(
            update={
                "value": self.value if value is None else value,
                "source": FieldSource.HUMAN,
                "reviewer": reviewer,
                "reviewer_rationale": rationale,
                "confidence": 1.0,
            }
        )


class ExtractionResult(BaseModel):
    """Everything one extraction run produced."""

    model_config = ConfigDict(frozen=True)

    document_id: str
    document_sha256: str
    fields: tuple[ExtractedField, ...]

    model_id: str
    prompt_version: str
    mode: str
    temperature: float = 0.0
    cache_hit: bool = False
    latency_ms: int = 0
    simulated: bool = True

    @property
    def field_map(self) -> dict[str, ExtractedField]:
        return {field.path: field for field in self.fields}

    @property
    def pending_review(self) -> tuple[ExtractedField, ...]:
        return tuple(f for f in self.fields if not f.is_resolved)

    @property
    def uncited(self) -> tuple[ExtractedField, ...]:
        """Fields with no supporting quote. Should always be empty."""
        return tuple(f for f in self.fields if f.citation is None)

    @property
    def is_ready_to_freeze(self) -> bool:
        return not self.pending_review

    @property
    def mean_confidence(self) -> Decimal:
        if not self.fields:
            return Decimal(0)
        total = sum(Decimal(str(f.confidence)) for f in self.fields)
        return (total / Decimal(len(self.fields))).quantize(Decimal("0.001"))

    def with_field(self, updated: ExtractedField) -> ExtractionResult:
        """Return a copy with one field replaced. Extraction results are immutable."""
        replaced = tuple(updated if f.path == updated.path else f for f in self.fields)
        if replaced == self.fields:
            raise KeyError(f"No field '{updated.path}' in this extraction.")
        return self.model_copy(update={"fields": replaced})
