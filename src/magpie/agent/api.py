"""FastAPI HTTP server exposing Magpie tools as REST endpoints.

Serves as the backend for OpenClaw skill integration and any other
HTTP-based agent framework. Run with:

    uv run magpie-api
    # or
    uv run python scripts/run_api.py

OpenClaw skill definition lives in skills/magpie/skill.yaml.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Magpie Trading API",
    description="Options trading capabilities exposed for agentic integrations (OpenClaw, etc.)",
    version="1.0.0",
)


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------


def _check_api_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    """Validate X-API-Key header. If MAGPIE_API_KEY is unset, no auth is required."""
    from magpie.config import settings

    if settings.magpie_api_key and x_api_key != settings.magpie_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key",
        )


Auth = Annotated[None, Depends(_check_api_key)]


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class AnalyzeRequest(BaseModel):
    symbol: str


class TradeApprovalRequest(BaseModel):
    limit_price: float | None = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/portfolio", dependencies=[Depends(_check_api_key)])
def get_portfolio() -> JSONResponse:
    """Return current account equity, buying power, and open position count."""
    from magpie.db.connection import get_connection
    from magpie.market.client import get_trading_client

    try:
        client = get_trading_client()
        account = client.get_account()
        equity = float(account.equity)
        cash = float(account.cash)
        buying_power = float(account.buying_power)
    except Exception as exc:
        logger.warning("Could not fetch Alpaca account: %s", exc)
        equity = cash = buying_power = 0.0

    conn = get_connection()
    open_count = conn.execute(
        "SELECT COUNT(*) FROM trade_journal WHERE status = 'open'"
    ).fetchone()[0]
    pending_count = conn.execute(
        "SELECT COUNT(*) FROM trade_journal WHERE status = 'pending_approval'"
    ).fetchone()[0]

    return JSONResponse({
        "equity": equity,
        "cash": cash,
        "buying_power": buying_power,
        "open_positions": open_count,
        "pending_approval": pending_count,
    })


@app.post("/analyze", dependencies=[Depends(_check_api_key)])
def analyze_symbol(request: AnalyzeRequest) -> JSONResponse:
    """Analyze a stock symbol and return an LLM options trading recommendation."""
    from magpie.analysis.llm import LLMKeyMissing, run_analysis
    from magpie.market.snapshots import build_analysis_context

    symbol = request.symbol.upper()
    try:
        context = build_analysis_context(symbol)
        analysis = run_analysis(symbol, context)
    except LLMKeyMissing as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Analysis failed for %s", symbol)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return JSONResponse({
        "id": analysis.id,
        "symbol": analysis.underlying_symbol,
        "recommendation": analysis.recommendation,
        "confidence": analysis.confidence_score,
        "strategy": analysis.strategy_suggested,
        "reasoning": analysis.reasoning_summary,
        "entry_price": analysis.suggested_entry,
        "stop_price": analysis.suggested_stop,
        "target_price": analysis.suggested_target,
        "model": analysis.model,
        "prompt_version": analysis.prompt_version,
    })


@app.get("/positions", dependencies=[Depends(_check_api_key)])
def list_positions() -> JSONResponse:
    """List open trades from the journal."""
    from magpie.db.connection import get_connection

    conn = get_connection()
    rows = conn.execute(
        """
        SELECT id, underlying_symbol, strategy_type, entry_price, quantity,
               unrealized_pnl, entry_time, dte_at_entry, entry_delta
        FROM trade_journal
        WHERE status = 'open'
        ORDER BY entry_time DESC
        """
    ).fetchall()

    positions = [
        {
            "id": r[0],
            "symbol": r[1],
            "strategy": r[2],
            "entry_price": r[3],
            "quantity": r[4],
            "unrealized_pnl": r[5],
            "entry_time": str(r[6]) if r[6] else None,
            "dte_at_entry": r[7],
            "entry_delta": r[8],
        }
        for r in rows
    ]
    return JSONResponse({"positions": positions})


@app.post("/sync", dependencies=[Depends(_check_api_key)])
def sync_positions() -> JSONResponse:
    """Sync Alpaca positions with the local trade journal."""
    from magpie.tracking.positions import sync_from_alpaca

    try:
        result = sync_from_alpaca()
        return JSONResponse(result)
    except Exception as exc:
        logger.exception("Sync failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/pending", dependencies=[Depends(_check_api_key)])
def list_pending() -> JSONResponse:
    """List trades awaiting human approval."""
    from magpie.db.connection import get_connection

    conn = get_connection()
    rows = conn.execute(
        """
        SELECT id, underlying_symbol, strategy_type, entry_price, quantity,
               entry_time, notes, entry_rationale
        FROM trade_journal
        WHERE status = 'pending_approval'
        ORDER BY entry_time DESC
        """
    ).fetchall()

    trades = [
        {
            "id": r[0],
            "symbol": r[1],
            "strategy": r[2],
            "entry_price": r[3],
            "quantity": r[4],
            "entry_time": str(r[5]) if r[5] else None,
            "notes": r[6],
            "rationale": r[7],
        }
        for r in rows
    ]
    return JSONResponse({"pending": trades})


@app.post("/approve/{trade_id}", dependencies=[Depends(_check_api_key)])
def approve_trade(trade_id: str, request: TradeApprovalRequest | None = None) -> JSONResponse:
    """Approve a pending trade and place the order via Alpaca."""
    from magpie.db.connection import get_connection
    from magpie.execution.orders import place_multileg_order, place_single_option_order
    from magpie.tracking.journal import update_trade_status
    import json as _json

    conn = get_connection()
    row = conn.execute(
        "SELECT id, underlying_symbol, legs, quantity FROM trade_journal WHERE id = ? AND status = 'pending_approval'",
        [trade_id],
    ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Pending trade not found")

    _, symbol, legs_json, quantity = row
    legs = _json.loads(legs_json) if legs_json else []
    limit_price = request.limit_price if request else None

    try:
        if len(legs) > 1:
            order_legs = [
                {"contract_id": leg["contract_symbol"], "action": leg["side"], "qty": abs(leg["quantity"])}
                for leg in legs
            ]
            order = place_multileg_order(order_legs, limit_price=limit_price)
        elif len(legs) == 1:
            leg = legs[0]
            order = place_single_option_order(
                leg["contract_symbol"], leg["side"], abs(leg["quantity"]), limit_price=limit_price
            )
        else:
            raise HTTPException(status_code=400, detail="Trade has no legs defined")

        update_trade_status(trade_id, status="open")
        conn.execute(
            "UPDATE trade_journal SET alpaca_order_id = ?, updated_at = datetime('now') WHERE id = ?",
            [order["id"], trade_id],
        )
        conn.commit()
        return JSONResponse({"approved": True, "trade_id": trade_id, "order": order})

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Order placement failed for %s", trade_id)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/reject/{trade_id}", dependencies=[Depends(_check_api_key)])
def reject_trade(trade_id: str) -> JSONResponse:
    """Reject a pending trade (marks it cancelled without placing an order)."""
    from magpie.db.connection import get_connection
    from magpie.tracking.journal import update_trade_status

    conn = get_connection()
    row = conn.execute(
        "SELECT id FROM trade_journal WHERE id = ? AND status = 'pending_approval'",
        [trade_id],
    ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Pending trade not found")

    update_trade_status(trade_id, status="cancelled")
    return JSONResponse({"rejected": True, "trade_id": trade_id})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    import uvicorn
    from magpie.config import settings

    uvicorn.run(app, host="127.0.0.1", port=settings.magpie_api_port, log_level="info")


if __name__ == "__main__":
    main()
