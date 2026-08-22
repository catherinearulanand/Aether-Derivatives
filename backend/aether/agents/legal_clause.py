"""The Legal-Clause Agent.

Reads a CSA and produces typed, cited, confidence-scored
:class:`~aether.agents.schema.ExtractedField` values. It never computes a margin
number, never invents a value that is not in the text, and never emits a field
without a citation.

.. rubric:: Two modes, one output type

``replay`` reads a cached extraction from disk. No network, no key, no latency, and
byte-identical every time. **This is the demo path.**

``live`` calls the model with ``temperature=0``, a pinned model id and a versioned
prompt, then validates the response against the same schema.

Both return an :class:`ExtractionResult`, so nothing downstream can tell — or needs
to tell — which mode produced it, beyond the ``mode`` field recorded for the audit
trail.

.. rubric:: Why replay is the default

Live connectivity on the build machine depends on an antivirus product's certificate
injection continuing to behave, on a network that will not be the one in the
demonstration room. A judged demo should not rest on that. Live mode exists and works;
the demo does not need it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from aether.agents.prompts import EXTRACTION_PROMPT, PROMPT_VERSION
from aether.agents.schema import (
    Citation,
    ConditionalValue,
    ExtractedField,
    ExtractionResult,
    FieldSource,
    ReviewReason,
)
from aether.config import Mode, Settings, get_settings, install_tls_trust
from aether.governance.sanitise import sanitise_document

__all__ = [
    "CONFIDENCE_THRESHOLD",
    "ExtractionError",
    "document_sha256",
    "extract_terms",
    "load_document",
]

#: Fields below this confidence are routed to a human before an agreement can freeze.
CONFIDENCE_THRESHOLD = 0.85


class ExtractionError(RuntimeError):
    """Raised when extraction cannot produce a usable result."""


def document_sha256(text: str) -> str:
    """Content hash. Keys the replay cache and anchors the audit trail."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_document(
    document_id: str,
    settings: Settings | None = None,
    prefer: str = "md",
) -> str:
    """Read a source document's text layer.

    Two ingestion formats, one downstream path:

    - **Markdown** — the authored source, and the default.
    - **Native PDF** — ``prefer="pdf"`` extracts the text layer with ``pypdf``. This
      is the format a Credit Support Annex actually arrives in, and the extracted
      text runs through exactly the same agent, prompt and schema.

    **Scanned** documents — an image with no text layer — are out of scope and stated
    as such on the methodology endpoint. Reading one needs a vision model call; a
    hand-authored "OCR result" would be a fabrication, not a capability.
    """
    active = settings or get_settings()
    root = active.fixtures_root / "documents"

    if prefer == "pdf":
        pdf_path = root / _document_filename(document_id, "pdf")
        if not pdf_path.exists():
            raise ExtractionError(
                f"No PDF found for '{document_id}' at {pdf_path}. "
                f"Run: python scripts/build_csa_pdf.py"
            )
        return extract_pdf_text(pdf_path)

    path = root / _document_filename(document_id, "md")
    if not path.exists():
        raise ExtractionError(f"No document found for '{document_id}' at {path}.")
    return path.read_text(encoding="utf-8")


def extract_pdf_text(path: Path) -> str:
    """Extract the text layer from a native PDF.

    Raises if the PDF has no text layer, rather than returning an empty string that
    would silently produce an empty extraction. A scanned document fails here, loudly
    and with the reason.
    """
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - dependency is pinned
        raise ExtractionError("Reading a PDF needs pypdf. Run: pip install pypdf") from exc

    reader = PdfReader(str(path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if len(text.strip()) < 200:
        raise ExtractionError(
            f"{path.name} has {len(text.strip())} characters of extractable text across "
            f"{len(reader.pages)} pages. It is most likely a scanned image, which this "
            f"prototype does not read: that needs a vision model call, and AETHER does "
            f"not claim OCR it has not performed."
        )
    return text


def _document_filename(document_id: str, extension: str) -> str:
    known = {"CSA-MERIDIAN-2026": "csa_meridian_2026"}
    stem = known.get(document_id, document_id.lower())
    return f"{stem}.{extension}"


def _parse_citation(raw: Any) -> Citation | None:
    if not raw:
        return None
    return Citation(
        page=int(raw["page"]),
        section=str(raw["section"]),
        quote=str(raw["quote"]),
    )


def _parse_field(raw: dict[str, Any]) -> ExtractedField:
    """Build a field, applying the confidence policy consistently.

    A field is routed to review when the agent explicitly flags it *or* when its
    confidence falls below the threshold. The agent cannot opt out of the threshold.
    """
    confidence = float(raw.get("confidence", 0.0))
    flagged = bool(raw.get("requires_review", False))
    below_threshold = confidence < CONFIDENCE_THRESHOLD

    reason_raw = raw.get("review_reason")
    if reason_raw:
        reason = ReviewReason(str(reason_raw))
    elif below_threshold:
        reason = ReviewReason.LOW_CONFIDENCE
    else:
        reason = None

    conditional_raw = raw.get("conditional")
    conditional = None
    if isinstance(conditional_raw, dict):
        conditional = ConditionalValue(
            trigger=str(conditional_raw["trigger"]),
            condition=str(conditional_raw["condition"]),
            value_if_triggered=conditional_raw.get("value_if_triggered"),
            trigger_citation=_parse_citation(conditional_raw.get("trigger_citation")),
        )

    return ExtractedField(
        path=str(raw["path"]),
        value=raw.get("value"),
        confidence=confidence,
        citation=_parse_citation(raw.get("citation")),
        source=FieldSource.AGENT,
        requires_review=flagged or below_threshold,
        review_reason=reason,
        review_note=str(raw.get("review_note", "")),
        conditional=conditional,
    )


def _replay_path(document_id: str, settings: Settings) -> Path:
    return settings.fixtures_root / "extractions" / f"{document_id}.replay.json"


def _extract_replay(document_id: str, text: str, settings: Settings) -> ExtractionResult:
    """Serve a cached extraction. No network, deterministic, instant."""
    path = _replay_path(document_id, settings)
    if not path.exists():
        raise ExtractionError(
            f"Replay mode needs a cached extraction at {path}, which does not exist. "
            f"Either add the cache or run with AETHER_MODE=live."
        )

    payload = json.loads(path.read_text(encoding="utf-8"))
    provenance = payload.get("_provenance", {})
    if provenance.get("simulated") is not True:
        raise ExtractionError(f"{path.name} does not declare itself simulated data.")

    fields = tuple(_parse_field(raw) for raw in payload["fields"])

    return ExtractionResult(
        document_id=document_id,
        document_sha256=document_sha256(text),
        fields=fields,
        model_id=str(payload.get("model_id", settings.model_id)),
        prompt_version=str(payload.get("prompt_version", PROMPT_VERSION)),
        mode=Mode.REPLAY.value,
        temperature=0.0,
        cache_hit=True,
        latency_ms=0,
    )


def _extract_live(document_id: str, text: str, settings: Settings) -> ExtractionResult:
    """Call the model and validate its response against the schema."""
    if not settings.api_key:
        raise ExtractionError(
            "AETHER_MODE=live requires ANTHROPIC_API_KEY. Unset it or switch to "
            "AETHER_MODE=replay, which needs no key and no network."
        )

    install_tls_trust(settings)

    try:
        import time

        from anthropic import Anthropic
    except ImportError as exc:  # pragma: no cover - dependency is pinned
        raise ExtractionError("The anthropic package is not installed.") from exc

    client = Anthropic(api_key=settings.api_key)
    started = time.monotonic()

    # The document is delivered inside a per-document boundary derived from its
    # own content hash, so text inside it cannot forge a closing marker to break
    # out. Detections are reported, never stripped: removing them would destroy
    # the evidence and change the hash the audit chain is anchored to.
    prepared = sanitise_document(document_id, text)

    message = client.messages.create(
        model=settings.model_id,
        max_tokens=8192,
        temperature=0.0,
        system=EXTRACTION_PROMPT,
        messages=[{"role": "user", "content": prepared.framed}],
    )
    latency_ms = int((time.monotonic() - started) * 1000)

    body = "".join(str(getattr(block, "text", "")) for block in message.content).strip()

    # The prompt requires a bare JSON object; strip a fenced block if one appears.
    if body.startswith("```"):
        body = body.split("\n", 1)[1].rsplit("```", 1)[0]

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ExtractionError(
            f"Model response was not valid JSON: {exc}. The deterministic engine "
            f"never sees unvalidated output, so this run is discarded."
        ) from exc

    fields = tuple(_parse_field(raw) for raw in payload.get("fields", []))
    if not fields:
        raise ExtractionError("Model returned no fields.")

    return ExtractionResult(
        document_id=document_id,
        document_sha256=document_sha256(text),
        fields=fields,
        model_id=settings.model_id,
        prompt_version=PROMPT_VERSION,
        mode=Mode.LIVE.value,
        temperature=0.0,
        cache_hit=False,
        latency_ms=latency_ms,
    )


def extract_terms(
    document_id: str = "CSA-MERIDIAN-2026",
    settings: Settings | None = None,
    source_format: str = "md",
) -> ExtractionResult:
    """Extract CSA terms from a document.

    ``source_format`` chooses the ingestion path — the authored markdown source, or
    the native PDF's extracted text layer. Both produce the same
    :class:`ExtractionResult` type and take the same downstream route.

    Falls back to replay if live is configured but unusable, because a demo that
    fails closed is worse than a demo that fails over.
    """
    active = settings or get_settings()
    text = load_document(document_id, active, prefer=source_format)

    if active.mode is Mode.LIVE and active.api_key:
        try:
            return _extract_live(document_id, text, active)
        except ExtractionError:
            if _replay_path(document_id, active).exists():
                return _extract_replay(document_id, text, active)
            raise

    return _extract_replay(document_id, text, active)
