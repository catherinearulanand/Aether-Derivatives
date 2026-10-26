# AETHER

**Autonomous Margin & Collateral Intelligence** -- a working prototype for the GIFT IFIH
Young Builders Program.

An ISDA Credit Support Annex goes in. A cited, reviewed, deterministically-calculated
margin call and an optimised collateral allocation come out, with a tamper-evident
audit trail behind every figure.

```
CSA document (markdown or native PDF)
  → Legal-Clause Agent          typed, cited, confidence-scored terms
  → human confirmation          the reviewer's decision governs the calculation
  → frozen Agreement
  → Risk-Engine Agent           exposure · sensitivities · credit support amount
  → Collateral-Optimizer Agent  cheapest-to-deliver LP · settlement instruction
  → decision                    proposal only, pending human approval
  → hash-chained audit trail    agent, human and engine events in one chain
```

Three agents orchestrate. Each chooses which deterministic tool to call and with which
identifiers. **None of them can pass a number** — a tool call's arguments admit strings,
integers, booleans and null, and a `Decimal` is rejected at construction.

> **All data in this system is simulated.** Market curves, counterparties, the
> derivatives book, the collateral inventory and the Credit Support Annex are synthetic
> and were authored for this prototype. No transaction is executed, no regulatory
> approval is claimed, and no market infrastructure is connected.

---

## The core principle

> ### Language models extract. Deterministic engines compute.

A language model reads the Annex and produces *typed, cited, confidence-scored fields*.
It never produces a margin number. Every contractual value crosses into the calculation
engine exactly once — through a validated schema, carrying a quote from the source
document, past a human confirmation when confidence is low.

That gate is **structural, not procedural**. `freeze_terms()` raises `ReviewRequired`
while any field awaits a decision, and the API returns `409` rather than computing. An
unreviewed model value physically cannot reach the margin engine.

```python
extraction = extract_terms("CSA-MERIDIAN-2026")
freeze_terms(extraction, ...)          # ReviewRequired: threshold.party_b
confirmed = confirm_field(extraction, "threshold.party_b", reviewer, rationale)
terms = freeze_terms(confirmed, ...)   # now permitted
```

---

## Run it

Requires Python 3.12+ and Node 20+. Runs **fully offline** — no API key, no network.

```bash
pip install -e ".[dev]"
cd frontend && npm install && cd ..

python scripts/verify_env.py                  # environment gate
powershell -ExecutionPolicy Bypass -File scripts/dev.ps1
```

Optional, and never on the demo path:

```bash
python scripts/build_csa_pdf.py               # render the CSA to a native PDF
python scripts/fetch_snapshot.py --dry-run    # ingest real published market data

pip install -e ".[data]"                      # faker + pandas, generation only
python scripts/generate_reconciliation_data.py  # rebuild the reconciliation dataset
```

Or start the two processes yourself:

```bash
PYTHONPATH=backend python -m uvicorn aether.api.main:app --port 8000
cd frontend && npm run dev -- --port 3000
```

| | |
|---|---|
| Web | http://127.0.0.1:3000 |
| API docs | http://127.0.0.1:8000/docs |

Headless, no browser needed:

```bash
python scripts/run_pipeline.py --scenario stress     # base | stress | crash
python scripts/run_pipeline.py --verify-determinism
```

---

## What it computes

| # | Function | Notes |
|---|---|---|
| F1 | Discount curves | Log-linear on discount factors, ACT/365F, single-curve |
| F2 | Interest rate swaps | Telescoped floating leg — exact under single-curve |
| F3 | FX forwards | Covered interest parity |
| F5 | Netting-set exposure | Cross-Master netting **structurally prevented** |
| F6 | Credit Support Amount | MTA gate, directional rounding, both MTA conventions |
| F7 | Schedule initial margin | BCBS-IOSCO standardised grid — **not ISDA SIMM** |
| F13 | Sensitivity margin | Bucketed delta by full revaluation, risk-weighted, correlated aggregation — **also not SIMM** |
| F8 | Haircuts & eligibility | Asset + FX haircut, wrong-way exclusion |
| F9 | Collateral optimisation | Linear program with duals and rejection reasons |
| F10 | Settlement instruction | ISO 20022 (`colr.003` / `colr.005`) and MT527 **message shape**, generated and never sent |
| F12 | Audit chain | SHA-256, canonical JSON, tamper-evident, spans agent → human → engine |

### The calculation the product exists to get right

```
CreditSupportAmount = max(0, IA + max(0, Exposure) − Threshold)
DeliveryAmount      = CreditSupportAmount − PostedValue
gate                |Amount| < MTA → no transfer     ← tested on the UNROUNDED amount
round               ROUND_UP for delivery, ROUND_DOWN for return
```

Whether the MTA is tested before or after rounding is genuinely ambiguous across CSA
vintages and is a real source of collateral disputes. Both conventions are supported,
the agreement elects one, and **the trace records which was applied**.

### Why the cheapest asset is not always chosen

The ranking that decides the allocation is **cost per effective unit**:

```
cost_per_effective_unit = funding_spread_bps ÷ effective_valuation_percentage
```

Indian government paper at a 9bp funding spread and an 86.48% effective valuation
(94% schedule × 8% FX haircut) costs 10.41bp per unit of collateral actually delivered.
A desk ranking by headline spread would reach for it ahead of a 98%-valued Treasury and
be wrong.

On the committed fixture the optimiser **evaluates the rupee paper and declines it**,
because the Treasury bill covers the residual at 8.04bp. That is the honest result and
the screen reports it with the reason attached. The cross-border argument does not
depend on the asset being posted — it is carried by the ranking, which is computed for
every eligible asset either way. The cleanest instance needs no allocation at all:

```
cash EUR   28bp headline ÷ 0.9200 effective = 30.43bp delivered   ← rank 10 → 11
cash USD   30bp headline ÷ 1.0000 effective = 30.00bp delivered   ← rank 11 → 10
```

The asset that is cheaper on the headline number is dearer per unit of collateral
actually delivered. This is where the GIFT City relevance lives — argued through
economics rather than asserted through branding, and **not** arranged by sizing the
inventory to produce a preferred answer.

---

## Verified results

Against the committed fixtures, on the designed rate shock:

| | |
|---|---:|
| Net exposure (8 trades, 1 netting set) | (USD 19,469,510.12) |
| Credit Support Amount | USD 9,469,510.12 |
| **Delivery Amount** (after MTA + rounding) | **USD 9,500,000.00** |
| Sensitivity margin (indicative) | USD 9,654,138.38 |
| Schedule initial margin (indicative) | USD 11,851,840.00 |
| Optimised funding cost | USD 5,496.52 |
| Cash-first baseline | USD 23,002.41 |
| **Saving** | **USD 17,505.89 (76.10%)** |
| Binding constraints | coverage 6.80bp · corporate 2.61bp · gold 1.22bp · issuer 1.09bp |
| Full pipeline, wall clock | ~90 ms |

Three scenarios, each proving something different:

| Scenario | What it demonstrates |
|---|---|
| **Quiet market** | Exposure of (USD 1,503,419.51) sits inside the USD 10m Threshold. **No call.** The gates demonstrably gate. |
| **Rate shock** | We owe. Five assets selected, four caps binding, the wrong-way asset refused. The INR G-Sec is **considered and priced out** at 10.41bp against 8.04bp — and the screen says so, with the number. |
| **Flash crash** | The book moves into the money, so **Party B** owes and Party B's ratings-contingent Threshold governs. Confirming the Ratings Event in Document Review moves the call from **USD 19,900,000 to USD 24,900,000** — the reviewer's decision changing the number. |

---

## Tests

```bash
pytest backend/tests                      # everything
pytest backend/tests -m slice             # the demo path, end to end
pytest backend/tests -m golden            # analytically-derived reference cases
pytest backend/tests -m property          # invariants over generated inputs
pytest backend/tests -m determinism       # byte-identical reproducibility
```

Golden expected values are derived **analytically**, before the implementation: a flat
curve discounts at `exp(-rt)`; a swap struck at its own par rate is worth zero; a
forward struck at the market forward is worth zero. A golden test whose expected value
came from running the code proves only that the code is deterministic.

Three tests carry more weight than the rest:

- **`test_optimizer_never_loses_to_the_baseline`** — the product's central commercial
  claim, asserted over generated inputs. If the LP ever costs more than cash-first,
  the claim is false.
- **`test_two_runs_produce_identical_audit_hashes`** — this test *is* the
  reproducibility claim. Without it, "reproducible" is marketing.
- **`test_freezing_is_blocked_while_a_field_awaits_review`** — the mechanical
  enforcement of the core principle.
- **`test_rejects_anything_that_is_not_a_reference`** — the agent boundary as a type.
  If a `Decimal` can reach a tool call, "language models never produce a number" is
  false and the architecture is decoration.

`backend/tests/unit/test_core_purity.py` parses every module under `aether/core/` and
fails the build on a forbidden import, an implicit clock, or module-level mutable
state. The deterministic-core rule is enforced by CI, not by discipline.

Two claims live in the frontend and are checked there, against the modules the
application actually imports rather than against a copy:

```bash
node scripts/verify_assistant.mjs        # needs the API up on :8000
node scripts/verify_reconciliation.mjs
```

- **`verify_assistant.mjs`** asserts that every monetary figure the assistant returns
  is character-for-character a string the engine put in the same response the screens
  render — not "close to", the same string. It also checks that an unsupported
  question returns `UNKNOWN` rather than a confident paragraph. If the assistant could
  disagree with the dashboard, the product's central claim would be unfalsifiable.
- **`verify_reconciliation.mjs`** scores the reconciliation classifier against
  `fixtures/reconciliation/injection_manifest.json`, the answer key the generator
  writes. Missed breaks and false positives are both measured. A within-tolerance
  price wobble raised as a break counts as a false positive, not a catch.

---

## Layout

```
backend/aether/core/      PURE. no I/O, no network, no clock, no ORM, no LLM.
backend/aether/agents/    LLM boundary: schema, prompt, replay, review gate, eval, swarm.
backend/aether/api/       Thin FastAPI routers. No business logic.
backend/aether/pipeline.py  Orchestration.
frontend/                 Next.js 16, App Router, TypeScript strict.
fixtures/                 Simulated data. Every file carries a provenance block.
fixtures/reconciliation/  Generated ledger pair + the injected-break answer key.
scripts/                  verify_env · run_pipeline · dev · build_docs_pdf
                          generate_reconciliation_data · verify_assistant · verify_reconciliation
docs/                     Architecture, test strategy, demo script.
```

Money is `Decimal` at every monetary boundary and crosses the API as a **decimal
string**, never a JSON number — a nine-figure notional would silently lose cents
through a JavaScript double.

---

## Modes

| Mode | Behaviour |
|---|---|
| `replay` *(default)* | Extraction served from a cached fixture. No network, no key, byte-identical. **This is the demo path.** |
| `live` | Real model call, `temperature=0`, pinned model id, versioned prompt. Optional. |

Market data has its own boundary. `scripts/fetch_snapshot.py` ingests **real published
end-of-day data** — the US Treasury par yield curve and ECB reference rates — and pins
it as a snapshot fixture with full provenance. The engine then reads that file exactly
as it reads a simulated one. Data is live *at ingest* and pinned *at calculation*: no
calculation ever reads a live feed, so determinism is unaffected.

Live connectivity is supported but the demo never depends on it. On the build machine
outbound TLS is intercepted by antivirus software; `truststore` resolves it against the
Windows trust store, and `scripts/verify_env.py` diagnoses the situation either way.

---

## What this deliberately does not do

Each is a defensible answer to "why not?", which is why it is written down.

- **ISDA SIMM** — two initial margin figures are produced: the public BCBS-IOSCO
  standardised schedule, and a sensitivity-based margin using AETHER's own documented
  risk weights and correlations. The second shares the *shape* of a risk-weighted
  aggregation, which is public. Nothing here is SIMM, SIMM-certified or
  SIMM-equivalent, and the weights are calibrated to nothing.
- **CVA / XVA / Monte Carlo PFE** — a product of its own; nothing in the collateral
  story needs it.
- **Blockchain** — the hash chain is tamper-evident, which is the honest claim for a
  single-writer audit log. Distributed consensus would add nothing.
- **Vector DB / RAG** — the document is bounded and small; full-document extraction is
  more accurate and removes a whole failure class.
- **A chatbot** — free-form chat invites exactly the ungrounded numeric answers the
  architecture exists to prevent.
- **SWIFT / tri-party / custodian connectivity** — settlement *instructions* are
  generated in ISO 20022 and MT527 message shape, reconcile to the Delivery Amount,
  and are never transmitted. No network, no membership, no BIC. The generated XML is
  not schema-validated.
- **Auth, RBAC, multi-tenancy, production infrastructure.**
- **Scanned-document OCR** — native PDFs are read through their text layer; a scanned
  image is refused with a stated reason rather than guessed at.
- **OIS/IBOR basis, business-day calendars.**

## Language discipline

| Never write | Write instead |
|---|---|
| "implements ISDA SIMM" | "BCBS-IOSCO standardised schedule, plus a risk-weighted sensitivity aggregation using AETHER's own uncertified weights. Neither is SIMM." |
| "regulatory-compliant" | "designed against IFSCA / BCBS-IOSCO margin concepts" |
| "connects to SWIFT" | "generates ISO 20022-shaped instructions; nothing is transmitted" |
| "AI-calculated margin" | "AI-extracted terms, deterministically calculated margin" |
| "real-time market data" | "published data ingested once and pinned; calculations never read a feed" |
| "zero errors" | the test count and the measured eval score |
| "fully autonomous" | "autonomous to a proposal; a human approves before anything moves" |

Every honest version is more persuasive to an informed audience than the overclaim, and
one checkable overclaim loses a technical judge permanently.

---

## Documents

- [`docs/architecture.md`](docs/architecture.md) — design and decision log
- [`docs/test-strategy.md`](docs/test-strategy.md) — what is tested and what is not
- [`docs/demo-script.md`](docs/demo-script.md) — the three-minute run
- [`docs/pdf/`](docs/pdf/) — print-ready versions
