"""Claude API integration — run analysis and persist results.

If ANTHROPIC_API_KEY is not set, run_analysis() raises AnthropicKeyMissing.
The CLI handles this by printing the formatted prompt for manual use in Claude Code.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from tenacity import retry, stop_after_attempt, wait_exponential

from magpie.analysis.prompts import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    format_analysis_prompt,
)
from magpie.db.models import LLMAnalysis


class AnthropicKeyMissing(RuntimeError):
    """Raised when ANTHROPIC_API_KEY is not configured."""


def _get_client():  # type: ignore[return]
    from magpie.config import settings

    if not settings.anthropic_api_key:
        raise AnthropicKeyMissing(
            "ANTHROPIC_API_KEY is not set. "
            "Add it to .env to enable standalone analysis, "
            "or use Claude Code interactively with the Alpaca MCP server."
        )

    import anthropic

    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=15))
def _call_api(model: str, prompt: str) -> str:
    """Call the Claude API and return the raw text response."""
    client = _get_client()
    message = client.messages.create(
        model=model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def _parse_response(raw: str) -> dict:
    """Parse the JSON response from the LLM. Returns empty dict on failure."""
    text = raw.strip()
    # Strip markdown fences if the model added them despite instructions
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {}


def build_prompt(symbol: str, context: dict) -> str:
    """
    Build the full analysis prompt for a symbol without calling the API.

    Use this when ANTHROPIC_API_KEY is not set — print the output and
    paste it into Claude Code for interactive analysis.
    """
    from magpie.analysis.feedback import compute_accuracy_stats, format_feedback_for_prompt

    feedback_raw = compute_accuracy_stats(symbol=symbol, window_days=30)
    feedback_summary = format_feedback_for_prompt(feedback_raw) if feedback_raw else {}

    return format_analysis_prompt(
        symbol=symbol,
        context=context,
        feedback_summary=feedback_summary,
    )


def run_analysis(
    symbol: str,
    context: dict,
    hypothetical_only: bool = False,
) -> LLMAnalysis:
    """
    Run a full LLM analysis for a symbol and persist the result to the DB.

    Raises AnthropicKeyMissing if ANTHROPIC_API_KEY is not configured.
    In that case, use build_prompt() to get the prompt text for manual use.
    """
    from magpie.analysis.feedback import compute_accuracy_stats, format_feedback_for_prompt
    from magpie.config import settings

    feedback_raw = compute_accuracy_stats(symbol=symbol, window_days=30)
    feedback_summary = format_feedback_for_prompt(feedback_raw) if feedback_raw else {}

    prompt = format_analysis_prompt(
        symbol=symbol,
        context=context,
        feedback_summary=feedback_summary,
    )

    model = settings.anthropic_model
    raw_response = _call_api(model=model, prompt=prompt)
    parsed = _parse_response(raw_response)

    analysis = LLMAnalysis(
        id=str(uuid.uuid4()),
        underlying_symbol=symbol,
        analysis_type="entry_recommendation",
        model=model,
        prompt_version=PROMPT_VERSION,
        context_snapshot=context,
        raw_response=raw_response,
        past_performance_summary=feedback_summary or None,
        recommendation=parsed.get("recommendation"),
        confidence_score=parsed.get("confidence"),
        strategy_suggested=parsed.get("strategy"),
        reasoning_summary=parsed.get("reasoning"),
        suggested_entry=parsed.get("entry_price"),
        suggested_stop=parsed.get("stop_price"),
        suggested_target=parsed.get("target_price"),
        created_at=datetime.now(timezone.utc),
    )

    _persist_analysis(analysis)
    return analysis


def _persist_analysis(analysis: LLMAnalysis) -> None:
    """Write an LLMAnalysis to the llm_analyses table."""
    from magpie.db.connection import get_connection

    conn = get_connection()
    conn.execute(
        """
        INSERT INTO llm_analyses (
            id, created_at, underlying_symbol, analysis_type,
            model, prompt_version, context_snapshot, past_performance_summary,
            raw_response, recommendation, confidence_score, strategy_suggested,
            reasoning_summary, suggested_entry, suggested_stop, suggested_target
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            analysis.id,
            analysis.created_at,
            analysis.underlying_symbol,
            analysis.analysis_type,
            analysis.model,
            analysis.prompt_version,
            json.dumps(analysis.context_snapshot),
            json.dumps(analysis.past_performance_summary) if analysis.past_performance_summary else None,
            analysis.raw_response,
            analysis.recommendation,
            analysis.confidence_score,
            analysis.strategy_suggested,
            analysis.reasoning_summary,
            analysis.suggested_entry,
            analysis.suggested_stop,
            analysis.suggested_target,
        ],
    )


def mark_outcome(analysis_id: str, was_correct: bool, notes: str | None = None) -> None:
    """Record the outcome of a prediction (call after a trade closes)."""
    from magpie.db.connection import get_connection

    conn = get_connection()
    conn.execute(
        """
        UPDATE llm_analyses
        SET was_correct = ?, outcome_notes = ?, outcome_recorded_at = NOW()
        WHERE id = ?
        """,
        [was_correct, notes, analysis_id],
    )
