"""PydanticAI-based trading analysis agent for Magpie.

This module is an example of building an agentic analysis pipeline with
PydanticAI — as an alternative to the single-shot LLM call in analysis/llm.py.

Key differences from analysis/llm.py:
  - Multi-turn: the agent calls tools iteratively to gather data before deciding
  - Structured: output is a Pydantic model validated at parse time, not hand-parsed JSON
  - Typed: full type safety on tool inputs, outputs, and the final recommendation
  - Testable: swap in TestModel for unit tests without any real API calls

Quickstart:
    uv run magpie-pydantic-agent AAPL

    # or in Python:
    import asyncio
    from magpie.agent.pydantic_agent import run_pydantic_analysis
    rec = asyncio.run(run_pydantic_analysis("AAPL"))
    print(rec.recommendation, rec.confidence)
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field
from pydantic_ai import Agent, RunContext

# Module-level imports let tests patch these without deep path targeting.
from magpie.config import settings
from magpie.db.connection import get_connection

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are Magpie, an expert options trading analyst for an Alpaca paper account.

Your goal is to analyze a symbol and decide whether to enter an options trade.

## Workflow

Call your tools in this order:
1. get_market_context — fetch live price, options chain, IV rank, and market regime
2. get_performance_feedback — see recent win rates and injected trading rules
3. get_open_positions — check portfolio concentration (optional, use if considering entry)
4. check_risk_limits — validate cost against account limits before recommending "enter"

## Decision criteria

- Only recommend "enter" when conviction is >= 0.65 AND risk limits pass
- Recommend "avoid" when the setup is unattractive or rules are violated
- Recommend "hold" or "reduce" only when asked about an existing position
- Always factor in market regime (bullish/bearish, low/high vol)

## Output

Return a structured TradeRecommendation with every field filled in.
For "enter" recommendations always include legs (strike, expiry, option_type).
Reasoning must be concise (2-4 sentences) and reference the data you gathered.
"""

# ---------------------------------------------------------------------------
# Dependencies — injected into every tool call
# ---------------------------------------------------------------------------


@dataclass
class MagpieDeps:
    """Context available to all tools during a single agent run."""

    symbol: str
    equity: float = 100_000.0
    daily_pnl: float = 0.0


# ---------------------------------------------------------------------------
# Structured output models
# ---------------------------------------------------------------------------


class TradeLeg(BaseModel):
    """A single leg of an options trade."""

    action: Literal["buy", "sell"]
    option_type: Literal["call", "put"]
    strike: float = Field(gt=0)
    expiry: str = Field(description="Expiration date as YYYY-MM-DD")
    target_delta: float | None = Field(None, ge=-1.0, le=1.0)


class TradeRecommendation(BaseModel):
    """Structured output produced by the Magpie trading agent."""

    recommendation: Literal["enter", "avoid", "hold", "reduce"]
    confidence: float = Field(ge=0.0, le=1.0, description="Conviction level 0–1")
    strategy: str = Field(
        description="Strategy label, e.g. 'vertical_spread', 'iron_condor', 'long_call'"
    )
    reasoning: str = Field(description="2–4 sentence explanation citing the data gathered")
    entry_price: float | None = Field(None, description="Estimated net debit/credit per contract")
    stop_price: float | None = Field(None, description="Stop-loss level on the underlying")
    target_price: float | None = Field(None, description="Profit-target level on the underlying")
    legs: list[TradeLeg] = Field(default_factory=list)
    risk_check_passed: bool = Field(
        False, description="True when check_risk_limits confirmed the trade fits account limits"
    )


# ---------------------------------------------------------------------------
# Agent
#
# defer_model_check=True skips API-key validation at import time.
# The model is overridden at run time by run_pydantic_analysis() which either
# builds a real model from settings or accepts a TestModel() from the caller.
# ---------------------------------------------------------------------------

magpie_agent: Agent[MagpieDeps, TradeRecommendation] = Agent(
    "anthropic:claude-opus-4-6",
    output_type=TradeRecommendation,
    deps_type=MagpieDeps,
    system_prompt=_SYSTEM_PROMPT,
    defer_model_check=True,
)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@magpie_agent.tool
async def get_market_context(ctx: RunContext[MagpieDeps]) -> dict:
    """Fetch current price, options chain, IV rank, and market regime for the symbol.

    Returns a dict with keys: underlying, options_chain, iv_metrics,
    price_history, market_regime.
    """
    from magpie.market.snapshots import build_analysis_context

    return build_analysis_context(ctx.deps.symbol)


@magpie_agent.tool
async def get_performance_feedback(ctx: RunContext[MagpieDeps]) -> str:
    """Return historical win rates, per-strategy stats, and active trading rules.

    This is the self-correction signal: past performance + rules are both
    injected here so the agent can spot patterns and avoid repeat mistakes.
    """
    from magpie.analysis.feedback import get_combined_feedback

    return (
        get_combined_feedback(symbol=ctx.deps.symbol, window_days=30)
        or "No performance history yet."
    )


@magpie_agent.tool
async def get_open_positions(ctx: RunContext[MagpieDeps]) -> list[dict]:
    """List currently open trades to assess portfolio concentration.

    Call this before recommending entry to avoid doubling up on the same
    underlying or strategy when positions are already at risk.
    """
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT id, underlying_symbol, strategy_type, entry_price,
               unrealized_pnl, dte_at_entry
        FROM trade_journal
        WHERE status = 'open'
        ORDER BY created_at DESC
        """
    ).fetchall()
    return [
        {
            "id": r[0],
            "symbol": r[1],
            "strategy": r[2],
            "entry_price": r[3],
            "unrealized_pnl": r[4],
            "dte_at_entry": r[5],
        }
        for r in rows
    ]


@magpie_agent.tool
async def check_risk_limits(
    ctx: RunContext[MagpieDeps],
    estimated_cost: float,
) -> dict:
    """Validate a proposed trade against account-level risk limits.

    Args:
        estimated_cost: Total trade cost in dollars (premium × 100 × contracts).

    Returns:
        {"passed": bool, "violations": list[str]}
        Always call this before recommending "enter". Set risk_check_passed=True
        in your response if and only if passed=True.
    """
    from magpie.execution.risk import run_all_checks

    result = run_all_checks(
        trade_cost=estimated_cost,
        account_equity=ctx.deps.equity,
        current_daily_pnl=ctx.deps.daily_pnl,
    )
    return {"passed": result.passed, "violations": result.violations}


# ---------------------------------------------------------------------------
# Model factory
# ---------------------------------------------------------------------------


class LLMKeyMissing(RuntimeError):
    """Raised when the configured provider's API key is absent."""


def _get_model_name() -> object:
    """Return a PydanticAI model for the configured provider.

    Builds an AnthropicModel or GroqModel with the API key from settings.
    Raises LLMKeyMissing if the required API key is not set.
    """
    if settings.llm_provider == "groq":
        if not settings.groq_api_key:
            raise LLMKeyMissing(
                "GROQ_API_KEY is not set. Add it to .env when using LLM_PROVIDER=groq."
            )
        from pydantic_ai.models.groq import GroqModel
        from pydantic_ai.providers.groq import GroqProvider

        return GroqModel(
            settings.groq_model,
            provider=GroqProvider(api_key=settings.groq_api_key),
        )

    if not settings.anthropic_api_key:
        raise LLMKeyMissing(
            "ANTHROPIC_API_KEY is not set. "
            "Add it to .env, or use Claude Code interactively with the Alpaca MCP server."
        )
    from pydantic_ai.models.anthropic import AnthropicModel
    from pydantic_ai.providers.anthropic import AnthropicProvider

    return AnthropicModel(
        settings.anthropic_model,
        provider=AnthropicProvider(api_key=settings.anthropic_api_key),
    )


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


async def run_pydantic_analysis(
    symbol: str,
    equity: float = 100_000.0,
    daily_pnl: float = 0.0,
    *,
    persist: bool = True,
    model=None,
) -> TradeRecommendation:
    """Run the PydanticAI trading agent for a symbol and return a recommendation.

    The agent will call tools (get_market_context, get_performance_feedback, etc.)
    in a multi-turn loop before producing the final structured output.

    Args:
        symbol: Underlying symbol, e.g. "AAPL".
        equity: Current account equity (for risk checks).
        daily_pnl: Today's realised P&L (for daily loss limit check).
        persist: Write the result to llm_analyses when True.
        model: PydanticAI model override — pass TestModel() in unit tests to
               skip real API calls. Defaults to the provider in settings.

    Returns:
        TradeRecommendation — Pydantic-validated structured output.

    Raises:
        LLMKeyMissing: If no model override is supplied and the API key is absent.
    """
    if model is None:
        model = _get_model_name()

    deps = MagpieDeps(symbol=symbol, equity=equity, daily_pnl=daily_pnl)

    logger.info("PydanticAI agent: analyzing %s", symbol)
    result = await magpie_agent.run(
        f"Analyze {symbol} and give me a trade recommendation.",
        deps=deps,
        model=model,
    )

    rec = result.output
    usage = result.usage()
    logger.info(
        "%s → recommendation=%s confidence=%.0f%% strategy=%s tokens=%d",
        symbol,
        rec.recommendation,
        rec.confidence * 100,
        rec.strategy,
        (usage.total_tokens or 0),
    )

    if persist:
        _persist_result(symbol, rec, result)

    return rec


def _persist_result(symbol: str, rec: TradeRecommendation, result) -> None:
    """Save a PydanticAI recommendation to the llm_analyses table."""
    from magpie.analysis.prompts import PROMPT_VERSION

    model_name = (
        settings.groq_model if settings.llm_provider == "groq" else settings.anthropic_model
    )
    context_snapshot = {
        "framework": "pydantic_ai",
        "tool_calls": len(result.all_messages()),
    }

    conn = get_connection()
    conn.execute(
        """
        INSERT INTO llm_analyses (
            id, created_at, underlying_symbol, analysis_type,
            model, prompt_version, context_snapshot,
            raw_response, recommendation, confidence_score,
            strategy_suggested, reasoning_summary,
            suggested_entry, suggested_stop, suggested_target
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            str(uuid.uuid4()),
            datetime.now(timezone.utc),
            symbol,
            "pydantic_ai_recommendation",
            model_name,
            PROMPT_VERSION,
            json.dumps(context_snapshot),
            json.dumps(rec.model_dump()),
            rec.recommendation,
            rec.confidence,
            rec.strategy,
            rec.reasoning,
            rec.entry_price,
            rec.stop_price,
            rec.target_price,
        ],
    )
    conn.commit()
    logger.debug("Persisted PydanticAI analysis for %s", symbol)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> None:
    import sys

    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s"
    )

    symbol = sys.argv[1].upper() if len(sys.argv) > 1 else "SPY"
    rec = asyncio.run(run_pydantic_analysis(symbol))

    sep = "=" * 60
    print(f"\n{sep}")
    print(f"Symbol:         {symbol}")
    print(f"Recommendation: {rec.recommendation.upper()}")
    print(f"Confidence:     {rec.confidence:.0%}")
    print(f"Strategy:       {rec.strategy}")
    print(f"Risk OK:        {rec.risk_check_passed}")
    print(f"Reasoning:      {rec.reasoning}")
    if rec.entry_price:
        print(f"Entry price:    ${rec.entry_price:.2f}")
    if rec.stop_price:
        print(f"Stop:           ${rec.stop_price:.2f}")
    if rec.target_price:
        print(f"Target:         ${rec.target_price:.2f}")
    if rec.legs:
        print(f"Legs ({len(rec.legs)}):")
        for leg in rec.legs:
            delta_str = f"  δ≈{leg.target_delta:.2f}" if leg.target_delta else ""
            print(
                f"  {leg.action.upper():4s} {leg.option_type:4s} "
                f"${leg.strike:.0f} exp {leg.expiry}{delta_str}"
            )
    print(sep)


if __name__ == "__main__":
    main()
