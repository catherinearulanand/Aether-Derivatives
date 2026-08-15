# AETHER — three-minute demo

**Before you start.** `AETHER_MODE=replay`, both servers up, browser on
`http://127.0.0.1:3000`, network irrelevant. Run `python scripts/run_pipeline.py` once
beforehand to confirm the slice is green.

The single most important sentence, if you only get one:

> **Language models extract. Deterministic engines compute.**

---

## 0:00 — 0:25 · The problem

> "A collateral desk gets a margin call. Someone reads a hundred-page Credit Support
> Annex to find the Threshold, the Minimum Transfer Amount, the eligible collateral and
> the haircuts. Someone else computes the exposure in a spreadsheet. A third person
> decides what to post — usually cash, because cash is easy. That process is slow, and
> the cash is the most expensive thing on the balance sheet to give away."

Open on **Margin Desk**, rate-shock scenario already loaded.

---

## 0:25 — 1:05 · Extraction, and the moment that matters

Go to **Document Review**.

> "The agent read the Annex and extracted twenty-one fields. Every one carries a citation
> — page, paragraph, and the verbatim quote. Click any field and the document scrolls
> to the clause it came from."

Click `rounding.increment`. The document highlights Paragraph 11(b)(iii)(D).

Then the point of the whole screen:

> "Now look at this one."

Point at `threshold.party_b` — confidence **0.52**, flagged `CONDITIONAL CLAUSE`.

> "Paragraph 11(b)(iii)(A) says the Threshold is five million dollars. But it says
> *subject to Paragraph 11(g)(ii)* — and that paragraph drops it to **zero** while a
> ratings downgrade is in effect. The document states the trigger. It cannot tell us
> whether the trigger is *currently* pulled. That is not a question a document can
> answer, so the agent doesn't guess — it stops and asks."

Try **Freeze agreement** first if you want the sharper version — the API returns 409.

> "And this isn't a disabled button. The server refuses. An unreviewed value physically
> cannot reach the margin engine."

**The moment that lands.** Switch to the **Flash crash** scenario on the Margin Desk
first and note the call: **USD 19,900,000**. Come back, click **Apply USD 0.00 instead**
with a rationale, and freeze. Return to the desk.

> "Nineteen point nine million became twenty-four point nine. Nothing about the market
> changed. A human decided that a ratings trigger was live, and the engine recomputed
> on the terms that human confirmed. That is the difference between recording a review
> and being governed by one."

The header now reads **reviewed terms** rather than the committed fixture.

---

## 1:05 — 1:45 · Deterministic margin

Back to **Margin Desk**. Point at the **Agent swarm** strip at the top.

> "Three agents. Legal-Clause hands over the terms. Risk-Engine routes the valuation
> and margin tools. Collateral-Optimizer decides whether anything needs selecting and
> runs the program. Look at the arguments column: every one is an identifier. None is
> a number — a tool call's arguments are typed to forbid it, so a hallucinated figure
> is rejected before anything executes."

> "From here on, no language model touches a number."

Walk the waterfall top to bottom:

> "Net exposure across eight trades in one netting set — and they net only within that
> netting set, because netting across Master Agreements would overstate the benefit.
> Nineteen point four million against us. Threshold of ten million comes off. Credit
> Support Amount: nine point four seven million."

Point at the **GATE** row.

> "Minimum Transfer Amount, five hundred thousand — tested on the *unrounded* amount,
> per Paragraph 3(b). Whether the MTA is tested before or after rounding is genuinely
> ambiguous across CSA vintages and is a real source of disputes. We support both, the
> agreement elects one, and we record which we applied."

Click any row.

> "Every line names the clause it came from."

Optional, if a judge looks sceptical — switch to **Quiet market**:

> "Same portfolio, calmer curve. Exposure sits inside the Threshold, so no call. The
> gates demonstrably gate."

---

## 1:45 — 2:35 · The commercial argument

Scroll to **Collateral optimisation**.

> "Nine and a half million has to be posted. The question is *what*."

> "A desk without an optimizer posts cash first. That costs twenty-three thousand
> dollars a year in funding. The linear program costs **five thousand five hundred** —
> seventy-six percent less, on this one call."

Point at the **cost per effective unit** column.

> "This is the column that matters. The Indian government bond has a nine basis point
> funding spread — cheaper than the eight basis point Treasury bill on paper. But it's
> in rupees, so it takes a ninety-four percent schedule valuation *and* an eight percent
> FX haircut. Eighty-six point four eight percent effective. Ten point four one basis
> points per unit of collateral actually delivered."

> "So the optimizer **declines it** — the bill covers the residual at eight point
> zero four. And look: it says so, with the number. That's the answer to 'why not that
> one', computed from the solved problem rather than guessed at."

Point at the EUR cash row on the cross-border panel.

> "Here's the cleanest version, and it needs no allocation at all. Euro cash is
> twenty-eight basis points. Dollar cash is thirty. Cheaper on paper — and *dearer*
> per unit delivered, thirty point four three against thirty point zero zero, because
> the euro takes the FX haircut. The two rank columns disagree. A desk ranking by
> funding spread reaches for the wrong one."

If a judge asks whether you sized the inventory to get that answer:

> "No — and we reverted a change that did. The rupee paper was in the allocation until
> we added gold, which displaced it. We briefly shrank a Treasury holding to bring it
> back, then took that out, because tuning an input after seeing the output is the one
> thing a reproducibility claim can't survive. What you're looking at is what the
> fixture produces."

Point at **shadow prices**.

> "These are the dual values from the solver. Four constraints bind. The corporate bond
> cap costs about five basis points at the margin, the gold cap three and a half. That
> is not a chart — that is what your own credit policy is costing you, computed."

Scroll one panel down to **Considered and not used**.

> "And every eligible asset it *didn't* use says why. Either a cap that applies to it is
> binding, or it costs more per unit of collateral actually delivered than everything
> that filled the requirement. An optimizer that can't answer 'why not that one' is a
> black box."

Point at the exclusion.

> "And this one is refused. It's the cheapest corporate bond in the inventory, and it is
> issued by the counterparty we'd be posting it to. Paragraph 11(g)(iv). Wrong-way risk.
> There's a test that fails the build if it ever gets allocated."

---

If you have thirty seconds spare, open **Settlement**.

> "The approved allocation renders as the two ISO 20022 messages a margin call actually
> uses — a call request and a collateral proposal — plus the MT527 block a custodian
> would accept. The legs reconcile to the Delivery Amount. And nothing is sent: there is
> no network here, no membership, no BIC. Generating a message and sending one are
> different capabilities and we have only the first."

---

## 2:35 — 3:00 · Proof

Scroll to the audit strip, or open **Audit Trail**.

> "Every stage is hash-chained — each event covers its own content plus the previous
> hash, so altering any record breaks everything after it. Tamper-evident. Deliberately
> not a blockchain; there's one writer and consensus would add nothing."

> "And because nothing in the engine reads a clock or a live feed, running this twice
> produces a byte-identical chain. There's a test that asserts exactly that."

Close on the decision banner:

> "The system proposes. It does not execute. Every decision is pending human approval,
> all the data is simulated, and the Methodology tab lists what we deliberately don't
> model — including that our initial margin is the public BCBS-IOSCO schedule, not ISDA
> SIMM."

---

## Questions you should hope for

**"Is this SIMM?"**
> No, and we're careful about that. SIMM is a licensed model with calibrated weights and
> a governed recalibration. We produce two figures. One is the public BCBS-IOSCO
> standardised schedule, exactly as published. The other is a genuine sensitivity
> aggregation — every curve pillar bumped, the book repriced, results risk-weighted and
> aggregated through correlation matrices — using *our own* documented weights,
> calibrated to nothing and certified by no one. The shape of the aggregation is public;
> the calibration is what's licensed, and we don't have it and don't claim it.

**"Why do the two initial margin numbers differ?"**
> The schedule applies a grid to notional. It cannot see that a book is partly hedged.
> Measured risk can, which is why the sensitivity figure comes in around eighty percent
> of the schedule number here. Neither is charged to the variation margin call — they sit
> under different agreements with different mechanics.

**"Do you actually connect to SWIFT?"**
> No. We generate the messages and never transmit them. No network, no membership, no
> BIC — the ones on screen are structurally valid placeholders that belong to nobody, and
> the XML isn't schema-validated. It's on the Methodology tab in those words.

**"Is the market data real?"**
> The demo runs on simulated snapshots, labelled as such in every fixture. There's also
> an ingestion script that pulls the US Treasury par yield curve and ECB reference rates
> and pins them as a snapshot with provenance. The distinction that matters: data is live
> at ingest and pinned at calculation. No calculation ever reads a feed, which is what
> keeps the audit hashes reproducible.

**"How do I know the AI didn't make a number up?"**
> It structurally can't. The model only emits typed fields with citations. Every
> arithmetic operation is a pure Python function with `Decimal` money, tested against
> analytically-derived expected values. The freeze gate refuses unreviewed input at the
> API layer. That's the architecture, not a policy.

**"What's your accuracy?"**
> Measured on the Methodology tab against hand-authored ground truth, weighted so a
> missed review flag counts triple — because confidently computing on an unconfirmed
> value is worse than an obvious error. Honest caveat: in replay mode the cached
> extraction is itself hand-authored, so that score demonstrates the harness. The live
> path exists and works.

**"Is the saving real?"**
> It's measured against a cash-first baseline implemented in the same codebase, on the
> same call, and there's a property test asserting the optimizer never loses to it. It
> is not extrapolated to an annual institution-wide figure, because that number would
> be made up.

**"What would you build next?"**
> Dispute attribution — decomposing a disagreement with a counterparty into valuation,
> FX, haircut and threshold components. It's specified in the architecture document and
> was cut for time, not for difficulty.

---

## If something breaks

- **Web shows "Cannot reach the AETHER API"** — the API isn't up. `PYTHONPATH=backend
  python -m uvicorn aether.api.main:app --port 8000`.
- **Anything looks wrong** — fall back to `python scripts/run_pipeline.py --scenario
  stress`. It prints the entire slice as text and needs no browser.
- **Never** switch to `AETHER_MODE=live` during a demo.
