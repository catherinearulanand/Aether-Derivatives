"""Settlement instruction generation — quantitative function F10.

Turns an approved collateral decision into the structured instruction a collateral
operations team would send, in the **shape** of the two ISO 20022 collateral
messages a margin call actually uses:

===================  ===========================================================
``colr.003``         MarginCallRequest — the call itself: what is owed, by whom,
                     under which agreement, for which value date.
``colr.005``         CollateralProposal — the assets proposed to satisfy it,
                     with their haircut valuations.
===================  ===========================================================

An MT527-shaped block is also produced, because a triparty collateral instruction is
still the form many custodians accept.

.. rubric:: What is and is not claimed

The instruction is **generated for real** from the deterministic allocation: every
line, quantity and valuation is the engine's output, and the totals reconcile to the
Delivery Amount. What does not exist is connectivity. Nothing is transmitted. No
SWIFT membership, BIC, network connection, service bureau or gpi tracker is involved
at any point. The XML produced here follows the element *shape* of the ISO 20022
messages and has **not** been validated against their XSDs; message identifiers,
account numbers and BICs are synthetic placeholders in the correct format.

Settlement is therefore **simulated**: the instruction is produced and recorded, and
the simulated ledger movement shows what would move if a human approved it and a
connected system sent it. That is the honest boundary, and it is stated on every
surface that renders one of these.

.. rubric:: Determinism

The instruction identifier is derived from the agreement, the value date and the
call amount by SHA-256 — never from a clock, a counter or a random UUID. Two
identical runs produce two identical instructions, which is what lets the settlement
message sit inside the reproducible audit chain.

Part of the deterministic core: no I/O, no clock, no framework dependency.
``hashlib`` is pure and permitted.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum
from xml.sax.saxutils import escape

from aether.core.csa import CallDirection, MarginCallResult
from aether.core.csa_terms import CSATerms, Party
from aether.core.money import Currency, Money
from aether.core.optimize import OptimizationResult

__all__ = [
    "SettlementInstruction",
    "SettlementLeg",
    "SettlementStatus",
    "build_settlement_instruction",
    "placeholder_account",
    "placeholder_bic",
    "to_iso20022_xml",
    "to_mt527",
]

#: Standard collateral settlement cycle. T+1 for a variation margin transfer.
SETTLEMENT_LAG_DAYS = 1


def placeholder_bic(party: Party) -> str:
    """A structurally valid eleven-character BIC that belongs to nobody.

    Functions rather than module dictionaries, because a module-level dict is shared
    mutable state and the deterministic core forbids it — a rule the purity test
    enforces on this file like every other.
    """
    return "AETHINBBXXX" if party is Party.PARTY_A else "MERIGB2LXXX"


def placeholder_account(party: Party) -> str:
    """A synthetic safekeeping account reference in the usual format."""
    return "SAFE-AETH-0001" if party is Party.PARTY_A else "SAFE-MERI-0001"


class SettlementStatus(StrEnum):
    """Where an instruction stands. There is no state beyond approval, because
    nothing downstream of approval exists."""

    GENERATED = "GENERATED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    NOT_REQUIRED = "NOT_REQUIRED"


@dataclass(frozen=True, slots=True)
class SettlementLeg:
    """One asset movement inside a collateral proposal."""

    sequence: int
    asset_id: str
    description: str
    asset_class: str
    currency: Currency
    market_value: Money
    valuation_percentage: Decimal
    collateral_value: Money
    safekeeping_account: str
    delivery_method: str = "DELIV"


@dataclass(frozen=True, slots=True)
class SettlementInstruction:
    """A generated, unsent collateral settlement instruction."""

    instruction_id: str
    agreement_id: str
    netting_set_id: str
    snapshot_id: str
    as_of: date
    value_date: date
    direction: CallDirection
    deliverer: str
    deliverer_bic: str
    receiver: str
    receiver_bic: str
    call_amount: Money
    collateral_value: Money
    legs: tuple[SettlementLeg, ...]
    status: SettlementStatus
    message_types: tuple[str, ...]
    engine_version: str
    simulated: bool = True

    @property
    def is_balanced(self) -> bool:
        """Does the proposed collateral cover the amount called?

        Post-haircut value must meet or exceed the Delivery Amount. It exceeds it
        whenever an asset is delivered in a lot that overshoots, which is normal.
        """
        return self.collateral_value.amount >= self.call_amount.amount

    @property
    def disclaimer(self) -> str:
        return (
            "SIMULATED SETTLEMENT. This instruction is generated from the "
            "deterministic allocation and is not transmitted anywhere. No SWIFT "
            "connectivity, network membership or gpi tracking exists in this system. "
            "The XML follows ISO 20022 message shape and is not schema-validated. "
            "BICs and account numbers are synthetic placeholders."
        )


def _instruction_id(agreement_id: str, value_date: date, amount: Money) -> str:
    """Deterministic identifier. No clock, no counter, no randomness."""
    material = f"{agreement_id}|{value_date.isoformat()}|{amount.amount}|{amount.currency.value}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:12].upper()
    return f"AETH-COLR-{digest}"


def build_settlement_instruction(
    terms: CSATerms,
    margin_call: MarginCallResult,
    allocation: OptimizationResult | None,
) -> SettlementInstruction | None:
    """Generate the settlement instruction for a margin call.

    Returns ``None`` when there is nothing to settle — no call, or a call gated by
    the Minimum Transfer Amount. A settlement message for a zero transfer would be
    noise, and generating one would misrepresent what the system decided.
    """
    if not margin_call.has_call:
        return None

    transferor = margin_call.transferor
    transferee = Party.PARTY_A if transferor is Party.PARTY_B else Party.PARTY_B

    # On a Return Amount, collateral flows back: the Transferee delivers.
    if margin_call.direction is CallDirection.RETURN:
        deliverer, receiver = transferee, transferor
    else:
        deliverer, receiver = transferor, transferee

    value_date = margin_call.as_of + timedelta(days=SETTLEMENT_LAG_DAYS)

    legs: list[SettlementLeg] = []
    collateral_value = Money.zero(margin_call.base_currency)

    if allocation is not None:
        for index, line in enumerate(allocation.lines, start=1):
            legs.append(
                SettlementLeg(
                    sequence=index,
                    asset_id=line.asset_id,
                    description=line.description,
                    asset_class=line.asset_class.value,
                    currency=line.currency,
                    market_value=line.market_value_posted,
                    valuation_percentage=line.effective_percentage,
                    collateral_value=line.effective_value,
                    safekeeping_account=placeholder_account(receiver),
                )
            )
            collateral_value = collateral_value + line.effective_value

    message_types: tuple[str, ...] = ("colr.003.001.05-shaped",)
    if legs:
        message_types = ("colr.003.001.05-shaped", "colr.005.001.05-shaped", "MT527-shaped")

    return SettlementInstruction(
        instruction_id=_instruction_id(terms.agreement_id, value_date, margin_call.call_amount),
        agreement_id=terms.agreement_id,
        netting_set_id=terms.netting_set_id,
        snapshot_id=margin_call.snapshot_id,
        as_of=margin_call.as_of,
        value_date=value_date,
        direction=margin_call.direction,
        deliverer=_name_of(terms, deliverer),
        deliverer_bic=placeholder_bic(deliverer),
        receiver=_name_of(terms, receiver),
        receiver_bic=placeholder_bic(receiver),
        call_amount=margin_call.call_amount,
        collateral_value=collateral_value,
        legs=tuple(legs),
        status=SettlementStatus.AWAITING_APPROVAL,
        message_types=message_types,
        engine_version=margin_call.engine_version,
    )


def _name_of(terms: CSATerms, party: Party) -> str:
    party_terms = terms.terms_for(party)
    return party_terms.legal_name or party.value.replace("_", " ").title()


def to_iso20022_xml(instruction: SettlementInstruction) -> str:
    """Render the instruction in ISO 20022 message shape.

    This is a faithful rendering of the element structure of ``colr.003``
    (MarginCallRequest) and ``colr.005`` (CollateralProposal). It is **not**
    schema-validated, carries a synthetic namespace marker, and is not transmissible.
    """
    lines: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!-- SIMULATED. ISO 20022 message shape, not schema-validated, not sent. -->",
        '<Document xmlns="urn:aether:simulated:colr.003.001.05">',
        "  <MrgnCallReq>",
        "    <MrgnCallReqId>",
        f"      <Id>{escape(instruction.instruction_id)}</Id>",
        f"      <CreDtTm>{instruction.as_of.isoformat()}T17:00:00+05:30</CreDtTm>",
        "    </MrgnCallReqId>",
        "    <Oblgtn>",
        f"      <AgrmtId>{escape(instruction.agreement_id)}</AgrmtId>",
        f"      <NetgSetId>{escape(instruction.netting_set_id)}</NetgSetId>",
        "      <PtyA>",
        f"        <Nm>{escape(instruction.deliverer)}</Nm>",
        f"        <AnyBIC>{instruction.deliverer_bic}</AnyBIC>",
        "      </PtyA>",
        "      <PtyB>",
        f"        <Nm>{escape(instruction.receiver)}</Nm>",
        f"        <AnyBIC>{instruction.receiver_bic}</AnyBIC>",
        "      </PtyB>",
        f"      <ValtnDt>{instruction.as_of.isoformat()}</ValtnDt>",
        "    </Oblgtn>",
        "    <MrgnCallRslt>",
        f'      <DlvrMrgnAmt Ccy="{instruction.call_amount.currency.value}">'
        f"{instruction.call_amount.amount}</DlvrMrgnAmt>",
        "    </MrgnCallRslt>",
        "  </MrgnCallReq>",
        "</Document>",
    ]

    if not instruction.legs:
        return "\n".join(lines)

    lines += [
        "",
        '<Document xmlns="urn:aether:simulated:colr.005.001.05">',
        "  <CollPrpsl>",
        f"    <TxId>{escape(instruction.instruction_id)}-PRPSL</TxId>",
        f"    <SttlmDt>{instruction.value_date.isoformat()}</SttlmDt>",
    ]
    for leg in instruction.legs:
        lines += [
            "    <CollPrpslDtls>",
            f"      <SeqNb>{leg.sequence}</SeqNb>",
            f"      <FinInstrmId>{escape(leg.asset_id)}</FinInstrmId>",
            f"      <Desc>{escape(leg.description)}</Desc>",
            f'      <MktVal Ccy="{leg.currency.value}">{leg.market_value.amount}</MktVal>',
            f"      <ValtnPctg>{leg.valuation_percentage}</ValtnPctg>",
            f'      <CollValAftrHrcut Ccy="{leg.collateral_value.currency.value}">'
            f"{leg.collateral_value.amount}</CollValAftrHrcut>",
            f"      <SfkpgAcct>{escape(leg.safekeeping_account)}</SfkpgAcct>",
            f"      <DlvryMtd>{leg.delivery_method}</DlvryMtd>",
            "    </CollPrpslDtls>",
        ]
    lines += [
        f'    <TtlCollVal Ccy="{instruction.collateral_value.currency.value}">'
        f"{instruction.collateral_value.amount}</TtlCollVal>",
        "  </CollPrpsl>",
        "</Document>",
    ]
    return "\n".join(lines)


def to_mt527(instruction: SettlementInstruction) -> str:
    """Render an MT527-shaped triparty collateral instruction.

    Field tags follow the MT527 layout. This is not a transmissible SWIFT message:
    there is no header block, no session, no network and no membership.
    """
    if not instruction.legs:
        return "// SIMULATED — no collateral legs to instruct."

    body: list[str] = [
        "// SIMULATED MT527-shaped block. Not a transmissible SWIFT message.",
        ":16R:GENL",
        f":20C::SEME//{instruction.instruction_id}",
        ":23G:NEWM",
        f":98A::EXRQ//{instruction.value_date.strftime('%Y%m%d')}",
        ":22H::COLA//SLEB",
        ":22H::REPR//PROV",
        ":16S:GENL",
        ":16R:COLLPRTY",
        f":95Q::PTYA//{instruction.deliverer}",
        f":95P::PTYB//{instruction.receiver_bic}",
        ":16S:COLLPRTY",
        ":16R:DEALTRAN",
        f":19A::TRAA//{instruction.call_amount.currency.value}{instruction.call_amount.amount}",
        ":16S:DEALTRAN",
    ]
    for leg in instruction.legs:
        body += [
            ":16R:SECMOVE",
            ":22H::COLM//DELI",
            f":35B:/XX/{leg.asset_id}",
            f":19A::PSTA//{leg.currency.value}{leg.market_value.amount}",
            f":92A::MARG//{leg.valuation_percentage}",
            ":16S:SECMOVE",
        ]
    return "\n".join(body)
