"""Run the AETHER pipeline headless and print the full slice.

The demo path without a browser. Everything the UI will show is produced here first,
which is deliberate: if the slice cannot be understood as text, no amount of frontend
will save it.

Run:  python scripts/run_pipeline.py [--scenario base|stress] [--verify-determinism]
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from aether.pipeline import PipelineResult, run_scenario

SCENARIOS = {
    "base": ("MKT-2026-08-14-BASE", date(2026, 8, 14)),
    "stress": ("MKT-2026-08-17-STRESS", date(2026, 8, 17)),
    "crash": ("MKT-2026-08-18-CRASH", date(2026, 8, 18)),
}

RULE = "-" * 78


def head(title: str) -> None:
    print(f"\n{title}\n{RULE}")


def render(result: PipelineResult) -> None:
    terms = result.terms
    print(f"\n{'=' * 78}")
    print(f"  AETHER  |  {terms.agreement_id}  |  {result.snapshot}")
    print("  SIMULATED DATA - prototype. No transaction is executed.")
    print(f"{'=' * 78}")

    head("1. EXPOSURE  (netting set, pinned snapshot)")
    for valuation in result.exposure.trade_valuations:
        print(
            f"  {valuation.trade_id:<18}{valuation.native_value!s:>22}"
            f"  ->{valuation.base_value!s:>22}"
        )
    print(f"  {'NET EXPOSURE':<18}{result.exposure.exposure!s:>48}")
    print(
        f"  {'netting benefit':<18}{result.exposure.netting_benefit!s:>48}"
        f"   (gross {result.exposure.gross_positive})"
    )

    head("2. INITIAL MARGIN  (indicative, not charged to the VM call)")
    im = result.initial_margin
    print(f"  method              {im.method}")
    print(f"  gross               {im.gross_im}")
    print(f"  net-to-gross ratio  {im.net_to_gross_ratio}")
    print(f"  initial margin      {im.initial_margin}")
    print(f"  {im.disclaimer}")

    risk = result.sensitivity_margin
    head("2b. RISK-WEIGHTED SENSITIVITY MARGIN  (F13)")
    print(f"  method              {risk.method}")
    print(f"  sensitivities       {len(risk.sensitivities)} buckets measured by revaluation")
    print(f"  interest rate       {risk.interest_rate_margin}")
    print(f"  fx                  {risk.fx_margin}")
    print(f"  vega                {risk.vega_margin}   ({risk.vega_note})")
    print(f"  total               {risk.total_margin}")
    print(f"  {risk.disclaimer}")

    head("3. MARGIN WATERFALL  (F6 credit support amount)")
    for step in result.margin_call.trace:
        gate = " [GATE]" if step.is_gate else ""
        print(f"  {step.label:<34}{step.value!s:>20}   {step.clause}{gate}")
    print(f"\n  {result.margin_call.summary}")

    if result.allocation is not None:
        allocation = result.allocation
        head("4. COLLATERAL OPTIMISATION  (F9 linear program)")
        print(f"  status {allocation.status} - {allocation.message}\n")
        print(f"  {'ASSET':<15}{'POSTED':>24}{'EFF%':>8}{'VALUE':>18}{'bp/unit':>10}{'COST':>13}")
        for line in allocation.lines:
            print(
                f"  {line.asset_id:<15}{line.market_value_posted!s:>24}"
                f"{line.effective_percentage:>8.4f}{line.effective_value!s:>18}"
                f"{line.cost_per_effective_unit_bps:>10}{line.annual_cost!s:>13}"
            )
        print(f"  {'':<15}{'':<24}{'':<8}{allocation.allocated_value!s:>18}")

        print("\n  BASELINE (cash-first heuristic)")
        for line in allocation.baseline_lines:
            print(
                f"  {line.asset_id:<15}{line.market_value_posted!s:>24}"
                f"{'':>8}{line.effective_value!s:>18}{'':>10}{line.annual_cost!s:>13}"
            )

        print(
            f"\n  optimiser {allocation.total_cost}   baseline {allocation.baseline_cost}"
            f"   SAVING {allocation.saving} ({allocation.saving_percentage}%)"
        )

        head("5. BINDING CONSTRAINTS  (LP shadow prices)")
        for shadow in allocation.shadow_prices:
            mark = "BIND" if shadow.binding else "    "
            print(f"  {mark} {shadow.shadow_price_bps:>8}bp  {shadow.description}")

        if allocation.excluded:
            print("\n  EXCLUDED")
            for asset_id, reason in allocation.excluded:
                print(f"    {asset_id:<15}{reason}")

    if result.settlement is not None:
        instruction = result.settlement
        head("5b. SETTLEMENT INSTRUCTION  (F10, generated - never sent)")
        print(f"  instruction   {instruction.instruction_id}")
        print(f"  messages      {', '.join(instruction.message_types)}")
        print(f"  {instruction.deliverer} -> {instruction.receiver}")
        print(f"  amount        {instruction.call_amount}   value date {instruction.value_date}")
        for leg in instruction.legs:
            print(
                f"    {leg.sequence}. {leg.asset_id:<15}{leg.market_value!s:>24}"
                f"  -> {leg.collateral_value!s:>18}"
            )
        print(f"  {instruction.disclaimer}")

    head("6. DECISION")
    decision = result.decision
    print(f"  {decision.action}  /  {decision.status}")
    print(f"  {decision.headline}\n")
    for line in decision.rationale:
        print(f"    - {line}")
    print(f"\n  requires human approval: {decision.requires_human_approval}")
    print(f"  {decision.disclaimer}")

    head("6b. AGENT TRACE  (which agent called which tool, and why)")
    for action in result.agent_actions:
        print(f"  {action.agent.value:<27}{action.tool}")
        print(f"      intent    {action.intent}")
        print(f"      arguments {dict(action.arguments)}")
        print(f"      returned  {action.outcome}")
    print()
    print("  No tool call above carries a monetary value: ToolCall rejects one at")
    print("  construction. Every figure in this report came from an engine event.")

    head("7. AUDIT TRAIL  (hash-chained, tamper-evident)")
    for event in result.audit.events:
        print(
            f"  {event.seq}  {event.actor_type.value:<7}{event.action:<26}"
            f"{event.hash[:16]}...  prev {event.prev_hash[:12]}..."
        )
    valid, break_at, message = result.audit.verify()
    print(f"\n  VERIFY: {'OK' if valid else f'BROKEN at {break_at}'} - {message}")
    print(f"  head:   {result.audit.head_hash}")
    print()


def verify_determinism() -> int:
    """Run the same scenario twice and compare the audit head hashes."""
    head("DETERMINISM CHECK")
    snapshot_id, as_of = SCENARIOS["stress"]
    first = run_scenario(snapshot_id, as_of)
    second = run_scenario(snapshot_id, as_of)

    print(f"  run 1 head  {first.audit.head_hash}")
    print(f"  run 2 head  {second.audit.head_hash}")

    identical = first.audit.head_hash == second.audit.head_hash
    print(f"\n  {'IDENTICAL - the pipeline is reproducible.' if identical else 'DIVERGED.'}")
    return 0 if identical else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the AETHER pipeline headless.")
    parser.add_argument("--scenario", choices=sorted(SCENARIOS), default="stress")
    parser.add_argument("--verify-determinism", action="store_true")
    args = parser.parse_args()

    if args.verify_determinism:
        return verify_determinism()

    snapshot_id, as_of = SCENARIOS[args.scenario]
    render(run_scenario(snapshot_id, as_of))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
