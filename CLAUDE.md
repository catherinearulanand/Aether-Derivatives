# AETHER — Engineering Rules

**Autonomous Margin & Collateral Intelligence.** Institutional fintech prototype for the
GIFT IFIH Young Builders Program.

Pipeline: `CSA document → Legal-Clause Agent → deterministic Risk Engine →
Collateral Optimizer → Decision → Audit Trail`.

---

## Core principle

> **LLMs orchestrate. Deterministic engines calculate.**

Agents may interpret, route, extract and orchestrate. **Agents must not directly perform
authoritative financial calculations.** A number crosses from the agent side to the engine
side exactly once — through a typed schema, carrying source evidence.

## Never

- Invent financial calculations
- Fabricate market data
- Claim regulatory approval
- Claim zero errors
- Execute real financial transactions
- Expose secrets
- Hardcode API keys

## Always

- Make calculations reproducible
- Show source evidence for legal extraction
- Maintain audit trails
- Label simulated data
- Validate inputs
- Write tests for quantitative logic
- Preserve type safety
- Explain architectural decisions

## Demo requirement

Every major feature must be demonstrable within a **3-minute** judge presentation.
If a feature cannot be shown in that budget, it is not a feature — it is a slide.

## UX requirement

The product must look like **institutional fintech software**, not a student CRUD
application. Dense, tabular, monospaced figures, explicit currency and precision.
Not a chatbot.

## Architecture

Frontend and backend must remain **separated**. They communicate only over the versioned
HTTP API. No shared runtime, no server-rendered coupling to Python.

## Data

Prototype market data may be simulated or sourced through APIs.
**All simulated data must be clearly identified.**

---

# How this repository works

## Layout

```
backend/aether/core/      PURE. no I/O, no network, no clock, no ORM, no LLM.
backend/aether/agents/    LLM boundary: schemas, prompts, cache, replay.
backend/aether/api/       Thin routers. No business logic.
backend/aether/db/        Persistence.
backend/tests/            unit · golden · property
fixtures/                 Simulated data. Every file carries a provenance block.
scripts/                  verify_env.py — the Phase 0 gate.
docs/                     Architecture, test strategy, decision log.
frontend/                 Next.js. Not started until the vertical slice runs.
```

## The `core/` rule

`backend/aether/core/` imports no framework, opens no socket, touches no database, and
never calls `datetime.now()`. Everything in it is a function from values to values.

This is what makes golden tests and reproducible audit hashes possible. If you find
yourself wanting to import `requests` or a session into `core/`, the logic belongs in a
service instead.

## Money

- **`Decimal` at every money boundary. Never `float`.** Floats are permitted inside curve
  interpolation and LP solving; anything that becomes a cash amount is `Decimal`.
- Rounding modes are explicit and documented at the call site — never left to a default.
- `ROUND_HALF_EVEN` for valuation, `ROUND_UP` for collateral delivery amounts,
  `ROUND_DOWN` for return amounts.

## Determinism

- Every engine call takes an explicit `as_of` and a pinned `market_snapshot_id`.
- No implicit clocks. No implicit data. No network reads inside a calculation.
- Injected randomness (e.g. simulated settlement fails) uses a seeded RNG.
- **Invariant, enforced by test:** running the same pipeline twice produces byte-identical
  audit hashes.

## Reproducibility contract

Every API response containing a computed number carries:
`engine_version`, `snapshot_id`, `as_of`, `trace_id`.

## Modes

`AETHER_MODE=replay` (default) — extraction served from cached fixtures on disk. No
network. **The full demo must run in this mode.**
`AETHER_MODE=live` — real model calls. Optional, never a hard dependency.

## Network note for this machine

Outbound TLS is intercepted by **Norton Web/Mail Shield**. Python's default context and
`certifi` both fail CA validation. The API must call `truststore.inject_into_ssl()` at
startup to use the Windows trust store. Run `python scripts/verify_env.py` to confirm.

## Fixture provenance

Every fixture carries a `_provenance` block marking it simulated, e.g.:

```json
"_provenance": {
  "simulated": true,
  "authored": "2026-08-14",
  "basis": "Synthetic. Modelled on 2016 ISDA VM CSA structure.",
  "warning": "SIMULATED DATA — not real institutional data."
}
```

No fixture may be added without one.

## Language for claims

| Do not write | Write instead |
|---|---|
| "implements ISDA SIMM" | "SIMM aggregation methodology, own documented risk weights, not certified" |
| "regulatory-compliant" | "designed against IFSCA / BCBS-IOSCO margin concepts" |
| "connects to SWIFT" | "generates SWIFT-shaped instruction messages; connectivity not built" |
| "AI-calculated margin" | "AI-extracted terms, deterministically calculated margin" |
| "real-time market data" | "pinned market snapshots, for reproducibility" |

## Implementation discipline

Phases are implemented **one at a time, completely**. For each phase: inspect, implement
every required file in full, write tests, run lint/type/tests, verify the exit criteria,
report. Only then continue.

- **No placeholder or TODO implementations.** A function either works or is not written.
- **No fake functionality written merely to satisfy a test.** If a test needs behaviour that
  does not exist, build the behaviour.
- Tests for quantitative logic are written alongside the code. Golden expected values are
  derived independently — analytically or by hand — never by pasting the code's own output.

### Order

| Phase | Scope |
|---|---|
| 0 ✓ | Environment + repository verification |
| 1 | Valuation core — `money`, `curves`, `pricing/`, `exposure` |
| 2 | Margin engine — `csa`, `haircut`, `im` |
| 3 | Optimizer — `optimize`, cash-first baseline, LP duals, feasibility invariants |
| 4 | Audit + orchestration — `audit`, decision record, pipeline runner, determinism |
| 5 | Legal-Clause Agent — typed terms, citations, confidence, review, replay, eval |
| 6 | FastAPI — resource endpoints, SSE run events, thin routers, OpenAPI |
| 7 | Next.js frontend |
| 8 | Demo scenarios |
| 9 | Testing consolidation |
| 10 | Hardening |

### If time runs short

**Preserve, in order:** deterministic valuation → CSA margin → collateral optimization →
audit chain → Legal-Clause Agent replay → API → one excellent frontend screen.

**Cut:** FX option, full SIMM, dispute agent, live connectivity, authentication, production
infrastructure, non-essential UI pages.

## Commands

```bash
python scripts/verify_env.py       # Phase 0 gate — run first, and after any env change
pytest backend/tests -q            # test suite
ruff check backend && ruff format --check backend
mypy backend/aether
python scripts/build_docs_pdf.py   # regenerate docs/pdf/*.pdf
```
