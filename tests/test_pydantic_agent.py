"""Tests for the PydanticAI agent framework (agent/pydantic_agent.py).

These tests use PydanticAI's TestModel so no real API calls are made.
TestModel returns a valid TradeRecommendation by filling Pydantic fields
with sensible defaults, letting us test the agent wiring without a live key.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydantic_ai.models.test import TestModel

from magpie.agent.pydantic_agent import (
    LLMKeyMissing,
    MagpieDeps,
    TradeLeg,
    TradeRecommendation,
    _get_model_name,
    _persist_result,
    magpie_agent,
    run_pydantic_analysis,
)


# ---------------------------------------------------------------------------
# Pydantic model validation — no API or DB needed
# ---------------------------------------------------------------------------


class TestTradeRecommendation:
    def test_valid_avoid(self):
        rec = TradeRecommendation(
            recommendation="avoid",
            confidence=0.3,
            strategy="none",
            reasoning="No clear catalyst.",
        )
        assert rec.recommendation == "avoid"
        assert rec.legs == []
        assert rec.risk_check_passed is False

    def test_valid_enter_with_legs(self):
        rec = TradeRecommendation(
            recommendation="enter",
            confidence=0.80,
            strategy="vertical_spread",
            reasoning="Bullish momentum. IV rank low. Risk checked.",
            entry_price=3.50,
            stop_price=180.0,
            target_price=210.0,
            legs=[
                TradeLeg(
                    action="buy", option_type="call", strike=200.0,
                    expiry="2026-06-20", target_delta=0.40,
                ),
                TradeLeg(
                    action="sell", option_type="call", strike=210.0,
                    expiry="2026-06-20", target_delta=0.20,
                ),
            ],
            risk_check_passed=True,
        )
        assert len(rec.legs) == 2
        assert rec.risk_check_passed is True

    def test_confidence_out_of_range_raises(self):
        with pytest.raises(Exception):
            TradeRecommendation(
                recommendation="enter",
                confidence=1.5,  # > 1.0
                strategy="long_call",
                reasoning="Test.",
            )

    def test_negative_confidence_raises(self):
        with pytest.raises(Exception):
            TradeRecommendation(
                recommendation="avoid",
                confidence=-0.1,
                strategy="none",
                reasoning="Test.",
            )

    def test_all_recommendation_literals(self):
        for action in ("enter", "avoid", "hold", "reduce"):
            rec = TradeRecommendation(
                recommendation=action,  # type: ignore[arg-type]
                confidence=0.5,
                strategy="test",
                reasoning="Test.",
            )
            assert rec.recommendation == action


class TestTradeLeg:
    def test_valid_call_leg(self):
        leg = TradeLeg(action="buy", option_type="call", strike=150.0, expiry="2026-05-16")
        assert leg.option_type == "call"
        assert leg.target_delta is None

    def test_valid_put_leg_with_delta(self):
        leg = TradeLeg(
            action="sell", option_type="put", strike=140.0,
            expiry="2026-05-16", target_delta=-0.30,
        )
        assert leg.target_delta == pytest.approx(-0.30)

    def test_invalid_action_raises(self):
        with pytest.raises(Exception):
            TradeLeg(action="hold", option_type="call", strike=100.0, expiry="2026-05-16")  # type: ignore[arg-type]

    def test_delta_out_of_range_raises(self):
        with pytest.raises(Exception):
            TradeLeg(
                action="buy", option_type="call", strike=100.0,
                expiry="2026-05-16", target_delta=1.5,  # > 1.0
            )

    def test_strike_must_be_positive(self):
        with pytest.raises(Exception):
            TradeLeg(action="buy", option_type="call", strike=-10.0, expiry="2026-05-16")


class TestMagpieDeps:
    def test_defaults(self):
        deps = MagpieDeps(symbol="AAPL")
        assert deps.symbol == "AAPL"
        assert deps.equity == 100_000.0
        assert deps.daily_pnl == 0.0

    def test_custom_values(self):
        deps = MagpieDeps(symbol="SPY", equity=50_000.0, daily_pnl=-800.0)
        assert deps.equity == 50_000.0
        assert deps.daily_pnl == -800.0


# ---------------------------------------------------------------------------
# _get_model_name — provider routing and key validation
# ---------------------------------------------------------------------------


class _MockSettings:
    def __init__(
        self,
        provider="anthropic",
        anthropic_key="sk-ant-test",
        groq_key=None,
        anthropic_model="claude-opus-4-6",
        groq_model="llama-3.3-70b-versatile",
    ):
        self.llm_provider = provider
        self.anthropic_api_key = anthropic_key
        self.groq_api_key = groq_key
        self.anthropic_model = anthropic_model
        self.groq_model = groq_model


def test_get_model_name_anthropic():
    # settings is imported at module level, so we patch it there
    import magpie.agent.pydantic_agent as mod
    orig = mod.settings
    mod.settings = _MockSettings()
    try:
        model = _get_model_name()
    finally:
        mod.settings = orig
    assert "Anthropic" in type(model).__name__


def test_get_model_name_groq():
    import magpie.agent.pydantic_agent as mod
    orig = mod.settings
    mod.settings = _MockSettings(provider="groq", groq_key="gsk_test", anthropic_key=None)
    try:
        model = _get_model_name()
    finally:
        mod.settings = orig
    assert "Groq" in type(model).__name__


def test_get_model_name_missing_anthropic_key_raises():
    import magpie.agent.pydantic_agent as mod
    orig = mod.settings
    mod.settings = _MockSettings(anthropic_key=None)
    try:
        with pytest.raises(LLMKeyMissing):
            _get_model_name()
    finally:
        mod.settings = orig


def test_get_model_name_missing_groq_key_raises():
    import magpie.agent.pydantic_agent as mod
    orig = mod.settings
    mod.settings = _MockSettings(provider="groq", groq_key=None, anthropic_key=None)
    try:
        with pytest.raises(LLMKeyMissing):
            _get_model_name()
    finally:
        mod.settings = orig


# ---------------------------------------------------------------------------
# Agent integration tests using TestModel (no real API)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_returns_recommendation():
    """Agent should produce a valid TradeRecommendation via TestModel.

    call_tools=[] prevents the TestModel from simulating tool calls,
    so no real market data or DB access is attempted.
    """
    deps = MagpieDeps(symbol="AAPL", equity=100_000.0)

    result = await magpie_agent.run(
        "Analyze AAPL.",
        deps=deps,
        model=TestModel(call_tools=[]),
    )

    assert isinstance(result.output, TradeRecommendation)
    assert result.output.recommendation in ("enter", "avoid", "hold", "reduce")
    assert 0.0 <= result.output.confidence <= 1.0
    assert isinstance(result.output.strategy, str)
    assert isinstance(result.output.reasoning, str)


@pytest.mark.asyncio
async def test_agent_multiple_symbols():
    """Agent should handle different symbols independently."""
    for symbol in ("SPY", "TSLA", "NVDA"):
        deps = MagpieDeps(symbol=symbol)
        result = await magpie_agent.run(
            f"Analyze {symbol}.",
            deps=deps,
            model=TestModel(call_tools=[]),
        )
        assert isinstance(result.output, TradeRecommendation)


@pytest.mark.asyncio
async def test_agent_result_is_validated():
    """TestModel produces output that passes Pydantic validation."""
    deps = MagpieDeps(symbol="QQQ")
    result = await magpie_agent.run(
        "Analyze QQQ.", deps=deps, model=TestModel(call_tools=[])
    )
    rec = result.output
    assert 0.0 <= rec.confidence <= 1.0
    assert isinstance(rec.legs, list)


@pytest.mark.asyncio
async def test_agent_via_override_context_manager():
    """agent.override() context manager is an alternative to passing model= to run()."""
    deps = MagpieDeps(symbol="IWM")
    with magpie_agent.override(model=TestModel(call_tools=[])):
        result = await magpie_agent.run("Analyze IWM.", deps=deps)
    assert isinstance(result.output, TradeRecommendation)


# ---------------------------------------------------------------------------
# run_pydantic_analysis
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_no_persist():
    """run_pydantic_analysis with persist=False should not touch the DB."""
    rec = await run_pydantic_analysis("AAPL", persist=False, model=TestModel(call_tools=[]))
    assert isinstance(rec, TradeRecommendation)


@pytest.mark.asyncio
async def test_run_with_persist(db):
    """run_pydantic_analysis with persist=True should write to llm_analyses."""
    import magpie.agent.pydantic_agent as mod
    orig_conn = mod.get_connection
    orig_settings = mod.settings
    mod.get_connection = lambda: db
    mod.settings = _MockSettings()
    try:
        rec = await run_pydantic_analysis("MSFT", persist=True, model=TestModel(call_tools=[]))
    finally:
        mod.get_connection = orig_conn
        mod.settings = orig_settings

    assert isinstance(rec, TradeRecommendation)
    rows = db.execute(
        "SELECT recommendation, analysis_type FROM llm_analyses "
        "WHERE underlying_symbol = 'MSFT' AND analysis_type = 'pydantic_ai_recommendation'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == rec.recommendation


@pytest.mark.asyncio
async def test_run_raises_when_no_key():
    """run_pydantic_analysis raises LLMKeyMissing when no model override and key absent."""
    import magpie.agent.pydantic_agent as mod
    orig = mod.settings
    mod.settings = _MockSettings(anthropic_key=None)
    try:
        with pytest.raises(LLMKeyMissing):
            await run_pydantic_analysis("AAPL")  # no model= override, triggers _get_model_name
    finally:
        mod.settings = orig


# ---------------------------------------------------------------------------
# _persist_result
# ---------------------------------------------------------------------------


def test_persist_result_writes_row(db):
    """_persist_result should insert one row into llm_analyses."""
    import magpie.agent.pydantic_agent as mod

    rec = TradeRecommendation(
        recommendation="avoid",
        confidence=0.4,
        strategy="vertical_spread",
        reasoning="IV too high.",
    )
    mock_result = MagicMock()
    mock_result.all_messages.return_value = ["msg1", "msg2"]

    orig_conn = mod.get_connection
    orig_settings = mod.settings
    mod.get_connection = lambda: db
    mod.settings = _MockSettings()
    try:
        _persist_result("GOOG", rec, mock_result)
    finally:
        mod.get_connection = orig_conn
        mod.settings = orig_settings

    rows = db.execute(
        "SELECT underlying_symbol, recommendation, confidence_score "
        "FROM llm_analyses WHERE underlying_symbol = 'GOOG'"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][1] == "avoid"
    assert rows[0][2] == pytest.approx(0.4)


def test_persist_result_groq_records_model_name(db):
    """_persist_result should store the groq model name when provider=groq."""
    import magpie.agent.pydantic_agent as mod

    rec = TradeRecommendation(
        recommendation="enter",
        confidence=0.7,
        strategy="iron_condor",
        reasoning="Range-bound market.",
    )
    mock_result = MagicMock()
    mock_result.all_messages.return_value = []

    orig_conn = mod.get_connection
    orig_settings = mod.settings
    mod.get_connection = lambda: db
    mod.settings = _MockSettings(
        provider="groq", groq_key="gsk_test", groq_model="llama-3.3-70b-versatile",
    )
    try:
        _persist_result("IWM", rec, mock_result)
    finally:
        mod.get_connection = orig_conn
        mod.settings = orig_settings

    row = db.execute(
        "SELECT model FROM llm_analyses WHERE underlying_symbol = 'IWM'"
    ).fetchone()
    assert row is not None
    assert row[0] == "llama-3.3-70b-versatile"
