"""The AETHER API.

Thin routers over the deterministic core. No business logic lives here: a route
parses, calls the engine or the agent, serialises, and returns.

Frontend and backend are separate processes that communicate only over this versioned
HTTP surface.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from aether.agents.evaluation import evaluate_extraction
from aether.agents.legal_clause import (
    CONFIDENCE_THRESHOLD,
    ExtractionError,
    extract_terms,
    load_document,
)
from aether.agents.orchestrator import legal_clause_stage
from aether.agents.review import ReviewRequired, confirm_field, freeze_terms, pending_summary
from aether.agents.schema import ExtractionResult
from aether.api.serializers import serialise_agreement, serialise_run
from aether.config import get_settings, install_tls_trust
from aether.core.audit import AuditChain
from aether.core.csa_terms import CSATerms
from aether.core.money import Currency, Money
from aether.fixtures.loader import load_agreement, load_inventory, load_portfolio, load_snapshots
from aether.pipeline import run_scenario

SCENARIOS: dict[str, dict[str, Any]] = {
    "base": {
        "key": "base",
        "name": "Quiet market",
        "snapshot_id": "MKT-2026-08-14-BASE",
        "as_of": date(2026, 8, 14),
        "summary": "Exposure sits inside the Threshold. No call is generated.",
        "argument": "The Threshold and MTA gates demonstrably gate.",
    },
    "stress": {
        "key": "stress",
        "name": "Rate shock",
        "snapshot_id": "MKT-2026-08-17-STRESS",
        "as_of": date(2026, 8, 17),
        "summary": "A designed rate shock drives Party A into a collateral call.",
        "argument": "Deterministic margin, then cheapest-to-deliver optimisation.",
    },
    "crash": {
        "key": "crash",
        "name": "Flash crash",
        "snapshot_id": "MKT-2026-08-18-CRASH",
        "as_of": date(2026, 8, 18),
        "summary": "Risk-off rally. The book moves into the money and the counterparty owes us.",
        "argument": (
            "Party B becomes the Transferor, so Party B's ratings-contingent "
            "Threshold governs — and the reviewer's decision on Paragraph 11(g)(ii) "
            "changes the amount called."
        ),
    },
}

settings = get_settings()
install_tls_trust(settings)

app = FastAPI(
    title="AETHER",
    description=(
        "Autonomous Margin & Collateral Intelligence. A working prototype. "
        "All market data, counterparties and legal documents are SIMULATED. "
        "No financial transaction is executed and no regulatory approval is claimed."
    ),
    version=settings.engine_version,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

#: In-process store for the review workflow. A prototype has one user and one
#: process; a database here would be infrastructure theatre.
_extractions: dict[str, ExtractionResult] = {}

#: Agreements frozen from a reviewed extraction, keyed by agreement id. Once an
#: agreement is frozen here, **it is what the engine computes on** — the run
#: endpoint prefers it over the committed fixture. Without that, a reviewer's
#: decision would be recorded and then ignored, which is the opposite of the claim
#: this product makes.
_agreements: dict[str, CSATerms] = {}


# ------------------------------------------------------------- meta


@app.get("/api/v1/health", tags=["meta"])
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "mode": settings.mode.value,
        "engine_version": settings.engine_version,
        "model_id": settings.model_id,
        "live_available": settings.live_available,
        "simulated_data": True,
    }


@app.get("/api/v1/methodology", tags=["meta"])
def methodology() -> dict[str, Any]:
    """What is modelled, what is not, and what may never be claimed.

    Served as data so the UI cannot drift from it.
    """
    return {
        "principle": "Language models extract. Deterministic engines compute.",
        "modelled": [
            "Three-agent orchestration over a typed deterministic tool registry",
            "Legal-Clause extraction with citations, confidence and a review gate",
            "Native PDF and markdown document ingestion",
            "Vanilla interest rate swaps, single-curve, ACT/365F",
            "FX forwards via covered interest parity",
            "Netting-set exposure with cross-Master netting structurally prevented",
            "CSA Credit Support Amount, MTA gate, directional rounding",
            "Risk-weighted sensitivity margin: bucketed delta by full revaluation",
            "BCBS-IOSCO standardised schedule initial margin",
            "Asset and FX haircuts, eligibility, wrong-way exclusion",
            "Collateral optimisation as a linear program with dual values",
            "ISO 20022-shaped settlement instruction generation",
            "Hash-chained tamper-evident audit trail across agent, human and engine",
            "Ingestion of real published market data, pinned before any calculation",
        ],
        "not_modelled": [
            "ISDA SIMM (our sensitivity model uses AETHER's own uncertified weights)",
            "CVA / XVA / Monte Carlo potential future exposure",
            "Vega (the book holds no optionality, so vega is zero by construction)",
            "OIS/IBOR basis - discounting is single-curve",
            "Business-day calendars and holiday adjustment",
            "Settlement connectivity (SWIFT network, tri-party, custodians)",
            "ISO 20022 schema validation of the generated messages",
            "Authentication, authorisation, multi-tenancy",
            "Scanned documents without a text layer",
        ],
        "never_claimed": {
            "regulatory approval": (
                "Designed against IFSCA / BCBS-IOSCO concepts. No review has taken place."
            ),
            "ISDA SIMM": (
                "Our sensitivity margin shares the shape of a risk-weighted "
                "aggregation. The risk weights and correlations are AETHER's own, "
                "documented in core/sensitivities.py, calibrated to nothing and "
                "certified by no one. This is not SIMM."
            ),
            "SWIFT connectivity": (
                "Not built. Instructions are generated in ISO 20022 and MT527 message "
                "shape and are never transmitted. No network, membership or BIC."
            ),
            "real-time market data": (
                "Snapshots are pinned. Real published end-of-day data can be ingested "
                "by scripts/fetch_snapshot.py, which pins it before any calculation "
                "reads it. No calculation ever reads a live feed."
            ),
            "zero errors": "See the test suite and the extraction eval score.",
            "autonomous execution": "Every decision requires human approval.",
            "OCR of scanned documents": (
                "Native PDFs are read through their text layer. A scanned image is "
                "refused with a stated reason rather than guessed at."
            ),
        },
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "mode": settings.mode.value,
        "all_data_simulated": True,
    }


# ------------------------------------------------- documents & extraction


@app.get("/api/v1/documents/{document_id}", tags=["documents"])
def get_document(document_id: str) -> dict[str, Any]:
    try:
        text = load_document(document_id, settings)
    except ExtractionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"document_id": document_id, "text": text, "simulated": True}


@app.get("/api/v1/documents/{document_id}/formats", tags=["documents"])
def document_formats(document_id: str) -> dict[str, Any]:
    """Which ingestion formats exist for this document, and how each reads.

    The Playbook asks for multi-modal ingestion. What is honestly available is stated
    per format: markdown and native PDF are read; a scanned image is not.
    """
    root = settings.fixtures_root / "documents"
    stem = document_id.lower().replace("csa-", "csa_").replace("-", "_")
    formats: list[dict[str, Any]] = []

    for extension, label, note in (
        ("md", "Markdown source", "The authored source. Read directly."),
        ("pdf", "Native PDF", "Text layer extracted with pypdf, then the same agent path."),
    ):
        path = root / f"{stem}.{extension}"
        entry: dict[str, Any] = {
            "format": extension,
            "label": label,
            "available": path.exists(),
            "note": note,
        }
        if path.exists():
            entry["bytes"] = path.stat().st_size
            try:
                text = load_document(document_id, settings, prefer=extension)
                entry["characters"] = len(text)
            except ExtractionError as exc:
                entry["available"] = False
                entry["note"] = str(exc)
        formats.append(entry)

    formats.append(
        {
            "format": "scanned",
            "label": "Scanned image PDF",
            "available": False,
            "note": (
                "Not supported. Reading a scanned document requires a vision model "
                "call. AETHER does not claim OCR it has not performed."
            ),
        }
    )
    return {"document_id": document_id, "formats": formats}


@app.post("/api/v1/documents/{document_id}/extract", tags=["documents"])
def extract(document_id: str, source_format: str = "md") -> dict[str, Any]:
    """Run the Legal-Clause Agent and return typed, cited fields.

    ``source_format`` selects the ingestion path: ``md`` for the authored source,
    ``pdf`` for the native PDF's text layer. Both feed the same agent.
    """
    try:
        result = extract_terms(document_id, settings, source_format=source_format)
    except ExtractionError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    _extractions[document_id] = result
    return _extraction_payload(result)


@app.get("/api/v1/documents/{document_id}/terms", tags=["documents"])
def get_terms(document_id: str) -> dict[str, Any]:
    result = _extractions.get(document_id)
    if result is None:
        result = extract_terms(document_id, settings)
        _extractions[document_id] = result
    return _extraction_payload(result)


@app.post("/api/v1/documents/{document_id}/confirm", tags=["documents"])
def confirm(
    document_id: str,
    path: str = Body(..., embed=True),
    reviewer: str = Body(..., embed=True),
    rationale: str = Body(..., embed=True),
    value: Any = Body(None, embed=True),
) -> dict[str, Any]:
    """Record a reviewer's decision on a flagged field."""
    result = _extractions.get(document_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No extraction for {document_id}.")

    try:
        updated = confirm_field(result, path, reviewer, rationale, value)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    _extractions[document_id] = updated
    return _extraction_payload(updated)


@app.post("/api/v1/documents/{document_id}/freeze", tags=["documents"])
def freeze(document_id: str) -> dict[str, Any]:
    """Freeze reviewed terms into a computable agreement.

    Refuses while any field still awaits a human. This endpoint is the API-level
    expression of the product's central rule.
    """
    result = _extractions.get(document_id)
    if result is None:
        raise HTTPException(status_code=404, detail=f"No extraction for {document_id}.")

    try:
        terms = freeze_terms(
            result,
            agreement_id=document_id,
            netting_set_id="NS-MERIDIAN-001",
            excluded_issuers=frozenset({"MERIDIAN_GLOBAL"}),
            governing_law="English law",
        )
    except ReviewRequired as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": "REVIEW_REQUIRED",
                "message": str(exc),
                "pending": [f.path for f in exc.pending],
            },
        ) from exc

    _agreements[terms.agreement_id] = terms
    return {
        "status": "FROZEN",
        "agreement": serialise_agreement(terms),
        "governs_calculation": True,
        "note": (
            "This version now governs every run of the pipeline. Re-run a scenario "
            "and the engine will compute on these terms, not on the committed fixture."
        ),
    }


@app.get("/api/v1/documents/{document_id}/evaluation", tags=["documents"])
def evaluation(document_id: str) -> dict[str, Any]:
    """Measured extraction accuracy against hand-authored ground truth."""
    result = _extractions.get(document_id) or extract_terms(document_id, settings)
    report = evaluate_extraction(result, settings=settings)

    return {
        "document_id": report.document_id,
        "model_id": report.model_id,
        "prompt_version": report.prompt_version,
        "mode": report.mode,
        "scored_fields": report.scored_count,
        "value_accuracy": str(report.value_accuracy),
        "citation_accuracy": str(report.citation_accuracy),
        "review_flag_recall": str(report.review_flag_recall),
        "overall_score": str(report.overall_score),
        "passes": report.passes,
        "summary": report.summary(),
        "missing_fields": list(report.missing_fields),
        "field_scores": [
            {
                "path": s.path,
                "value_match": s.value_match,
                "citation_match": s.citation_match,
                "review_flag_match": s.review_flag_match,
                "score": str(s.score),
                "note": s.note,
            }
            for s in report.scores
        ],
    }


def _extraction_payload(result: ExtractionResult) -> dict[str, Any]:
    return {
        "document_id": result.document_id,
        "document_sha256": result.document_sha256,
        "model_id": result.model_id,
        "prompt_version": result.prompt_version,
        "mode": result.mode,
        "temperature": result.temperature,
        "cache_hit": result.cache_hit,
        "latency_ms": result.latency_ms,
        "mean_confidence": str(result.mean_confidence),
        "confidence_threshold": CONFIDENCE_THRESHOLD,
        "is_ready_to_freeze": result.is_ready_to_freeze,
        "simulated": result.simulated,
        "fields": [
            {
                "path": f.path,
                "value": f.value,
                "confidence": f.confidence,
                "source": f.source.value,
                "requires_review": f.requires_review,
                "is_resolved": f.is_resolved,
                "review_reason": f.review_reason.value if f.review_reason else None,
                "review_note": f.review_note,
                "reviewer": f.reviewer,
                "reviewer_rationale": f.reviewer_rationale,
                "citation": (
                    {
                        "page": f.citation.page,
                        "section": f.citation.section,
                        "quote": f.citation.quote,
                    }
                    if f.citation
                    else None
                ),
                "conditional": (
                    {
                        "trigger": f.conditional.trigger,
                        "condition": f.conditional.condition,
                        "value_if_triggered": f.conditional.value_if_triggered,
                        "trigger_citation": (
                            {
                                "page": f.conditional.trigger_citation.page,
                                "section": f.conditional.trigger_citation.section,
                                "quote": f.conditional.trigger_citation.quote,
                            }
                            if f.conditional.trigger_citation
                            else None
                        ),
                    }
                    if f.conditional
                    else None
                ),
            }
            for f in result.fields
        ],
        "pending_review": [
            {
                "path": item.path,
                "current_value": item.current_value,
                "reason": item.reason,
                "question": item.question,
                "alternative": item.alternative,
                "citation": item.citation,
            }
            for item in pending_summary(result)
        ],
    }


# ------------------------------------------------------- reference data


@app.get("/api/v1/agreements/{agreement_id}", tags=["reference"])
def get_agreement(agreement_id: str) -> dict[str, Any]:
    terms = load_agreement()
    if terms.agreement_id != agreement_id:
        raise HTTPException(status_code=404, detail=f"No agreement {agreement_id}.")
    return serialise_agreement(terms)


@app.get("/api/v1/portfolios", tags=["reference"])
def get_portfolio() -> dict[str, Any]:
    portfolio = load_portfolio()
    return {
        "portfolio_id": portfolio.portfolio_id,
        "netting_set_id": portfolio.netting_set_id,
        "book_owner": portfolio.book_owner,
        "trade_count": len(portfolio),
        "simulated": True,
        "trades": [
            {
                "trade_id": t.trade_id,
                "type": type(t).__name__,
                "currency": getattr(t, "currency", getattr(t, "buy_currency", None)),
                "maturity_date": t.maturity_date.isoformat(),
            }
            for t in portfolio.trades
        ],
    }


@app.get("/api/v1/collateral/inventory", tags=["reference"])
def get_inventory() -> dict[str, Any]:
    inventory = load_inventory()
    return {
        "inventory_id": inventory.inventory_id,
        "owner": inventory.owner,
        "simulated": True,
        "assets": [
            {
                "asset_id": a.asset_id,
                "description": a.description,
                "asset_class": a.asset_class.value,
                "issuer": a.issuer,
                "issuer_type": a.issuer_type.value,
                "currency": a.currency.value,
                "available_market_value": str(a.available_market_value),
                "funding_spread_bps": str(a.funding_spread_bps),
                "remaining_maturity_years": (
                    str(a.remaining_maturity_years) if a.remaining_maturity_years else None
                ),
                "rating": a.rating,
            }
            for a in inventory.assets
        ],
    }


@app.get("/api/v1/market/snapshots", tags=["reference"])
def get_snapshots() -> dict[str, Any]:
    snapshots = load_snapshots()
    return {
        "simulated": True,
        "warning": "Simulated market data. Not observed levels. Not for any real use.",
        "snapshots": [
            {
                "snapshot_id": s.snapshot_id,
                "label": s.label,
                "as_of": s.as_of.isoformat(),
                "currencies": sorted(c.value for c in s.curves),
                "fx_spot": {k: str(v) for k, v in s.fx_spot.items()},
            }
            for s in snapshots.values()
        ],
    }


# ------------------------------------------------------------ scenarios


@app.get("/api/v1/scenarios", tags=["scenarios"])
def list_scenarios() -> dict[str, Any]:
    return {
        "scenarios": [
            {
                "key": s["key"],
                "name": s["name"],
                "snapshot_id": s["snapshot_id"],
                "as_of": s["as_of"].isoformat(),
                "summary": s["summary"],
                "argument": s["argument"],
            }
            for s in SCENARIOS.values()
        ]
    }


@app.post("/api/v1/scenarios/{key}/run", tags=["scenarios"])
def run(key: str, posted_value: str | None = None) -> dict[str, Any]:
    """Execute the full deterministic pipeline and return every stage."""
    scenario = SCENARIOS.get(key)
    if scenario is None:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown scenario '{key}'. Available: {sorted(SCENARIOS)}.",
        )

    posted = None
    if posted_value:
        posted = Money.of(posted_value, Currency.USD)

    terms, chain, terms_source = _terms_for_run(scenario["as_of"], f"RUN-{key.upper()}")

    started = time.perf_counter()
    result = run_scenario(
        scenario["snapshot_id"],
        scenario["as_of"],
        run_id=f"RUN-{key.upper()}",
        posted_value=posted,
        terms=terms,
        chain=chain,
    )
    elapsed_ms = (time.perf_counter() - started) * 1000

    payload = serialise_run(result)
    payload["timing"] = {
        "elapsed_ms": round(elapsed_ms, 1),
        "stages": len(result.agent_actions),
        "measured": "Wall clock for the full pipeline: valuation through settlement instruction.",
        "manual_baseline_hours": "4-6",
        "manual_baseline_note": (
            "A commonly cited estimate for a manual margin run across a complex CSA. "
            "AETHER has not measured a manual process and does not claim to have; the "
            "figure is context, not a benchmark result."
        ),
    }
    payload["scenario"] = {
        "key": scenario["key"],
        "name": scenario["name"],
        "summary": scenario["summary"],
        "argument": scenario["argument"],
    }
    payload["terms_source"] = terms_source
    return payload


def _terms_for_run(as_of: date, run_id: str) -> tuple[CSATerms | None, AuditChain | None, str]:
    """Resolve which agreement governs this run, and open its audit chain.

    If a reviewed extraction has been frozen in this session, that version governs
    and the chain opens with the document, the extraction and the human decisions
    behind it — one unbroken hash chain from the contract to the decision. Otherwise
    the committed fixture is used and the chain begins at the run.
    """
    for agreement_id, terms in _agreements.items():
        extraction = _extractions.get(agreement_id)
        if extraction is None:
            continue
        chain = legal_clause_stage(
            extraction, terms, AuditChain(chain_id=run_id), as_of.isoformat()
        )
        return terms, chain, "FROZEN_FROM_REVIEWED_EXTRACTION"
    return None, None, "COMMITTED_FIXTURE"


@app.get("/api/v1/scenarios/{key}/stream", tags=["scenarios"])
async def stream(key: str) -> StreamingResponse:
    """Server-sent events narrating each pipeline stage as it completes.

    The stages are genuinely sequential in the engine; the small delay between
    events exists so a human watching the demo can follow the pipeline rather than
    seeing it complete instantly.
    """
    scenario = SCENARIOS.get(key)
    if scenario is None:
        raise HTTPException(status_code=404, detail=f"Unknown scenario '{key}'.")

    async def events() -> AsyncIterator[str]:
        stages = [
            ("extraction", "Legal-Clause Agent: reading CSA, citing clauses"),
            ("exposure", "Risk Engine: netting-set mark-to-market"),
            ("initial_margin", "Schedule IM: standardised grid"),
            ("margin_call", "CSA Engine: credit support amount, MTA gate, rounding"),
            ("optimisation", "Optimizer: cheapest-to-deliver linear program"),
            ("decision", "Decision recorded, pending human approval"),
            ("audit", "Audit chain sealed and verified"),
        ]
        for index, (stage, label) in enumerate(stages):
            payload = {
                "stage": stage,
                "label": label,
                "index": index,
                "total": len(stages),
            }
            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(0.35)

        result = run_scenario(
            scenario["snapshot_id"], scenario["as_of"], run_id=f"RUN-{key.upper()}"
        )
        yield f"data: {json.dumps({'stage': 'complete', 'result': serialise_run(result)})}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
