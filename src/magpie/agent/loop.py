"""Autonomous agent loop — continuously analyzes watchlist and executes trades.

Hybrid autonomy model:
  - Trades with estimated cost <= MAGPIE_AUTO_TRADE_MAX_COST (and passing risk
    checks) are executed automatically.
  - All other "enter" recommendations are saved with status='pending_approval'
    for human review via `magpie agent pending` or the HTTP API.

Run with:
    uv run magpie-agent
    # or
    uv run python scripts/run_agent.py
"""

from __future__ import annotations

import logging
import signal
import time
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class AgentLoop:
    """Continuously scans the watchlist and acts on LLM recommendations."""

    def __init__(self) -> None:
        self._running = False

    def run(self, interval: int | None = None) -> None:
        """Run the agent loop indefinitely.

        Args:
            interval: Seconds between scan cycles. Defaults to MAGPIE_AGENT_INTERVAL.
        """
        from magpie.config import settings

        interval = interval if interval is not None else settings.magpie_agent_interval
        self._running = True

        # Graceful shutdown on SIGTERM / SIGINT
        signal.signal(signal.SIGTERM, lambda *_: self._stop())
        signal.signal(signal.SIGINT, lambda *_: self._stop())

        logger.info("Agent loop started. Scan interval: %ds", interval)
        while self._running:
            try:
                self._scan_cycle()
            except Exception:
                logger.exception("Scan cycle failed — will retry next interval")
            if self._running:
                logger.debug("Sleeping %ds until next scan", interval)
                time.sleep(interval)

        logger.info("Agent loop stopped.")

    def _stop(self) -> None:
        logger.info("Shutdown signal received — stopping after current cycle.")
        self._running = False

    def _scan_cycle(self) -> None:
        from magpie.analysis.llm import LLMKeyMissing
        from magpie.config import settings
        from magpie.market.client import get_trading_client

        logger.info("Starting scan cycle at %s", datetime.now(timezone.utc).isoformat())

        symbols = self._get_watchlist()
        if not symbols:
            logger.info("Watchlist is empty — nothing to scan.")
            return

        # Fetch account info once per cycle
        try:
            client = get_trading_client()
            account = client.get_account()
            equity = float(account.equity)
            # Approximate daily P&L from change_today
            daily_pnl = float(getattr(account, "equity_previous_close", equity) or equity) - equity
        except Exception as exc:
            logger.warning("Could not fetch account info: %s — skipping cycle", exc)
            return

        for symbol in symbols:
            if not self._running:
                break
            try:
                self._analyze_and_act(symbol, equity, daily_pnl, settings)
            except LLMKeyMissing as exc:
                logger.error("LLM key missing — cannot run analysis: %s", exc)
                break  # No point retrying other symbols either
            except Exception:
                logger.exception("Failed to process %s — skipping", symbol)

    def _analyze_and_act(
        self,
        symbol: str,
        equity: float,
        daily_pnl: float,
        settings,  # magpie.config.Settings
    ) -> None:
        from magpie.analysis.llm import run_analysis
        from magpie.execution.risk import run_all_checks
        from magpie.market.snapshots import build_analysis_context

        logger.info("Analyzing %s ...", symbol)
        context = build_analysis_context(symbol)
        analysis = run_analysis(symbol, context)

        logger.info(
            "%s: recommendation=%s confidence=%.2f strategy=%s",
            symbol,
            analysis.recommendation,
            analysis.confidence_score or 0.0,
            analysis.strategy_suggested,
        )

        if analysis.recommendation != "enter":
            logger.info("%s: no entry signal — skipping", symbol)
            return

        legs = self._extract_legs(analysis)
        cost = self._estimate_cost(analysis, equity)

        risk = run_all_checks(
            trade_cost=cost,
            account_equity=equity,
            current_daily_pnl=daily_pnl,
        )

        auto_limit = settings.magpie_auto_trade_max_cost
        if risk.passed and auto_limit > 0 and cost <= auto_limit:
            logger.info("%s: auto-executing (cost=%.2f <= limit=%.2f)", symbol, cost, auto_limit)
            self._auto_execute(analysis, legs, cost)
        else:
            reason = "above auto-trade limit" if risk.passed else "; ".join(risk.violations)
            logger.info("%s: queuing for approval — %s", symbol, reason)
            self._queue_for_approval(analysis, legs, cost, reason)

    def _extract_legs(self, analysis) -> list[dict]:
        """Convert LLM analysis legs to journal leg format."""
        raw_legs = []
        if analysis.context_snapshot and "legs" in analysis.context_snapshot:
            raw_legs = analysis.context_snapshot["legs"]
        # Legs from parsed response are stored in context_snapshot by run_analysis when available.
        # Fall back to building a synthetic single-leg from suggestion fields.
        return raw_legs

    def _estimate_cost(self, analysis, equity: float) -> float:
        """Estimate trade cost from entry price. Defaults to 1% of equity if unknown."""
        if analysis.suggested_entry and analysis.suggested_entry > 0:
            # Option premium × 100 (multiplier) × 1 contract
            return analysis.suggested_entry * 100
        return equity * 0.01  # conservative default: 1% of equity

    def _auto_execute(self, analysis, legs: list[dict], cost: float) -> None:
        from magpie.execution.orders import place_multileg_order, place_single_option_order
        from magpie.tracking.journal import create_trade

        try:
            if len(legs) > 1:
                order_legs = [
                    {"contract_id": leg["contract_symbol"], "action": leg["side"], "qty": abs(leg.get("quantity", 1))}
                    for leg in legs
                ]
                order = place_multileg_order(order_legs, limit_price=analysis.suggested_entry)
            elif len(legs) == 1:
                leg = legs[0]
                order = place_single_option_order(
                    leg["contract_symbol"], leg["side"],
                    abs(leg.get("quantity", 1)), limit_price=analysis.suggested_entry
                )
            else:
                logger.warning("No legs to execute for %s — saving as pending instead", analysis.underlying_symbol)
                self._queue_for_approval(analysis, legs, cost, "no legs resolved")
                return

            trade_id = create_trade(
                trade_mode="paper",
                underlying_symbol=analysis.underlying_symbol,
                asset_class="option",
                quantity=1,
                status="open",
                strategy_type=analysis.strategy_suggested,
                entry_price=analysis.suggested_entry,
                legs=legs,
                entry_rationale=analysis.reasoning_summary,
                alpaca_order_id=order["id"],
            )
            logger.info("Auto-executed %s → trade_id=%s order=%s", analysis.underlying_symbol, trade_id, order["id"])

        except Exception:
            logger.exception("Auto-execution failed for %s — saving as pending", analysis.underlying_symbol)
            self._queue_for_approval(analysis, legs, cost, "order placement failed")

    def _queue_for_approval(self, analysis, legs: list[dict], cost: float, reason: str) -> None:
        from magpie.tracking.journal import create_trade

        trade_id = create_trade(
            trade_mode="paper",
            underlying_symbol=analysis.underlying_symbol,
            asset_class="option",
            quantity=1,
            status="pending_approval",
            strategy_type=analysis.strategy_suggested,
            entry_price=analysis.suggested_entry,
            legs=legs,
            entry_rationale=analysis.reasoning_summary,
            notes=f"Pending approval: {reason}",
        )
        logger.info(
            "Queued %s for approval → trade_id=%s reason=%s",
            analysis.underlying_symbol, trade_id, reason,
        )

    def _get_watchlist(self) -> list[str]:
        from magpie.db.connection import get_connection

        conn = get_connection()
        rows = conn.execute("SELECT symbol FROM watchlist ORDER BY priority DESC, symbol ASC").fetchall()
        return [r[0] for r in rows]


def main() -> None:
    import logging

    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")

    loop = AgentLoop()
    loop.run()


if __name__ == "__main__":
    main()
