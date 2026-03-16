"""LLM API integration — run analysis and persist results.

Supports multiple providers via LLM_PROVIDER setting:
  - "anthropic" (default): Claude models via Anthropic SDK
  - "groq": Llama/Mixtral models via Groq SDK (openai-compatible)

If the configured provider's API key is not set, run_analysis() raises LLMKeyMissing.
The CLI handles this by printing the formatted prompt for manual use in Claude Code.
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone


def _json_default(obj: object) -> str:
    """Handle datetime/date objects in json.dumps."""
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

from tenacity import retry, retry_if_not_exception_type, stop_after_attempt, wait_exponential

from magpie.analysis.prompts import (
    PROMPT_VERSION,
    SYSTEM_PROMPT,
    format_analysis_prompt,
)
from magpie.db.models import LLMAnalysis


class LLMKeyMissing(RuntimeError):
    """Raised when the configured LLM provider's API key is not set."""


# Backward-compat alias
AnthropicKeyMissing = LLMKeyMissing


def _get_anthropic_client():  # type: ignore[return]
    from magpie.config import settings

    if not settings.anthropic_api_key:
        raise LLMKeyMissing(
            "ANTHROPIC_API_KEY is not set. "
            "Add it to .env to enable standalone analysis, "
            "or use Claude Code interactively with the Alpaca MCP server."
        )

    import anthropic

    return anthropic.Anthropic(api_key=settings.anthropic_api_key)


def _get_groq_client():  # type: ignore[return]
    from magpie.config import settings

    if not settings.groq_api_key:
        raise LLMKeyMissing(
            "GROQ_API_KEY is not set. "
            "Add it to .env when using LLM_PROVIDER=groq."
        )

    from groq import Groq

    return Groq(api_key=settings.groq_api_key)


def _call_api_anthropic(model: str, prompt: str) -> str:
    client = _get_anthropic_client()
    message = client.messages.create(
        model=model,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def _call_api_groq(model: str, prompt: str) -> str:
    client = _get_groq_client()
    response = client.chat.completions.create(
        model=model,
        max_tokens=1024,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
    )
    return response.choices[0].message.content


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=15),
    retry=retry_if_not_exception_type(LLMKeyMissing),
)
def _call_api(model: str, prompt: str) -> str:
    """Call the configured LLM provider and return the raw text response."""
    from magpie.config import settings

    if settings.llm_provider == "groq":
        return _call_api_groq(model, prompt)
    return _call_api_anthropic(model, prompt)


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
    from magpie.analysis.feedback import get_combined_feedback

    feedback_summary = get_combined_feedback(symbol=symbol, window_days=30)

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

    Uses the provider configured via LLM_PROVIDER (default: anthropic).
    Raises LLMKeyMissing if the provider's API key is not configured.
    In that case, use build_prompt() to get the prompt text for manual use.
    """
    from magpie.analysis.feedback import get_combined_feedback
    from magpie.config import settings

    feedback_summary = get_combined_feedback(symbol=symbol, window_days=30)

    prompt = format_analysis_prompt(
        symbol=symbol,
        context=context,
        feedback_summary=feedback_summary,
    )

    model = settings.groq_model if settings.llm_provider == "groq" else settings.anthropic_model
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
            json.dumps(analysis.context_snapshot, default=_json_default),
            json.dumps(analysis.past_performance_summary, default=_json_default) if analysis.past_performance_summary else None,
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
    conn.commit()


def mark_outcome(analysis_id: str, was_correct: bool, notes: str | None = None) -> None:
    """Record the outcome of a prediction (call after a trade closes)."""
    from magpie.db.connection import get_connection

    conn = get_connection()
    conn.execute(
        """
        UPDATE llm_analyses
        SET was_correct = ?, outcome_notes = ?, outcome_recorded_at = datetime('now')
        WHERE id = ?
        """,
        [was_correct, notes, analysis_id],
    )
    conn.commit()
