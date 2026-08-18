# AETHER-DERIVATIVES — Speaker Notes

**GIFT IFIH Young Builders Program · IFSC**

`AETHER_DERIVATIVES_GIFT_CITY_HACKATHON_PITCH.pptx` — 13 slides.
Slides 1–11 are the idea, sourced from the Master Playbook. Slides 12–13 are the only
slides carrying screenshots, and every one is a capture of the running application.

---

## The three-minute cut

Present **1 · 2 · 3 · 8 · 9 · 12 · 13**. Hold 4–7, 10 and 11 for questions.
The two slides that win the room are **8 (the thesis)** and **9 (GIFT City)** — do not rush them.

| Slide | Cue |
|---|---|
| 1 | "An ISDA Credit Support Annex in; a defensible margin call and a cost-minimal allocation out." |
| 2 | "Margin calls are settled by people reading legal documents." |
| 3 | "Contract auditor, pit boss, treasury manager. Today those are three people." |
| 8 | "The expensive question isn't how much. It's what you deliver." |
| 9 | "We did not force a GIFT City asset into the allocation." |
| 12 | "This is the application running, not a mockup." |
| 13 | "When the contract is ambiguous, it stops." |

---

## The line to land

> **AI interprets. Deterministic engines calculate. Optimisation decides. Humans govern ambiguity.**

---

## Slide 01 · AETHER-DERIVATIVES

*Hero* · **0:00–0:15** · source: Playbook §1

OPENING (15s)
"AETHER-Derivatives. Autonomous margin and collateral intelligence for cross-border OTC
derivatives."

"One sentence: an ISDA Credit Support Annex goes in, and a defensible margin call, a
cost-minimal collateral allocation and a tamper-evident audit trail come out."

Point at the four bullets on the right — that's the whole product.

Say the honesty line early; it buys credibility for everything after:
"Everything you'll see runs on simulated data, and the system says so on every screen."

---

## Slide 02 · Margin calls are settled by people reading legal documents

*The problem* · **0:15–0:40** · source: Playbook §1, §2

THE PROBLEM (25s)
"Over-the-counter derivatives are a six-hundred-trillion-dollar notional market, and
they move on collateral."

"When volatility spikes, the desks that have to move that collateral spend four to six
hours recalculating variation margin — because the terms that drive the calculation are
buried in a two-hundred-page annex, the exposure gets rebuilt in a spreadsheet, and the
collateral decision is made by habit."

"Three costs. Late calls trigger default notices. The cash-first habit posts the most
expensive asset you own. And when it's disputed, there's no single record."

Be precise about attribution — a finance judge will notice:
"Those market figures are from our problem research, not something this prototype
measured."

KEY TAKEAWAY: the difficulty is the chain, not any single calculation.

---

## Slide 03 · Think of it as an automated escrow desk

*The idea, without the jargon* · **0:40–1:05** · source: Playbook §2

PLAIN ENGLISH (25s)
"If the jargon is getting in the way — think of it as an automated escrow desk."

"Three roles. The contract auditor reads the agreement and establishes the rules: what
counts as security, what minimum sizes apply, what safety margin comes off each asset."

"The pit boss watches the position and works out how much is owed right now."

"And the treasury manager looks across everything you own — cash, government bonds,
corporate paper, gold — and picks the cheapest combination the contract permits."

"Today those are three people in three systems. AETHER makes them one pipeline."

KEY TAKEAWAY: this is an operations problem before it is an AI problem.

---

## Slide 04 · A prompt wrapper cannot do this job

*Why this needs more than a chatbot* · **1:05–1:30** · source: Playbook §3

WHY NOT A CHATBOT (25s)
"The obvious question is why this needs agents at all."

"Three reasons, one per layer. On legal extraction, retrieval fails because the clauses
are nested — a Threshold qualified 'subject to' a ratings trigger sits in two paragraphs
that never appear together."

"On risk, language models hallucinate arithmetic. You cannot prompt that away. So our
agents never calculate — they invoke audited deterministic functions through a typed
boundary, and the engine returns every figure."

"On collateral, fixed rules can't weigh yields, haircuts, concentration caps and FX at
once. So the agent hands it to a solver."

THE LINE: "AI interprets. Deterministic engines calculate."

LIKELY Q: "So why not skip the AI entirely?"
A: "Because a rules engine needs structured inputs, and the interpretation step is
exactly what's missing. ISDA agreements are bespoke."

---

## Slide 05 · Three agents. One orchestrator. One auditable decision

*Architecture* · **1:30–1:55** · source: Playbook §2, §3

ARCHITECTURE (25s)
"Three agents under one orchestrator, and each one owns a stage."

"Legal-Clause interprets the contract and hands over structured terms. Risk-Engine turns
those terms plus the market into a margin requirement. Collateral-Optimizer decides what
to deliver against it."

"Read the middle column carefully: 'never performs arithmetic itself'. The agent chooses
which deterministic tool to invoke and with which references. The engine returns the
number."

"And the bar at the bottom is what makes that checkable — each agent's request and each
engine's result are recorded as separate events."

LIKELY Q: "What stops an agent inventing a number anyway?"
A: "The type of a tool call. Arguments are identifiers and flags only — a Decimal raises
at construction. I can show you the test."

---

## Slide 06 · One decision pipeline, from contract to collateral

*The workflow* · **1:55–2:20** · source: Playbook §2, §3

THE WORKFLOW (25s)
"This is the pipeline end to end. Document at the top, audit record at the bottom."

"Two things I'd point out. Third row down: human review. It only fires where the
contract is genuinely ambiguous — not on every field, which would defeat the purpose."

"And the box on the right is the rule the whole thing is built on: a contractual value
crosses from the model into the engine exactly once, through a validated schema,
carrying a quote from the source document. After that point no language model touches a
number."

"The lower right panel is what each stage leaves behind. That's the difference between a
demo and infrastructure — you can reconstruct the decision months later."

---

## Slide 07 · Four capabilities — and where each one stands today

*The product* · **2:20–2:45** · source: Playbook §4

THE PRODUCT (25s)
"Four capabilities, and I've put the status on each one rather than letting you assume."

"Legal parser: built. Native PDF and markdown. A scanned document with no text layer is
refused with a stated reason, not guessed at."

"Risk engine: built. Two initial margin methods — and neither is ISDA SIMM. The weights
are ours, uncertified, and the code says so four times over."

"Collateral optimisation: built. A real linear program, and it returns the shadow price
of every binding constraint."

"Settlement: partial. We generate the messages in ISO 20022 and MT527 shape. Nothing is
transmitted — no network, no membership, no BIC. Connectivity is roadmap and I'm not
going to claim otherwise."

KEY TAKEAWAY: the honest labelling is the point. Three built, one partial.

---

## Slide 08 · The expensive part of a margin call is what you deliver

*The commercial thesis* · **2:45–3:15** · source: Playbook §4.3

COLLATERAL THESIS (30s)
"Everyone focuses on how much is owed. The expensive question is what you deliver."

"The ranking that decides it is cost per effective unit — funding spread divided by
effective valuation percentage. An asset with a low headline spread and a heavy haircut
delivers less collateral per unit you encumber. That single ratio is the product."

"And it has to satisfy six constraints at once — eligibility, haircut, concentration,
wrong-way risk, inventory, FX. That's a solver's job, not a spreadsheet's."

"On one verified run: cash-first costs twenty-three thousand a year. Optimised costs
five and a half. Seventy-six percent lower."

SAY THE QUALIFIER, DON'T HIDE IT:
"Modelled, against a cash-first baseline, in one synthetic scenario. Not a guarantee."

"And the solver gives you something a spreadsheet never will — the shadow price of every
binding constraint. Your corporate bond cap is costing you 2.61 basis points. That's your
own credit policy, priced."

---

## Slide 09 · Cross-border collateral has to be priced, not assumed

*GIFT City · IFSC* · **3:15–3:45** · source: Playbook §1, §7

GIFT CITY (30s) — the slide that earns the venue
"An IFSC banking unit has a structural tension. It trades a dollar-based agreement, and
it funds rupee assets more cheaply at home. Those pull in opposite directions."

"AETHER resolves it by pricing it. Walk the ladder: nine basis points headline — cheaper
than the eight-point alternative. Ninety-four percent schedule valuation. Then a further
eight percent FX haircut because it isn't the base currency. Eighty-six point four eight
percent effective. Ten point four one basis points delivered."

"The Treasury bill delivers at eight point zero four. So the optimiser declines the
rupee asset."

THE LINE THAT LANDS — say it slowly:
"We did not force a GIFT City asset into the allocation because this is a GIFT City
hackathon. The system produced the inconvenient answer and we kept it."

"And the argument doesn't depend on that outcome. Same inventory: euro cash is
twenty-eight basis points on paper and thirty point four three delivered — dearer than
thirty-point-zero dollar cash. The FX haircut reverses the ranking. That's the thesis."

LIKELY Q: "So rupee collateral is never worth posting?"
A: "It's worth posting when delivered economics say so. Change the inventory or the caps
and it enters the allocation. What matters is that the decision is priced, not assumed."

---

## Slide 10 · Financial AI earns trust by refusing to guess

*Why this can be trusted* · **3:45–4:10** · source: Playbook §8

TRUST (25s)
"Three pillars, and then the part most decks leave out."

"Deterministic by construction — every figure is a pure function of contract terms and a
pinned snapshot. No clock, no live feed, no randomness. Same inputs, byte-identical
results."

"Human at the ambiguity — where a clause is conditional, the pipeline stops. And it's not
a greyed-out button; the server refuses to freeze while any field awaits a decision."

"Evidence for every step — extraction, confirmation, every engine call, chained by hash."

NOW THE BOTTOM HALF — slow down, this is the credibility moment:
"And here's what we deliberately do not claim. This isn't SIMM. We're not connected to
SWIFT. The market data is pinned, not live. The seventy-six percent is modelled, not
guaranteed. The accuracy score demonstrates the harness, not the model. And this is not
production-ready."

"We wrote that list before we wrote the pitch. It's served by the API, so the interface
can't drift from it."

KEY TAKEAWAY: financial AI becomes trustworthy when the system is willing to produce an
inconvenient answer.

---

## Slide 11 · From a verified prototype to institutional infrastructure

*Where this goes* · **4:10–4:35** · source: Playbook §6, §7

ROADMAP AND CLOSE (25s)
"Everything in the NOW column runs today, offline, on a laptop. NEXT is production
integration — live feeds, persistent state, authentication, custodian connectivity.
Those are engineering, not research. FUTURE is institutional scale."

"The honest line: the decision engine scales conceptually — the linear program doesn't
care whether the inventory has eleven assets or eleven hundred. The production
infrastructure is a separate layer and I'm not going to claim we've built it."

"Three reasons this matters. Financially meaningful — collateral selection is an
optimisation problem and we treat it as one. Technically defensible — deterministic
engines, a real solver, a reproducible audit chain. And GIFT City relevant, because
cross-border collateral is priced on delivered economics."

FINAL LINE:
"AETHER turns fragmented margin operations into one traceable decision pipeline."

Then: "Let me show you it running."

---

## Slide 12 · The calculation, running

*Working demo* · **4:35–5:00** · source: Live application

DEMO I — THE CALCULATION (25s)
"These are screenshots of the application running, not mockups."

"One — the margin waterfall. Exposure of nineteen point four seven million against us,
threshold of ten million comes off, credit support amount nine point four seven, and the
MTA gate and rounding give nine and a half million. Every line names the clause it came
from."

"Two — the optimiser. Five assets, ranked by cost per effective unit. Five thousand four
hundred against twenty-three thousand for cash-first."

"Three — and this is the one I'd linger on — cross-border economics. Every non-dollar
asset with its paper rank next to its delivered rank, and the FX drag isolated. The
rupee asset is priced at ten point four one and declined, with the reason on screen."

"Note the panel on the right: four binding constraints, and the wrong-way asset refused
outright — that's the counterparty's own paper, which the annex forbids."

---

## Slide 13 · The governance, running

*Working demo* · **5:00–5:25** · source: Live application

DEMO II — THE GOVERNANCE (25s)
"Four — the moment that matters most. Paragraph 11(b)(iii)(A) says Party B's threshold is
five million dollars. But it says it 'subject to' another paragraph, which drops the
threshold to zero while a ratings downgrade is in effect."

"The document defines the trigger. It cannot tell us whether the trigger is currently
pulled. That is not a question a document can answer — so the agent scores it at 0.52
confidence and stops. And this is not a disabled button: the server returns a 409."

"Five — the agent trace. Look at the arguments column. Every one is an identifier:
netting_set_id, snapshot_id, agreement_id. Never a number. A tool call rejects a monetary
value at construction, so a hallucinated figure cannot reach the engine."

"Six — the audit chain. Agent decision, engine computation, alternating, fifteen events,
verified."

CLOSE ON THE STRIP:
"Four hundred and six tests, byte-reproducible, and zero network calls. It runs on a
laptop with the wifi off."

---

## Figures you must not get wrong

| Figure | Value | Appears on |
|---|---|---|
| Net exposure | (USD 19,469,510.12) | 12 |
| Credit Support Amount | USD 9,469,510.12 | 12 |
| Delivery Amount | USD 9,500,000.00 | 12 |
| Cash-first baseline | USD 23,002.41 | 8, 12 |
| Optimised allocation | USD 5,496.52 | 8, 12 |
| Modelled reduction | USD 17,505.89 · 76.10% | 8, 12 |
| Binding constraints | 6.80 · 2.61 · 1.22 · 1.09 bp | 8, 12 |
| INR headline spread | 9 bp | 9 |
| INR effective valuation | 86.48% (94% × 92%) | 9 |
| INR delivered cost | 10.41 bp — **not selected** | 9, 12 |
| FX drag alone | 0.83 bp | 9, 12 |
| Cheapest alternative | 8.04 bp · US Treasury bill | 9 |
| EUR cash inversion | 28 bp paper → 30.43 bp delivered | 9 |
| Flagged field confidence | 0.52 (gate at 0.85) | 13 |
| Audit events | 15, verified | 13 |
| Tests | 406 | 13 |

---

## Words to use, and words to avoid

| Never say | Say instead |
|---|---|
| "we implement ISDA SIMM" | "BCBS-IOSCO schedule plus our own uncertified weights — neither is SIMM" |
| "we connect to SWIFT" | "we generate ISO 20022-shaped instructions; nothing is transmitted" |
| "76% savings" | "76.10% modelled reduction against a cash-first baseline in this scenario" |
| "real-time market data" | "pinned snapshots; published data is pinned before any calculation reads it" |
| "zero errors" | "406 tests, and the accuracy score demonstrates the harness" |
| "fully autonomous" | "autonomous to a proposal; a human approves before anything moves" |

---

## If a judge pushes

**"Why agents rather than a rules engine?"** A rules engine needs structured inputs. The
interpretation step is what's missing, and ISDA agreements are bespoke.

**"How do you stop hallucinated numbers?"** A tool call's arguments are typed
`str | int | bool | None`. A `Decimal` raises at construction. Enforced by type, asserted by test.

**"Is the market data real?"** The demo is simulated and labelled. Published data can be
ingested and pinned — but pinned *before* any calculation reads it.

**"Did you tune the fixture to get that result?"** A bill holding was reduced after seeing the
output. It was caught and reverted. The committed fixture is the original, and the rupee asset
is priced out on it. That history is the answer — it makes the result credible, not weaker.

**"Is this production-ready?"** No, and slide 11 says so. No authentication, no persistence,
no multi-tenancy. A deliberately scoped prototype.
