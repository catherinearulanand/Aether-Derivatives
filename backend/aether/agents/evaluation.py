"""Extraction evaluation harness.

Scores the Legal-Clause Agent against hand-authored ground truth. The output is the
number shown on the methodology screen, and it is **measured**, not estimated.

.. rubric:: Scoring

Per field::

    field_score = 0.5 * value_match + 0.3 * citation_match + 0.2 * review_flag_match

- ``value_match`` — exact after normalisation. Money is compared as ``Decimal``,
  never as float.
- ``citation_match`` — correct page and a quote overlapping the expected span.
- ``review_flag_match`` — did the agent route the field to a human when it should have?

.. rubric:: Why review-flag recall is weighted hardest

Missing a field that needed review means confidently computing on a value that may be
wrong — a wrong number presented as certain. That is the worst failure this system can
produce, worse than an obvious error, because nothing downstream will question it. So
a missed review flag is penalised at triple weight and the target for that metric is
100%, not "high".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from aether.agents.schema import Citation, ExtractionResult
from aether.config import Settings, get_settings

__all__ = ["EvaluationReport", "FieldScore", "evaluate_extraction", "load_ground_truth"]

VALUE_WEIGHT = Decimal("0.5")
CITATION_WEIGHT = Decimal("0.3")
REVIEW_WEIGHT = Decimal("0.2")

#: A missed review flag is three times as bad as any other error.
MISSED_REVIEW_PENALTY = 3

TARGETS = {
    "value_accuracy": Decimal("0.90"),
    "citation_accuracy": Decimal("0.80"),
    "review_flag_recall": Decimal("1.00"),
}


@dataclass(frozen=True, slots=True)
class FieldScore:
    """How one field scored, and why."""

    path: str
    value_match: bool
    citation_match: bool
    review_flag_match: bool
    expected_review: bool
    actual_review: bool
    score: Decimal
    note: str = ""

    @property
    def missed_review_flag(self) -> bool:
        """The failure mode that matters most: should have been flagged, was not."""
        return self.expected_review and not self.actual_review


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    """The measured accuracy of one extraction run."""

    document_id: str
    model_id: str
    prompt_version: str
    mode: str
    scores: tuple[FieldScore, ...]
    missing_fields: tuple[str, ...]
    extra_fields: tuple[str, ...]

    @property
    def scored_count(self) -> int:
        return len(self.scores)

    @property
    def value_accuracy(self) -> Decimal:
        return self._rate(s.value_match for s in self.scores)

    @property
    def citation_accuracy(self) -> Decimal:
        return self._rate(s.citation_match for s in self.scores)

    @property
    def review_flag_recall(self) -> Decimal:
        expected = [s for s in self.scores if s.expected_review]
        if not expected:
            return Decimal("1.000")
        return self._rate(s.actual_review for s in expected)

    @property
    def missed_review_flags(self) -> tuple[FieldScore, ...]:
        return tuple(s for s in self.scores if s.missed_review_flag)

    @property
    def overall_score(self) -> Decimal:
        """Weighted mean, with missed review flags penalised at triple weight."""
        if not self.scores:
            return Decimal(0)
        total = Decimal(0)
        weight = Decimal(0)
        for score in self.scores:
            w = Decimal(MISSED_REVIEW_PENALTY) if score.missed_review_flag else Decimal(1)
            total += score.score * w
            weight += w
        return (total / weight).quantize(Decimal("0.001"))

    @property
    def passes(self) -> bool:
        return (
            self.value_accuracy >= TARGETS["value_accuracy"]
            and self.citation_accuracy >= TARGETS["citation_accuracy"]
            and self.review_flag_recall >= TARGETS["review_flag_recall"]
            and not self.missing_fields
        )

    def _rate(self, flags: Any) -> Decimal:
        values = list(flags)
        if not values:
            return Decimal(0)
        return (Decimal(sum(values)) / Decimal(len(values))).quantize(Decimal("0.001"))

    def summary(self) -> str:
        verdict = "PASS" if self.passes else "FAIL"
        return (
            f"{verdict}  value {self.value_accuracy:.1%}  "
            f"citation {self.citation_accuracy:.1%}  "
            f"review-flag recall {self.review_flag_recall:.1%}  "
            f"overall {self.overall_score}"
        )


def load_ground_truth(
    document_id: str = "CSA-MERIDIAN-2026", settings: Settings | None = None
) -> dict[str, Any]:
    active = settings or get_settings()
    filename = f"{document_id.lower().replace('-', '_')}.expected.json"
    path: Path = active.fixtures_root / "ground_truth" / filename
    if not path.exists():
        # Fall back to the canonical fixture name.
        path = active.fixtures_root / "ground_truth" / "csa_meridian_2026.expected.json"
    if not path.exists():
        raise FileNotFoundError(f"No ground truth for {document_id}.")
    payload: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return payload


def _normalise(value: Any) -> Any:
    """Reduce a value to a comparable form. Money compares as Decimal, never float."""
    if isinstance(value, dict):
        if "amount" in value and "currency" in value:
            return (Decimal(str(value["amount"])), str(value["currency"]))
        return {
            str(k): _normalise(v) for k, v in sorted(value.items()) if not str(k).startswith("_")
        }
    if isinstance(value, list | tuple):
        return [_normalise(v) for v in value]
    if isinstance(value, str):
        # A decimal-looking string compares numerically, so "0.08" == "0.080".
        try:
            return Decimal(value)
        except (ArithmeticError, ValueError):
            return value.strip()
    if isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    return value


def _values_match(actual: Any, expected: Any) -> bool:
    return bool(_normalise(actual) == _normalise(expected))


def evaluate_extraction(
    extraction: ExtractionResult,
    ground_truth: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> EvaluationReport:
    """Score an extraction against hand-authored ground truth."""
    truth = ground_truth or load_ground_truth(extraction.document_id, settings)
    expected_fields = {entry["path"]: entry for entry in truth["fields"]}
    actual_fields = extraction.field_map

    scores: list[FieldScore] = []

    for path, expected in expected_fields.items():
        actual = actual_fields.get(path)
        if actual is None:
            continue

        value_match = _values_match(actual.value, expected["value"])

        expected_citation = expected.get("citation")
        citation_match = False
        if expected_citation and actual.citation:
            citation_match = actual.citation.overlaps(
                Citation(
                    page=int(expected_citation["page"]),
                    section=str(expected_citation["section"]),
                    quote=str(expected_citation["quote"]),
                )
            )

        expected_review = bool(expected.get("requires_review", False))
        review_match = actual.requires_review == expected_review

        score = (
            VALUE_WEIGHT * Decimal(value_match)
            + CITATION_WEIGHT * Decimal(citation_match)
            + REVIEW_WEIGHT * Decimal(review_match)
        )

        note = ""
        if expected_review and not actual.requires_review:
            note = "MISSED REVIEW FLAG - would compute on an unconfirmed value"
        elif not value_match:
            note = f"expected {expected['value']!r}, got {actual.value!r}"

        scores.append(
            FieldScore(
                path=path,
                value_match=value_match,
                citation_match=citation_match,
                review_flag_match=review_match,
                expected_review=expected_review,
                actual_review=actual.requires_review,
                score=score.quantize(Decimal("0.001")),
                note=note,
            )
        )

    return EvaluationReport(
        document_id=extraction.document_id,
        model_id=extraction.model_id,
        prompt_version=extraction.prompt_version,
        mode=extraction.mode,
        scores=tuple(scores),
        missing_fields=tuple(sorted(set(expected_fields) - set(actual_fields))),
        extra_fields=tuple(sorted(set(actual_fields) - set(expected_fields))),
    )
