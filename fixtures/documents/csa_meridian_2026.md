<!--
  SIMULATED DATA — NOT A REAL INSTITUTIONAL DOCUMENT.

  _provenance:
    simulated: true
    authored: 2026-08-14
    document_id: CSA-MERIDIAN-2026
    basis: >
      Synthetic. Structure modelled on the 2016 ISDA Credit Support Annex for
      Variation Margin (English law, Transfer). Paragraphs 1-10 are summarised
      rather than reproduced; Paragraph 11 (Elections and Variables) is authored
      in full because it carries every value the Risk Engine consumes.
    counterparties: Fictional. Any resemblance to real institutions is coincidental.
    warning: >
      Not legal advice, not a template, and not suitable for any real transaction.
-->

[PAGE 1]

---

# CREDIT SUPPORT ANNEX

### for Variation Margin (VM)

**to the Schedule to the**

## ISDA MASTER AGREEMENT

dated as of **12 January 2026**

between

**AETHER CAPITAL MARKETS (IFSC) LIMITED**, an IFSC Banking Unit established under the
laws of India and licensed by the International Financial Services Centres Authority,
having its registered office at Unit 704, Signature Tower, GIFT SEZ, Gandhinagar,
Gujarat 382355, India

("**Party A**")

and

**MERIDIAN GLOBAL MARKETS PLC**, a company incorporated under the laws of England and
Wales, having its registered office at 18 Finsbury Circus, London EC2M 7EA, United
Kingdom

("**Party B**")

---

This Annex supplements, forms part of, and is subject to, the ISDA Master Agreement
referred to above. Capitalised terms used but not defined herein have the meanings
given to them in the ISDA Master Agreement.

**Governing law:** English law.
**Netting Set Identifier:** `NS-MERIDIAN-001`

---

[PAGE 2]

## Paragraph 1 — Interpretation

1(a) Terms defined in the ISDA Master Agreement have the same meaning in this Annex.

1(b) In the event of any inconsistency between the provisions of Paragraph 11 and the
other provisions of this Annex, **Paragraph 11 shall prevail**.

1(c) References to a party "Transferring" Eligible Credit Support are to that party in
its capacity as Transferor.

## Paragraph 2 — Credit Support Obligations

2(a) **Delivery Amount.** Subject to Paragraphs 3 and 4, upon a demand made by the
Transferee on or promptly following a Valuation Date, if the Delivery Amount for that
Valuation Date equals or exceeds the Transferor's Minimum Transfer Amount, the
Transferor will Transfer to the Transferee Eligible Credit Support having a Value as of
the date of Transfer at least equal to the applicable Delivery Amount.

The "**Delivery Amount**" applicable to the Transferor for any Valuation Date is the
amount by which:

  (i) the Credit Support Amount

exceeds

  (ii) the Value as of that Valuation Date of the Transferor's Credit Support Balance.

2(b) **Return Amount.** Subject to Paragraphs 3 and 4, upon a demand made by the
Transferor on or promptly following a Valuation Date, if the Return Amount for that
Valuation Date equals or exceeds the Transferor's Minimum Transfer Amount, the
Transferee will Transfer to the Transferor Equivalent Credit Support having a Value as
of the date of Transfer as close as practicable to the applicable Return Amount.

The "**Return Amount**" applicable to the Transferee for any Valuation Date is the
amount by which:

  (i) the Value as of that Valuation Date of the Transferor's Credit Support Balance

exceeds

  (ii) the Credit Support Amount.

2(c) **Credit Support Amount.** The "**Credit Support Amount**" applicable to the
Transferor for any Valuation Date means:

> the greater of (i) zero and (ii) the sum of the Transferor's Independent Amount and
> the Transferee's Exposure, less the Transferor's Threshold.

---

[PAGE 3]

## Paragraph 3 — Transfers, Calculations and Exchanges

3(a) **Calculations.** All calculations of Value and Exposure for the purposes of
Paragraphs 2 and 4 will be made by the Valuation Agent as of the relevant Valuation
Time. The Valuation Agent will notify each party of its calculations not later than the
Notification Time on the Local Business Day following the applicable Valuation Date.

3(b) **Rounding.** The Delivery Amount and the Return Amount will be rounded in
accordance with Paragraph 11(b)(iii)(D). **For the avoidance of doubt, the Minimum
Transfer Amount test in Paragraphs 2(a) and 2(b) is applied to the unrounded amount,
and rounding is applied only after that test has been satisfied.**

## Paragraph 4 — Dispute Resolution

4(a) If a party disputes (i) the Valuation Agent's calculation of a Delivery Amount or
a Return Amount or (ii) the Value of any Transfer of Eligible Credit Support, then that
party will notify the other party not later than the close of business on the Local
Business Day following the date on which notification was given under Paragraph 3(a).

4(b) The party required to Transfer will nonetheless Transfer **the undisputed amount**
not later than the close of business on the Local Business Day on which the notice of
dispute is given, and the parties will thereafter consult in good faith to resolve the
dispute.

4(c) If the parties fail to resolve the dispute by the Resolution Time, the Valuation
Agent will recalculate the disputed item by seeking four mid-market quotations from
Reference Market-makers and taking the arithmetic mean.

## Paragraphs 5 to 10

Paragraphs 5 (Transfer of Title), 6 (Distributions and Interest Amount), 7 (Events of
Default), 8 (Certain Rights and Remedies), 9 (Representations) and 10 (Expenses) are
incorporated in the standard form published by the International Swaps and Derivatives
Association, Inc. and are not varied except as set out in Paragraph 11.

---

[PAGE 4]

# Paragraph 11 — Elections and Variables

## 11(a) Base Currency and Eligible Currency

**11(a)(i) "Base Currency"** means **United States Dollars (USD)**.

**11(a)(ii) "Eligible Currency"** means the Base Currency, the **Euro (EUR)** and the
**Indian Rupee (INR)**.

## 11(b) Credit Support Obligations

**11(b)(i) "Eligible Credit Support (VM)."** The following items will qualify as
"Eligible Credit Support (VM)" for the party specified, subject to Paragraph 11(g):

| Ref | Item | Valuation Percentage |
|-----|------|----------------------|
| (A) | Cash in the Base Currency | **100%** |
| (B) | Cash in any Eligible Currency other than the Base Currency | **100%** |
| (C) | Negotiable debt obligations issued by the US Treasury having a remaining maturity of **not more than one year** | **99.5%** |
| (D) | Negotiable debt obligations issued by the US Treasury having a remaining maturity of **more than one year but not more than five years** | **98.0%** |
| (E) | Negotiable debt obligations issued by the US Treasury having a remaining maturity of **more than five years but not more than ten years** | **96.0%** |
| (F) | Negotiable debt obligations issued by the Federal Republic of Germany having a remaining maturity of **not more than ten years** | **97.0%** |
| (G) | Dated securities issued by the Government of India having a remaining maturity of **not more than ten years** | **94.0%** |
| (H) | Corporate debt obligations rated **AA- or above** by Standard & Poor's having a remaining maturity of **not more than five years** | **92.0%** |
| (I) | Equity securities constituting a component of a Main Index | **85.0%** |
| (J) | **Allocated gold bullion** held in an LBMA Good Delivery vault, valued at the LBMA PM auction price | **88.0%** |

For the purposes of the table above, "Main Index" means the S&P 500 Index, the EURO
STOXX 50 Index or the NIFTY 50 Index.

Gold bullion Transferred under item (J) must be held in allocated form. Unallocated
bullion, gold-linked notes and exchange-traded products referencing gold do not
qualify.

**11(b)(ii) "Independent Amount"** means, with respect to:

  - **Party A:** zero.
  - **Party B:** **USD 2,000,000**.

---

[PAGE 5]

**11(b)(iii) Thresholds.**

  **(A) "Threshold"** means, with respect to:

  - **Party A:** **USD 10,000,000**.
  - **Party B:** **USD 5,000,000**, subject to Paragraph 11(g)(ii).

  **(B) "Minimum Transfer Amount"** means, with respect to Party A and Party B,
  **USD 500,000**.

  **(C) "Independent Amount"** is as specified in Paragraph 11(b)(ii).

  **(D) "Rounding."** The Delivery Amount will be rounded **up** and the Return Amount
  will be rounded **down**, in each case to the nearest integral multiple of
  **USD 100,000**.

## 11(c) Valuation and Timing

**11(c)(i) "Valuation Agent"** means **Party A**, save that following an Event of
Default with respect to Party A, the Valuation Agent will be Party B.

**11(c)(ii) "Valuation Date"** means each Local Business Day.

**11(c)(iii) "Valuation Time"** means **5:00 p.m., GIFT City time (IST)**, on the Local
Business Day immediately preceding the Valuation Date.

**11(c)(iv) "Notification Time"** means **1:00 p.m., London time**, on a Local Business
Day.

**11(c)(v) "Resolution Time"** means 1:00 p.m., London time, on the Local Business Day
following the date on which notice of a dispute is given under Paragraph 4.

## 11(d) Exchange Date

"**Exchange Date**" means, with respect to a substitution of Eligible Credit Support,
the Local Business Day following the date on which notice of substitution is given,
provided that the Transferee has consented to the substitution.

---

[PAGE 6]

## 11(e) Distributions and Interest Amount

**11(e)(i) "Interest Rate"** means, with respect to cash Transferred as Eligible Credit
Support:

  - in **USD**: the Secured Overnight Financing Rate (**SOFR**) **minus 10 basis
    points**;
  - in **EUR**: the Euro Short-Term Rate (**€STR**) **minus 10 basis points**;
  - in **INR**: the Mumbai Interbank Outright Rate (**MIBOR**) **minus 25 basis
    points**.

**11(e)(ii) "Interest Period"** means each calendar month.

**11(e)(iii) Interest Amount.** The Interest Amount will be Transferred on the second
Local Business Day following the end of each Interest Period, and will be subject to
the Minimum Transfer Amount only where the parties so agree in writing.

## 11(f) Addresses for Transfers

Transfers to Party A shall be made to its account at the custodian notified in writing
from time to time. Transfers to Party B shall be made to its account at Euroclear Bank
SA/NV, account number notified separately.

## 11(g) Other Provisions

**11(g)(i) Additional Valuation Percentage — currency mismatch.**

Where the currency of an item of Eligible Credit Support (VM) is **not** the Base
Currency, the Valuation Percentage otherwise applicable to that item under Paragraph
11(b)(i) shall be **further reduced by 8%** (an "FX Haircut"), applied multiplicatively.

> *Illustration.* An item with a Valuation Percentage of 94% denominated in INR has an
> effective Valuation Percentage of 94% × 92% = **86.48%**.

---

[PAGE 7]

**11(g)(ii) Ratings-contingent Threshold.**

Notwithstanding Paragraph 11(b)(iii)(A), if at any time the long-term senior unsecured
debt rating of Party B is **downgraded below A- by Standard & Poor's** or **below A3 by
Moody's Investors Service** (a "**Ratings Event**"), then for so long as such Ratings
Event is continuing the **Threshold with respect to Party B shall be zero**.

Party B shall notify Party A of the occurrence of a Ratings Event not later than the
Notification Time on the Local Business Day following the date on which it occurs.

**11(g)(iii) Concentration limits.**

No item of Eligible Credit Support (VM) shall be included in the Credit Support Balance
to the extent that its inclusion would cause:

  (A) the aggregate Value of items issued by a **single issuer other than a sovereign
      issuer** to exceed **25%** of the Value of the Credit Support Balance;

  (B) the aggregate Value of items falling within Paragraph 11(b)(i)(H) (corporate debt)
      to exceed **30%** of the Value of the Credit Support Balance; or

  (C) the aggregate Value of items falling within Paragraph 11(b)(i)(I) (equity
      securities) to exceed **20%** of the Value of the Credit Support Balance; or

  (D) the aggregate Value of items falling within Paragraph 11(b)(i)(J) (gold bullion)
      to exceed **15%** of the Value of the Credit Support Balance.

**11(g)(iv) Wrong-way collateral.**

No party may Transfer as Eligible Credit Support (VM) any security issued by that party,
by an Affiliate of that party, or by any entity whose creditworthiness is materially
correlated with that of the Transferor.

**11(g)(v) Substitution.**

The Transferor may substitute Eligible Credit Support on any Local Business Day, subject
to the consent of the Transferee, such consent not to be unreasonably withheld.

---

[PAGE 8]

**11(g)(vi) Legally ineligible credit support.**

Paragraph 11(g) of the standard form (Legally Ineligible Credit Support (VM)) applies.

**11(g)(vii) Regulatory basis.**

This Annex is entered into for the purpose of compliance by the parties with applicable
variation margin requirements. Nothing in this Annex constitutes a determination by
either party as to the regulatory treatment of any Transaction.

---

**IN WITNESS WHEREOF** the parties have executed this Annex on the date first above
written.

|  |  |
|---|---|
| **AETHER CAPITAL MARKETS (IFSC) LIMITED** | **MERIDIAN GLOBAL MARKETS PLC** |
| By: ......................................... | By: ......................................... |
| Name: R. Venkataraman | Name: H. Ashworth |
| Title: Head of Treasury | Title: Managing Director, Collateral |
| Date: 12 January 2026 | Date: 12 January 2026 |

---

*END OF DOCUMENT — SIMULATED. Not a real agreement.*
