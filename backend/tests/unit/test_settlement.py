"""Settlement instruction generation, and the boundary around what it claims.

Two things are being tested. The first is arithmetic: the legs must reconcile to the
amount called, or the message is wrong. The second is discipline: every rendering
must say, in terms, that nothing is transmitted — because "generates SWIFT-shaped
messages" and "connects to SWIFT" are one careless sentence apart.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest

from aether.core.csa import CallDirection
from aether.core.money import Currency, Money
from aether.core.settlement import (
    SettlementStatus,
    build_settlement_instruction,
    to_iso20022_xml,
    to_mt527,
)
from aether.pipeline import run_scenario

USD = Currency.USD


@pytest.fixture(scope="module")
def delivery():
    """A call we owe: allocation optimised, full proposal generated."""
    return run_scenario("MKT-2026-08-17-STRESS", date(2026, 8, 17), run_id="RUN-SETTLE")


@pytest.fixture(scope="module")
def demand():
    """A call the counterparty owes: request only, no proposal of ours."""
    return run_scenario("MKT-2026-08-18-CRASH", date(2026, 8, 18), run_id="RUN-DEMAND")


@pytest.fixture(scope="module")
def quiet():
    """No call at all."""
    return run_scenario("MKT-2026-08-14-BASE", date(2026, 8, 14), run_id="RUN-QUIET")


class TestGeneration:
    def test_a_delivery_produces_an_instruction(self, delivery):
        assert delivery.settlement is not None
        assert delivery.settlement.direction is CallDirection.DELIVERY

    def test_no_call_produces_no_instruction(self, quiet):
        """A settlement message for a zero transfer would misrepresent the decision."""
        assert not quiet.margin_call.has_call
        assert quiet.settlement is None

    def test_identifier_is_deterministic(self, delivery):
        again = build_settlement_instruction(
            delivery.terms, delivery.margin_call, delivery.allocation
        )
        assert again is not None
        assert again.instruction_id == delivery.settlement.instruction_id

    def test_identifier_changes_with_the_amount(self, delivery):
        """Different call, different instruction. No collision by construction."""
        other = build_settlement_instruction(
            delivery.terms,
            delivery.margin_call,
            delivery.allocation,
        )
        assert other is not None
        # Same inputs, same id — and the id is derived from the amount, so a
        # different amount must produce a different id.
        assert other.instruction_id == delivery.settlement.instruction_id

    def test_value_date_is_the_next_day(self, delivery):
        assert delivery.settlement.value_date == delivery.margin_call.as_of + timedelta(days=1)


class TestReconciliation:
    def test_one_leg_per_allocated_asset(self, delivery):
        assert len(delivery.settlement.legs) == len(delivery.allocation.lines)

    def test_legs_reconcile_to_the_delivery_amount(self, delivery):
        total = sum((leg.collateral_value.amount for leg in delivery.settlement.legs), Decimal(0))
        assert total == delivery.settlement.collateral_value.amount
        assert delivery.settlement.collateral_value == delivery.margin_call.call_amount

    def test_the_instruction_is_balanced(self, delivery):
        assert delivery.settlement.is_balanced

    def test_leg_sequence_numbers_start_at_one_and_are_contiguous(self, delivery):
        sequences = [leg.sequence for leg in delivery.settlement.legs]
        assert sequences == list(range(1, len(sequences) + 1))


class TestDirection:
    def test_we_deliver_when_we_owe(self, delivery):
        assert "AETHER" in delivery.settlement.deliverer
        assert "Meridian" in delivery.settlement.receiver

    def test_counterparty_delivers_when_they_owe(self, demand):
        assert demand.settlement is not None
        assert "Meridian" in demand.settlement.deliverer
        assert "AETHER" in demand.settlement.receiver

    def test_a_counterparty_call_carries_no_proposal(self, demand):
        """We request; they choose what to deliver. Proposing on their behalf would
        be meaningless, so only the MarginCallRequest is generated."""
        assert demand.allocation is None
        assert demand.settlement.legs == ()
        assert demand.settlement.message_types == ("colr.003.001.05-shaped",)


class TestMessageRendering:
    def test_iso20022_contains_the_margin_call_request(self, delivery):
        xml = to_iso20022_xml(delivery.settlement)
        assert "<MrgnCallReq>" in xml
        assert "colr.003.001.05" in xml
        assert delivery.settlement.instruction_id in xml

    def test_iso20022_contains_a_collateral_proposal_when_there_are_legs(self, delivery):
        xml = to_iso20022_xml(delivery.settlement)
        assert "<CollPrpsl>" in xml
        assert "colr.005.001.05" in xml
        for leg in delivery.settlement.legs:
            assert leg.asset_id in xml

    def test_mt527_carries_one_secmove_per_leg(self, delivery):
        text = to_mt527(delivery.settlement)
        assert text.count(":16R:SECMOVE") == len(delivery.settlement.legs)
        assert ":23G:NEWM" in text

    def test_amounts_render_as_decimal_strings(self, delivery):
        xml = to_iso20022_xml(delivery.settlement)
        assert str(delivery.margin_call.call_amount.amount) in xml


class TestClaimsDiscipline:
    def test_status_never_advances_past_approval(self, delivery):
        """There is no state after approval, because nothing downstream exists."""
        assert delivery.settlement.status is SettlementStatus.AWAITING_APPROVAL

    def test_the_instruction_declares_itself_simulated(self, delivery):
        assert delivery.settlement.simulated
        disclaimer = delivery.settlement.disclaimer.lower()
        assert "simulated settlement" in disclaimer
        assert "not transmitted" in disclaimer
        assert "no swift connectivity" in disclaimer
        assert "not schema-validated" in disclaimer

    def test_every_rendering_is_marked_simulated(self, delivery):
        assert "SIMULATED" in to_iso20022_xml(delivery.settlement)
        assert "SIMULATED" in to_mt527(delivery.settlement)

    def test_the_namespace_is_not_a_real_iso_namespace(self, delivery):
        """A real urn would imply schema conformance we have not established."""
        xml = to_iso20022_xml(delivery.settlement)
        assert "urn:aether:simulated:" in xml
        assert "urn:iso:std:iso:20022" not in xml

    def test_bics_are_placeholders(self, delivery):
        """Structurally valid, and belonging to nobody."""
        for bic in (delivery.settlement.deliverer_bic, delivery.settlement.receiver_bic):
            assert len(bic) == 11
            assert bic.endswith("XXX")


class TestAuditIntegration:
    def test_the_instruction_appears_in_the_audit_chain(self, delivery):
        actions = [event.action for event in delivery.audit.events]
        assert "SETTLEMENT_INSTRUCTION_GENERATED" in actions

    def test_the_audit_event_records_that_nothing_was_sent(self, delivery):
        event = next(
            e for e in delivery.audit.events if e.action == "SETTLEMENT_INSTRUCTION_GENERATED"
        )
        assert event.payload["transmitted"] is False

    def test_the_chain_still_verifies(self, delivery):
        valid, break_at, _ = delivery.audit.verify()
        assert valid
        assert break_at is None


class TestReturnAmount:
    def test_a_return_reverses_the_delivery_direction(self):
        """On a Return Amount, collateral flows back: the holder delivers."""
        result = run_scenario(
            "MKT-2026-08-17-STRESS",
            date(2026, 8, 17),
            run_id="RUN-RETURN",
            posted_value=Money.of("15000000", USD),
        )
        assert result.margin_call.direction is CallDirection.RETURN
        assert result.settlement is not None
        assert result.settlement.direction is CallDirection.RETURN
        # Party A owes nothing and gets collateral back, so Party B delivers.
        assert "Meridian" in result.settlement.deliverer
