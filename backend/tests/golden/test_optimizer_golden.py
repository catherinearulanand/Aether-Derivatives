"""Golden reference cases for the collateral optimizer.

The expected allocation is derived by hand from the cost-per-effective-unit ranking
and the concentration caps, before consulting the solver:

    equity        2 / 0.8500 =  2.35 bp per effective unit   (cheapest)
    Northwind     4 / 0.9200 =  4.35
    Contoso       5 / 0.9200 =  5.43
    gold          6 / 0.8800 =  6.82
    UST 6M        8 / 0.9950 =  8.04
    India G-Sec   9 / 0.8648 = 10.41   <- 9bp headline, 10.41 after the FX haircut
    Bund         10 / 0.8924 = 11.21
    UST 3Y       12 / 0.9800 = 12.24
    UST 7Y       15 / 0.9600 = 15.62
    cash USD     30 / 1.0000 = 30.00
    cash EUR     28 / 0.9200 = 30.43   (most expensive)

Against a USD 9,500,000 requirement the caps bite in this order: equity is limited by
inventory (2.0m x 0.85 = 1.7m, inside its 20% cap); corporate debt is capped at 30%
of the balance and Northwind alone at 25%; gold is capped at 15%. The Treasury bill
then covers the residual at 8.04 bp, and **the India G-Sec is not reached**.

That last fact is the honest outcome of the fixture and is asserted here as such. The
cross-border argument does not depend on the rupee paper being posted: it is carried
by the ranking, which the optimizer computes for every eligible asset whether or not
it is used. Two rows make it, and both are asserted below:

    India G-Sec   9 bp headline, 10.41 bp delivered  -> priced out, with the reason
    cash EUR     28 bp headline, 30.43 bp delivered  -> ranks BELOW 30 bp cash USD

The second is a genuine ranking inversion: the asset that is cheaper on the headline
number is dearer per unit of collateral actually delivered. A desk ranking by funding
spread would reach for the EUR cash first and be wrong.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from aether.core.money import Currency, Money
from aether.core.optimize import OptimizerStatus, optimize_collateral
from aether.fixtures.loader import load_agreement, load_inventory, load_snapshot

pytestmark = pytest.mark.golden

USD = Currency.USD
REQUIRED = Money.of("9500000", USD)


@pytest.fixture(scope="module")
def result():
    return optimize_collateral(
        load_agreement(),
        load_inventory(),
        load_snapshot("MKT-2026-08-17-STRESS"),
        REQUIRED,
    )


class TestCheapestToDeliver:
    def test_solves_optimally(self, result):
        assert result.status is OptimizerStatus.OPTIMAL

    def test_covers_the_requirement_exactly(self, result):
        """Minimising a strictly positive cost means never over-posting."""
        assert result.allocated_value == REQUIRED

    def test_uses_the_five_cheapest_eligible_assets(self, result):
        assert [line.asset_id for line in result.lines] == [
            "US0000E0Y08",  # equity, 2.35 bp/unit
            "US0000C3Y06",  # Northwind, 4.35
            "US0000C4Y07",  # Contoso, 5.43
            "XAU-ALLOC-01",  # allocated gold, 6.82
            "US0000T6M01",  # UST 6M, 8.04
        ]

    def test_lines_are_ordered_by_cost_per_effective_unit(self, result):
        costs = [line.cost_per_effective_unit_bps for line in result.lines]
        assert costs == sorted(costs)

    def test_declines_the_expensive_assets(self, result):
        """Cash is never posted despite a 100% valuation percentage."""
        posted = {line.asset_id for line in result.lines}
        assert "CASH-USD" not in posted
        assert "CASH-EUR" not in posted
        assert "US0000T7Y03" not in posted


class TestFXHaircutEconomics:
    """The GIFT City argument, made through economics rather than branding."""

    def test_india_gsec_is_priced_for_the_fx_drag(self, result):
        """94% schedule x 92% FX = 86.48% effective, so 9bp becomes 10.41bp delivered.

        The document supplies this worked example itself at Paragraph 11(g)(i), which
        is where the expected value comes from — not from running the code.
        """
        line = next(line for line in result.considered if line.asset_id == "IN0000G6Y05")

        assert line.fx_haircut_applied
        assert line.effective_percentage == Decimal("0.8648")
        assert line.funding_spread_bps == Decimal("9")
        # 9 / 0.8648 = 10.41, so it ranks behind the 8bp Treasury bill.
        assert line.cost_per_effective_unit_bps == Decimal("10.41")

    def test_the_fx_drag_is_isolated_from_the_schedule_haircut(self, result):
        """How much of the cost is the FX haircut alone?

        9 / 0.9400 = 9.574 bp without it; 9 / 0.8648 = 10.407 bp with it. The
        difference, 0.83 bp, is the price of posting cross-border collateral,
        separated from the schedule valuation that would apply in any currency.
        """
        line = next(line for line in result.considered if line.asset_id == "IN0000G6Y05")
        assert line.fx_drag_bps == Decimal("0.83")

    def test_india_gsec_is_not_reached_and_says_why(self, result):
        """The authentic outcome of this fixture, asserted rather than arranged.

        The optimizer evaluated the rupee paper and priced it out. That is a result,
        not a gap: the reason is computed from the solved problem and rendered, so the
        product can answer "why not that one?" — which is the question an optimizer
        that cannot answer it has no business being trusted on.
        """
        assert all(line.asset_id != "IN0000G6Y05" for line in result.lines)

        line = next(line for line in result.considered if line.asset_id == "IN0000G6Y05")
        assert not line.selected
        assert "10.41bp per effective unit" in line.not_selected_reason
        assert "8.04bp" in line.not_selected_reason

    def test_cross_border_rows_are_reported_whether_or_not_they_are_posted(self, result):
        """The GIFT City argument survives the rupee paper not being used.

        Every non-base-currency asset is reported with its ranking and its FX drag,
        selected or not. The economics are visible either way.
        """
        assert {line.asset_id for line in result.cross_border_lines} == {
            "IN0000G6Y05",
            "DE0000B5Y04",
            "CASH-EUR",
        }
        assert all(line.fx_drag_bps > 0 for line in result.cross_border_lines)

    def test_the_fx_haircut_reverses_the_cash_ranking(self):
        """EUR cash is cheaper on headline spread and dearer per unit delivered.

        28bp / 0.92 = 30.43 against 30bp / 1.00 = 30.00. A desk ranking by funding
        spread would reach for the EUR cash first and be wrong. This is the clearest
        instance in the inventory of the FX haircut inverting an ordering.
        """
        from aether.core.haircut import assess_eligibility

        terms = load_agreement()
        inventory = load_inventory()

        usd_cash = inventory.by_id("CASH-USD")
        eur_cash = inventory.by_id("CASH-EUR")

        usd_eff = assess_eligibility(usd_cash, terms).effective_percentage
        eur_eff = assess_eligibility(eur_cash, terms).effective_percentage

        assert usd_eff == Decimal("1.000")
        assert eur_eff == Decimal("0.92")

        # Cheaper on the headline number.
        assert eur_cash.funding_spread_bps < usd_cash.funding_spread_bps
        # Dearer on the number that actually matters.
        assert eur_cash.funding_spread_bps / eur_eff > usd_cash.funding_spread_bps / usd_eff

    def test_the_fx_haircut_narrows_the_inr_advantage(self, result):
        """The INR paper stays competitive, but by far less than headline suggests."""
        inr = next(line for line in result.considered if line.asset_id == "IN0000G6Y05")
        ust_3y_headline = Decimal("12")

        headline_advantage = ust_3y_headline - inr.funding_spread_bps
        effective_advantage = Decimal("12.24") - inr.cost_per_effective_unit_bps

        assert headline_advantage == Decimal("3")
        assert effective_advantage < headline_advantage

    def test_amounts_are_reported_in_the_asset_currency(self, result):
        """Native currency for the quantity, base currency for the collateral value."""
        line = next(line for line in result.considered if line.asset_id == "IN0000G6Y05")
        assert line.market_value_posted.currency is Currency.INR
        assert line.effective_value.currency is USD
        assert line.available_market_value is not None
        assert line.available_market_value.currency is Currency.INR

    def test_the_eur_cash_ranking_inversion_is_reported(self, result):
        """The clearest instance in the inventory, and it needs no allocation.

        EUR cash is cheaper than USD cash on the headline spread and dearer per unit
        delivered. The two rank columns disagree, which is the whole argument.
        """
        eur = next(line for line in result.considered if line.asset_id == "CASH-EUR")
        usd = next(line for line in result.considered if line.asset_id == "CASH-USD")

        assert eur.funding_spread_bps < usd.funding_spread_bps
        assert eur.cost_per_effective_unit_bps > usd.cost_per_effective_unit_bps
        assert eur.headline_rank < eur.effective_rank


class TestConcentrationCaps:
    def test_corporate_debt_is_held_at_its_30_percent_cap(self, result):
        corporate = sum(
            (
                line.effective_value.amount
                for line in result.lines
                if line.asset_id in {"US0000C3Y06", "US0000C4Y07"}
            ),
            Decimal(0),
        )
        assert corporate == Decimal("2850000.00")  # 30% of 9,500,000

    def test_northwind_is_held_at_its_25_percent_issuer_cap(self, result):
        line = next(line for line in result.lines if line.asset_id == "US0000C3Y06")
        assert line.effective_value == Money.of("2375000", USD)  # 25% of 9,500,000

    def test_equity_is_limited_by_inventory_not_by_its_cap(self, result):
        """2.0m x 0.85 = 1.7m, below the 20% (1.9m) cap. Honest about which binds."""
        line = next(line for line in result.lines if line.asset_id == "US0000E0Y08")
        assert line.effective_value == Money.of("1700000", USD)
        assert line.market_value_posted == Money.of("2000000", USD)


class TestShadowPrices:
    def test_coverage_constraint_binds(self, result):
        coverage = next(s for s in result.shadow_prices if s.name == "coverage")
        assert coverage.binding
        assert coverage.shadow_price_bps > 0

    def test_corporate_cap_binds_and_has_a_price(self, result):
        cap = next(s for s in result.shadow_prices if s.name == "concentration:CORPORATE_BOND")
        assert cap.binding
        assert cap.shadow_price_bps > 0

    def test_northwind_issuer_cap_binds(self, result):
        cap = next(s for s in result.shadow_prices if s.name == "issuer:NORTHWIND_TECH")
        assert cap.binding

    def test_equity_cap_does_not_bind(self, result):
        """Inventory runs out first, so the cap costs nothing."""
        cap = next(s for s in result.shadow_prices if s.name == "concentration:EQUITY")
        assert not cap.binding

    def test_binding_constraints_are_surfaced_separately(self, result):
        names = {s.name for s in result.binding_constraints}
        assert names == {
            "coverage",
            "concentration:CORPORATE_BOND",
            "concentration:GOLD",
            "issuer:NORTHWIND_TECH",
        }

    def test_gold_cap_binds_at_fifteen_percent(self, result):
        """15% of 9,500,000 = 1,425,000 of post-haircut value, from 3.0m available."""
        cap = next(s for s in result.shadow_prices if s.name == "concentration:GOLD")
        assert cap.binding
        line = next(line for line in result.lines if line.asset_id == "XAU-ALLOC-01")
        assert line.effective_value == Money.of("1425000", USD)


class TestBaselineComparison:
    def test_baseline_posts_cash_first(self, result):
        assert [line.asset_id for line in result.baseline_lines][:2] == [
            "CASH-USD",
            "CASH-EUR",
        ]

    def test_optimizer_beats_the_baseline(self, result):
        assert result.total_cost < result.baseline_cost

    def test_the_saving_is_material(self, result):
        """Measured, not asserted. If the fixtures change, this number changes."""
        assert result.saving.is_positive
        assert result.saving_percentage > Decimal("50")

    def test_costs_are_reported_in_base_currency(self, result):
        assert result.total_cost.currency is USD
        assert result.baseline_cost.currency is USD


class TestWrongWayExclusion:
    def test_meridian_paper_is_excluded_with_a_reason(self, result):
        excluded = dict(result.excluded)
        assert "US0000C2Y09" in excluded
        assert "11(g)(iv)" in excluded["US0000C2Y09"]

    def test_it_is_the_only_exclusion(self, result):
        assert len(result.excluded) == 1
