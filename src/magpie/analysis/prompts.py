"""Versioned prompt templates for LLM analysis.

Bump PROMPT_VERSION whenever system or analysis prompts change so that
prediction accuracy can be tracked per prompt version in the DB.
"""

PROMPT_VERSION = "v1.0"

# ── System prompt ────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are an expert options trader and quantitative analyst specializing in
defined-risk options strategies. Your role is to analyze market data and provide actionable
trading recommendations for paper trading on Alpaca.

## Your expertise
- Vertical spreads (bull call, bear put, bull put, bear call)
- Iron condors and iron butterflies (range-bound markets)
- Single-leg calls and puts (directional plays with conviction)
- Calendar and diagonal spreads (IV and time decay plays)
- Straddles and strangles (earnings and high-volatility events)

## Analysis framework
For every analysis you must consider:
1. **Direction**: What is the most likely price movement in the next 15-45 days?
2. **Volatility**: Is IV high or low? Favor selling premium in high IV, buying in low IV.
3. **Risk/Reward**: Prefer defined-risk strategies. Max loss must be knowable.
4. **DTE**: Target 30-45 DTE for new positions. Avoid <15 DTE entries.
5. **Delta**: For directional plays, target 0.30-0.50 delta. Neutral = 0.10-0.20 delta.

## Output format
ALWAYS respond with valid JSON only — no markdown fences, no explanation outside the JSON.

Schema:
{
  "recommendation": "enter" | "avoid" | "hold" | "reduce",
  "confidence": 0.0-1.0,
  "strategy": "<strategy_type>",
  "reasoning": "<2-3 sentence explanation>",
  "entry_price": <float or null>,
  "stop_price": <float or null>,
  "target_price": <float or null>,
  "legs": [
    {
      "action": "buy" | "sell",
      "option_type": "call" | "put",
      "strike": <float>,
      "expiry": "<YYYY-MM-DD>",
      "target_delta": <float or null>
    }
  ]
}

If the recommendation is "avoid", legs may be an empty array.
"""

# ── Analysis prompt template ─────────────────────────────────────────────────

ANALYSIS_TEMPLATE = """\
## Task
Analyze the following market data for {symbol} and provide an options trading recommendation.

## Underlying ({symbol})
- Current price: ${price}
- Daily change: {change_pct}
- 20-day SMA: {sma_20}
- Price vs SMA20: {price_vs_sma20}
- 52-week range: ${low_52w} — ${high_52w}
- Volume: {volume}

## IV Metrics
- Current avg IV (chain): {current_iv}
- IV Rank (0-100): {iv_rank}

## Options Chain Snapshot (15–45 DTE)
Total liquid contracts found: {total_contracts}

Top ATM Calls:
{calls_summary}

Top ATM Puts:
{puts_summary}

## Recent Price History (last 5 days)
{price_history}

{feedback_section}
"""

# ── Feedback section template ─────────────────────────────────────────────────

FEEDBACK_TEMPLATE = """\
## Your Historical Performance on {symbol} (last {window_days} days)
{performance_text}

Use this to calibrate your current recommendation — avoid repeating patterns that have
historically lost money on this symbol or with this strategy.
"""

NO_HISTORY_TEXT = "No historical data yet — this is your first analysis. Start building your track record."


def format_analysis_prompt(
    symbol: str,
    context: dict,
    feedback_summary: dict | None = None,
    window_days: int = 30,
) -> str:
    """Render the analysis prompt from market context and optional feedback."""
    underlying = context.get("underlying", {})
    iv = context.get("iv_metrics", {})
    chain = context.get("options_chain", {})
    history = context.get("price_history_summary", {})

    def _pct(v: float | None) -> str:
        return f"{v * 100:+.2f}%" if v is not None else "N/A"

    def _price(v: float | None) -> str:
        return f"{v:.2f}" if v is not None else "N/A"

    def _summarize_contracts(contracts: list[dict]) -> str:
        if not contracts:
            return "  None available\n"
        lines = []
        for c in contracts[:5]:
            cid = c.get("contract_id", "")
            delta = f"{c['delta']:.2f}" if c.get("delta") else "N/A"
            iv_str = f"{c['implied_volatility'] * 100:.1f}%" if c.get("implied_volatility") else "N/A"
            theta = f"{c['theta']:.4f}" if c.get("theta") else "N/A"
            mid = f"${c['mid']:.2f}" if c.get("mid") else "N/A"
            oi = c.get("open_interest") or 0
            lines.append(f"  {cid}: delta={delta}, IV={iv_str}, theta={theta}/day, mid={mid}, OI={oi}")
        return "\n".join(lines)

    def _summarize_bars(bars: list[dict]) -> str:
        lines = []
        for b in bars:
            ts = str(b.get("timestamp", ""))[:10]
            lines.append(
                f"  {ts}: O={b.get('open', 0):.2f} H={b.get('high', 0):.2f} "
                f"L={b.get('low', 0):.2f} C={b.get('close', 0):.2f} V={b.get('volume', 0):,}"
            )
        return "\n".join(lines) if lines else "  No data"

    # Feedback section
    if feedback_summary and feedback_summary.get("total_analyses", 0) > 0:
        perf_text = feedback_summary.get("narrative", NO_HISTORY_TEXT)
        feedback_section = FEEDBACK_TEMPLATE.format(
            symbol=symbol,
            window_days=window_days,
            performance_text=perf_text,
        )
    else:
        feedback_section = f"## Historical Performance\n{NO_HISTORY_TEXT}"

    return ANALYSIS_TEMPLATE.format(
        symbol=symbol,
        price=_price(underlying.get("price")),
        change_pct=_pct(underlying.get("change_pct")),
        sma_20=_price(underlying.get("sma_20")),
        price_vs_sma20=_pct(underlying.get("price_vs_sma20")),
        low_52w=_price(underlying.get("low_52w")),
        high_52w=_price(underlying.get("high_52w")),
        volume=f"{underlying.get('volume') or 0:,}",
        current_iv=_pct(iv.get("current_iv")),
        iv_rank=f"{iv.get('iv_rank'):.1f}" if iv.get("iv_rank") is not None else "N/A",
        total_contracts=chain.get("total_contracts", 0),
        calls_summary=_summarize_contracts(chain.get("calls", [])),
        puts_summary=_summarize_contracts(chain.get("puts", [])),
        price_history=_summarize_bars(history.get("bars_30d", [])),
        feedback_section=feedback_section,
    )
