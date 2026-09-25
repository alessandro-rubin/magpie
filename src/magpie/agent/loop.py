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
            # Daily P&L vs. previous close (negative = loss, as check_daily_loss expects)
            daily_pnl = equity - float(account.last_equity or equity)
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

        from magpie.analysis.llm import _parse_response
        from magpie.execution.orders import net_premium

        llm_legs = _parse_response(analysis.raw_response or "").get("legs") or []
        legs = resolve_legs(symbol, llm_legs, context)
        if not legs:
            logger.warning("%s: could not resolve suggested legs to quoted contracts — skipping", symbol)
            return

        entry_price = round(abs(net_premium(legs)), 2)
        cost = self._estimate_cost(legs)

        risk = run_all_checks(
            trade_cost=cost,
            account_equity=equity,
            current_daily_pnl=daily_pnl,
        )

        auto_limit = settings.magpie_auto_trade_max_cost
        if risk.passed and auto_limit > 0 and cost <= auto_limit:
            logger.info("%s: auto-executing (cost=%.2f <= limit=%.2f)", symbol, cost, auto_limit)
            self._auto_execute(analysis, legs, entry_price, cost)
        else:
            reason = "above auto-trade limit" if risk.passed else "; ".join(risk.violations)
            logger.info("%s: queuing for approval — %s", symbol, reason)
            self._queue_for_approval(analysis, legs, entry_price, cost, reason)

    def _estimate_cost(self, legs: list[dict]) -> float:
        """Capital at risk for one lot: max loss at expiry (debit paid, or width minus credit)."""
        from magpie.dashboard.payoff import max_loss

        return -max_loss(legs)

    def _auto_execute(self, analysis, legs: list[dict], entry_price: float, cost: float) -> None:
        from magpie.execution.orders import (
            place_multileg_order,
            place_single_option_order,
            signed_limit_price,
        )
        from magpie.tracking.journal import create_trade

        try:
            if len(legs) > 1:
                order_legs = [
                    {"contract_id": leg["contract_symbol"], "action": leg["side"], "qty": abs(leg.get("quantity", 1))}
                    for leg in legs
                ]
                order = place_multileg_order(order_legs, limit_price=signed_limit_price(legs, entry_price), qty=1)
            else:
                leg = legs[0]
                order = place_single_option_order(
                    leg["contract_symbol"], leg["side"], 1, limit_price=entry_price
                )

            trade_id = create_trade(
                trade_mode="paper",
                underlying_symbol=analysis.underlying_symbol,
                asset_class="option",
                quantity=1,
                status="open",
                strategy_type=analysis.strategy_suggested,
                entry_price=entry_price,
                legs=legs,
                entry_rationale=analysis.reasoning_summary,
                alpaca_order_id=order["id"],
            )
            logger.info("Auto-executed %s → trade_id=%s order=%s", analysis.underlying_symbol, trade_id, order["id"])

        except Exception:
            logger.exception("Auto-execution failed for %s — saving as pending", analysis.underlying_symbol)
            self._queue_for_approval(analysis, legs, entry_price, cost, "order placement failed")

    def _queue_for_approval(
        self, analysis, legs: list[dict], entry_price: float, cost: float, reason: str
    ) -> None:
        from magpie.tracking.journal import create_trade

        trade_id = create_trade(
            trade_mode="paper",
            underlying_symbol=analysis.underlying_symbol,
            asset_class="option",
            quantity=1,
            status="pending_approval",
            strategy_type=analysis.strategy_suggested,
            entry_price=entry_price,
            legs=legs,
            entry_rationale=analysis.reasoning_summary,
            notes=f"Pending approval: {reason} (max loss ${cost:,.0f}/lot)",
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


MAX_MLEG_LEGS = 4  # Alpaca multi-leg orders accept 2-4 legs


def resolve_legs(symbol: str, llm_legs: list[dict], context: dict, fetch_snapshot=None) -> list[dict]:
    """Map the LLM's suggested legs to quoted OCC contracts in journal leg format.

    Premiums come from the chain in ``context`` when the contract is there, otherwise from a
    live snapshot. Returns [] if any leg is malformed or unquoted — a partial spread is never
    traded.
    """
    from datetime import date

    from magpie.market.occ import build_occ

    if fetch_snapshot is None:
        from magpie.market.options import get_option_snapshot as fetch_snapshot

    if not llm_legs or len(llm_legs) > MAX_MLEG_LEGS:
        logger.warning("%s: expected 1-%d legs, got %d", symbol, MAX_MLEG_LEGS, len(llm_legs or []))
        return []

    chain = context.get("options_chain") or {}
    quotes = {c["contract_id"]: c for c in (chain.get("calls") or []) + (chain.get("puts") or [])}

    legs = []
    for raw in llm_legs:
        try:
            action = str(raw["action"]).lower()
            option_type = str(raw["option_type"]).lower()
            strike = float(raw["strike"])
            expiry = date.fromisoformat(str(raw["expiry"]))
            if action not in ("buy", "sell"):
                raise ValueError(f"invalid action {action!r}")
            contract = build_occ(symbol, expiry, option_type, strike)
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("%s: malformed leg %r (%s)", symbol, raw, exc)
            return []

        quote = quotes.get(contract)
        if quote is None:
            try:
                quote = fetch_snapshot(contract)
            except Exception:
                logger.warning("%s: snapshot fetch failed for %s", symbol, contract, exc_info=True)
                return []
        if not quote or not quote.get("mid"):
            logger.warning("%s: no live quote for %s", symbol, contract)
            return []

        legs.append({
            "contract_symbol": contract,
            "option_type": option_type,
            "strike_price": strike,
            "expiry": expiry.isoformat(),
            "quantity": 1 if action == "buy" else -1,
            "premium": round(quote["mid"], 2),
            "side": action,
        })
    return legs


def main() -> None:
    import logging

    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")

    loop = AgentLoop()
    loop.run()


if __name__ == "__main__":
    main()
