# AETHER — Architecture & Decision Log

Working document. The narrative version, with diagrams and the full risk register, is the
shared architecture artifact; this file is the one that gets edited during the build.

**Scope:** 48-hour solo prototype, demo 2026-08-16. One complete vertical slice, in depth,
over breadth.

---

## The slice

```
CSA document → Legal-Clause Agent → reviewed, frozen terms
             → Risk-Engine Agent → Collateral-Optimizer Agent → Decision → Audit
```

Three agents orchestrate; deterministic engines calculate. The boundary between them
is a type, not a convention — see D-011.

## Core principle

> **LLMs orchestrate. Deterministic engines calculate.**

Agents interpret, route, extract and orchestrate. Agents never perform authoritative
financial calculations. A number crosses from the agent side to the engine side exactly
once — through a typed schema, carrying source evidence, past a human confirmation when
confidence is low.

---

## Phase 0 results (complete)

| Check | Result |
|---|---|
| Python | 3.14.3 — **staying**, no downgrade needed |
| numpy / scipy | 2.4.3 / 1.18.0, cp314 wheels confirmed. LP solver viable. |
| Outbound TLS | **Intercepted by Norton Web/Mail Shield.** Default context and certifi both fail. |
| TLS resolution | `truststore` + Windows trust store **works** — TLSv1.3 established |
| Demo mode | `live` available; **`replay` remains the default and the demo path** |
| Gate | 15 passed, 3 warned, 0 failed |

**Decision D-001 — call `truststore.inject_into_ssl()` at API startup.** Without it the
Anthropic SDK cannot establish TLS on this machine. Guarded by `AETHER_USE_TRUSTSTORE`.

**Decision D-002 — replay mode stays the demo path even though live now works.** Live
connectivity depends on a third-party AV product's certificate injection continuing to
behave. That is not something to discover is broken during a judged presentation.

---

## Decision log

| # | Decision | Rationale |
|---|---|---|
| D-001 | `truststore.inject_into_ssl()` at startup | Only working TLS path on this machine |
| D-002 | Replay is the demo path; live is optional | Removes network from the critical path |
| D-003 | `Decimal` at every money boundary | Float drift in margin figures is indefensible and invisible |
| D-004 | Single-curve discounting, no OIS/IBOR basis | Basis changes no conclusion in the demo; costs a day |
| D-005 | SQLite, not Postgres | Docker is not installed. SQLite stays Postgres-shaped for later. |
| D-006 | LP is continuous, not MILP | Solves exactly and instantly; integer lot sizes add no demo value |
| D-007 | No vector DB / RAG | Document is bounded and small; full-document extraction is more accurate and removes a failure class |
| D-008 | Markdown CSA fixture, not PDF | Text layer is what extraction consumes. PDF rendering is presentation, deferred until the UI exists. |
| D-009 | Backend-first; frontend after the slice runs | An impressive parser with no engine behind it is worth nothing at the deadline |
| D-010 | Cash carries the *highest* funding cost in the inventory | Reflects real opportunity cost, and is what makes the cash-first baseline genuinely expensive to beat |
| D-011 | Agent tool-call arguments are `str \| int \| bool \| None` | Makes "an LLM never produces an authoritative number" structural rather than procedural. A `Decimal` argument raises at construction, so a hallucinated figure cannot reach an engine even via a model-authored plan |
| D-012 | Two IM figures, neither charged to the VM call | The schedule grid and a sensitivity aggregation disagree, and the disagreement is informative: a notional grid cannot see that a book is hedged. Charging either to a VM call would overstate the requirement |
| D-013 | Sensitivities by full revaluation, not closed form | One repricing per bucket costs milliseconds and removes an entire class of analytic-derivative bugs |
| D-014 | Settlement generates messages and never transmits | The Playbook's fourth feature is deliverable honestly as message *shape*. Connectivity is not, so it is refused rather than faked |
| D-015 | Market data is ingested live and pinned before use | Satisfies "live market data" and "no calculation reads a feed" simultaneously. The network call happens in a script; the engine reads a pinned file |
| D-016 | The optimizer only runs when the inventory owner is the Transferor | Optimising our own inventory against the counterparty's obligation is meaningless. When they owe, we issue a call and await their proposal |
| D-017 | Two loaders, not one relaxed loader | `load_json` stays simulated-only so no real data can reach the engine by the demo path. Real published data has its own named door with four required conditions. Supporting ingestion never cost us the original guarantee |
| D-018 | **No fixture value is changed after observing an output** | The rupee paper is not selected on the committed inventory, and that stands. A bill holding was briefly reduced to bring it back into the allocation; that was reverted, because tuning an input to produce a preferred result is the one thing a reproducibility claim cannot survive. The cross-border argument is carried by the ranking, which the optimizer computes for every eligible asset whether or not it is posted |

---

## Layering

```
backend/aether/core/      PURE. no I/O, no network, no clock, no ORM, no LLM.
backend/aether/agents/    LLM boundary: schemas, prompts, cache, replay.
backend/aether/api/       Thin routers. No business logic.
backend/aether/db/        Persistence.
```

Routers parse and validate, then call a service. Services orchestrate persistence and call
`core/`. `core/` computes. Business logic never appears in a router; persistence never
appears in `core/`.

---

## Deterministic functions in the slice

Cut down from the full design to what the slice needs. All rows marked yes are built and tested.

| # | Function | In slice |
|---|---|---|
| F1 | Discount curve, log-linear on DFs | yes |
| F2 | Vanilla IRS PV, single curve | yes |
| F3 | FX forward PV | yes |
| F5 | Netting-set exposure, netting-set enforced | yes |
| F6 | Credit Support Amount, MTA gate, rounding | yes — **the core** |
| F8 | Asset haircut × FX haircut | yes |
| F9 | Collateral optimization LP + baseline + duals | yes |
| F12 | Audit hash chain | yes |
| F7 | Initial margin, BCBS-IOSCO standardised schedule | yes — reported, **not** charged to the VM call |
| F13 | Risk-weighted sensitivity margin | yes — bucketed delta by revaluation, own weights, **not SIMM** |
| F10 | Settlement instruction, ISO 20022 / MT527 message shape | yes — generated, **never transmitted** |
| F4 | FX option (Garman–Kohlhagen) | **cut** — and vega is therefore zero by construction |
| F11 | Dispute attribution | **cut** |

### F6 — the calculation the product exists to get right

```
PostedValue         = Σ MV_a · valuation_pct_a · (1 − fx_haircut_a) · fx(a → base)
CreditSupportAmount = max(0, IA + max(0, Exposure) − Threshold)
DeliveryAmount      = CreditSupportAmount − PostedValue        if > 0
ReturnAmount        = PostedValue − CreditSupportAmount        if > 0

gate    if |Amount| < MTA → 0          ← tested on the UNROUNDED amount, per CSA 3(b)
round   ROUND_UP for delivery, ROUND_DOWN for return, to USD 100,000
```

### F9 — the commercial thesis

```
minimise    Σ cost_a · x[a,c]
subject to  Σ x[a,c] · valuation_pct_a · (1 − fx_haircut_a) ≥ required_c
            Σ x[a,c] ≤ available_a
            x[a,c] = 0  if a ∉ eligible(c)          ← includes wrong-way exclusion
            Σ_{a ∈ class} x[a,c] ≤ cap_class
```

Three outputs beyond the allocation:
- **Cost per effective unit** = `cost_a / (valuation_pct_a · (1 − fx_haircut_a))` — the
  cheapest-to-deliver ranking, and the reason the cheapest headline asset is not always
  chosen.
- **Baseline comparison** against the cash-first heuristic. Measured, never asserted.
- **Shadow prices** from the LP duals — "the binding constraint is the 20% equity cap;
  relaxing it by USD 1m saves N bp."

---

## Build status — all blocks delivered

| Block | Work | Exit gate | Status |
|---|---|---|---|
| **1** | `core/money.py`, `curves.py`, `pricing/`, `exposure.py` | Golden tests match analytically-derived values | done |
| **2** | `core/csa.py` (F6), `haircut.py` (F8), `im.py` (F7) | 8 golden CSA cases green incl. MTA-before-rounding | done |
| **3** | `core/optimize.py` (F9), baseline, duals | `optimizer ≤ baseline` invariant green; wrong-way excluded | done |
| **4** | `core/audit.py` (F12), decision, pipeline runner | Two runs, identical hashes. Slice runs headless. | done |
| **5** | Legal-Clause Agent: schema, prompt, replay, review gate, eval | Eval meets targets offline; freeze refuses unreviewed input | done |
| **6** | FastAPI routers, SSE, OpenAPI | Slice runs over HTTP | done |
| **7** | Frontend: desk, review, optimizer, audit, methodology | Demo runs in a browser | done |
| **8** | Demo scenarios, talk track, README | Full run offline | done |
| **9** | Playbook alignment: agent swarm, sensitivity margin, settlement, gold, cross-border surfacing, PDF and market-data ingestion | Agent boundary enforced by type and asserted by test; frozen terms govern the calculation | done |

**Final state:** 406 tests passing, `ruff` and `mypy --strict` clean across 34 source
files, frontend `tsc` and `eslint` clean, production build green across 7 routes.

Verified on the committed fixtures: net exposure (USD 19,469,510.12) → Credit Support
Amount USD 9,469,510.12 → Delivery Amount USD 9,500,000.00; optimiser USD 5,496.52
against a cash-first baseline of USD 23,002.41, a 76.10% saving across five assets with
four binding constraints; audit chain of 15 events — alternating agent decision and
engine computation — verifying and reproducing byte-identically across runs.

### Cut, as planned

F4 FX option and F11 dispute attribution. F4's absence is why vega is zero by
construction rather than by omission: there is no instrument in the book whose value
depends on a volatility, and the aggregation carries the term and reports zero with
that reason attached.

---

## Claims discipline

| Do not write | Write instead |
|---|---|
| "implements ISDA SIMM" | "BCBS-IOSCO schedule, plus a sensitivity aggregation using our own uncertified risk weights. Neither is SIMM" |
| "regulatory-compliant" | "designed against IFSCA / BCBS-IOSCO margin concepts" |
| "connects to SWIFT" | "generates ISO 20022 and MT527-shaped instructions; nothing is transmitted, no network exists" |
| "AI-calculated margin" | "AI-extracted terms, deterministically calculated margin" |
| "real-time market data" | "published data ingested once and pinned; no calculation reads a feed" |
| "zero errors" | "N golden cases and M invariants, all green; here is the eval score" |

All demo data is simulated and labelled as such in every fixture's `_provenance` block.
