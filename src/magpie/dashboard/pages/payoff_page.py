"""Options payoff diagram page."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from magpie.dashboard.data import get_trades_with_legs_df
from magpie.dashboard.payoff import compute_payoff, find_breakevens, price_range_for_legs

st.header("Payoff Diagrams")

df = get_trades_with_legs_df()

if df.empty:
    st.info("No trades with leg data found. Record trades with `legs` to see payoff diagrams.")
    st.stop()

# Parse legs JSON and build trade selector options
trade_options: dict[str, dict] = {}
for _, row in df.iterrows():
    try:
        legs = json.loads(row["legs"]) if isinstance(row["legs"], str) else row["legs"]
        if not legs or not isinstance(legs, list):
            continue
        # Validate required fields
        for leg in legs:
            _ = leg["option_type"], leg["strike_price"], leg["quantity"], leg["premium"]
    except (json.JSONDecodeError, KeyError, TypeError):
        continue

    label = (
        f"{row['underlying_symbol']} — {row['strategy_type'] or 'unknown'} "
        f"({row['status']}) — {str(row.get('entry_time', ''))[:10]}"
    )
    trade_options[label] = {
        "legs": legs,
        "underlying_price": float(row["entry_underlying_price"])
        if pd.notna(row.get("entry_underlying_price"))
        else None,
        "current_underlying_price": float(row["current_underlying_price"])
        if pd.notna(row.get("current_underlying_price"))
        else None,
        "unrealized_pnl": float(row["unrealized_pnl"])
        if pd.notna(row.get("unrealized_pnl"))
        else None,
        "realized_pnl": float(row["realized_pnl"])
        if pd.notna(row.get("realized_pnl"))
        else None,
        "updated_at": str(row["updated_at"])[:16] if pd.notna(row.get("updated_at")) else None,
        "id": row["id"],
        "status": row["status"],
    }

if not trade_options:
    st.info(
        "No trades have valid leg data (need option_type, strike_price, quantity, premium per leg)."
    )
    st.stop()

# Trade selector
selected_label = st.sidebar.selectbox("Select trade", list(trade_options.keys()))
show_legs = st.sidebar.checkbox("Show individual legs", value=False)

trade = trade_options[selected_label]
legs = trade["legs"]
underlying_price = trade["underlying_price"]
current_price = trade["current_underlying_price"]
unrealized_pnl = trade["unrealized_pnl"]
realized_pnl = trade["realized_pnl"]
is_closed = trade["status"] == "closed"

# Compute payoff — use current price for centering the chart if available
price_low, price_high = price_range_for_legs(legs, current_price or underlying_price)
prices = np.linspace(price_low, price_high, 500)
pnl = compute_payoff(legs, prices)
breakevens = find_breakevens(legs, price_low, price_high)

max_profit = float(pnl.max())
max_loss = float(pnl.min())

# Summary
if is_closed:
    pnl_col = 1 if realized_pnl is not None else 0
    extra_cols = (1 if current_price else 0) + pnl_col
else:
    extra_cols = (1 if current_price else 0) + (1 if unrealized_pnl is not None else 0)
cols = st.columns(3 + extra_cols)
cols[0].metric("Max Profit", f"${max_profit:,.0f}" if max_profit < 1e8 else "Unlimited")
cols[1].metric("Max Loss", f"${max_loss:,.0f}")
cols[2].metric("Breakeven(s)", ", ".join(f"${b:,.2f}" for b in breakevens) if breakevens else "N/A")
ci = 3
if is_closed:
    if realized_pnl is not None:
        cols[ci].metric("Realized P&L", f"${realized_pnl:,.0f}")
        ci += 1
    if current_price:
        current_pnl_val = float(compute_payoff(legs, np.array([current_price]))[0])
        cols[ci].metric("P&L at Expiry", f"${current_pnl_val:,.0f}", f"exit @ ${current_price:.2f}")
else:
    if unrealized_pnl is not None:
        sync_hint = f"synced {trade['updated_at']}" if trade.get("updated_at") else "last sync"
        cols[ci].metric("Unrealized P&L", f"${unrealized_pnl:,.0f}", sync_hint)
        ci += 1
    if current_price:
        current_pnl_val = float(compute_payoff(legs, np.array([current_price]))[0])
        cols[ci].metric("P&L at Expiry", f"${current_pnl_val:,.0f}", f"if stays @ ${current_price:.2f}")

# Build chart
fig = go.Figure()

# Individual legs (if toggled)
if show_legs:
    for i, leg in enumerate(legs):
        leg_list = [leg]
        leg_pnl = compute_payoff(leg_list, prices)
        leg_label = (
            f"{'Long' if leg['quantity'] > 0 else 'Short'} "
            f"{leg['option_type'].upper()} ${leg['strike_price']}"
        )
        fig.add_trace(
            go.Scatter(
                x=prices,
                y=leg_pnl,
                mode="lines",
                line={"width": 1, "dash": "dot"},
                opacity=0.5,
                name=leg_label,
            )
        )

# Combined payoff — split into profit/loss regions
fig.add_trace(
    go.Scatter(
        x=prices,
        y=np.where(pnl >= 0, pnl, 0),
        mode="lines",
        fill="tozeroy",
        fillcolor="rgba(38, 166, 154, 0.3)",
        line={"color": "#26a69a", "width": 2},
        name="Profit",
    )
)
fig.add_trace(
    go.Scatter(
        x=prices,
        y=np.where(pnl < 0, pnl, 0),
        mode="lines",
        fill="tozeroy",
        fillcolor="rgba(239, 83, 80, 0.3)",
        line={"color": "#ef5350", "width": 2},
        name="Loss",
    )
)

# Breakeven lines
for be in breakevens:
    fig.add_vline(x=be, line_dash="dash", line_color="white", opacity=0.5)
    fig.add_annotation(x=be, y=0, text=f"BE ${be:.2f}", showarrow=False, yshift=15)

# Entry price marker
if underlying_price:
    fig.add_vline(x=underlying_price, line_dash="dot", line_color="#ffab40", opacity=0.7)
    fig.add_annotation(
        x=underlying_price,
        y=max_profit * 0.8,
        text=f"Entry ${underlying_price:.2f}",
        showarrow=False,
        font={"color": "#ffab40"},
    )

# Current / exit underlying price marker
if current_price:
    current_pnl = float(compute_payoff(legs, np.array([current_price]))[0])
    price_label = f"Exit ${current_price:.2f}" if is_closed else f"Now ${current_price:.2f}"
    dot_label = f"Exit P&L ${current_pnl:,.0f}" if is_closed else f"Current P&L ${current_pnl:,.0f}"
    fig.add_vline(x=current_price, line_dash="dash", line_color="#42a5f5", opacity=0.8)
    fig.add_annotation(
        x=current_price,
        y=max_profit * 0.6,
        text=price_label,
        showarrow=False,
        font={"color": "#42a5f5"},
    )
    # Dot on the P&L curve at current/exit price
    fig.add_trace(
        go.Scatter(
            x=[current_price],
            y=[current_pnl],
            mode="markers",
            marker={"color": "#42a5f5", "size": 10, "symbol": "diamond"},
            name=dot_label,
            showlegend=True,
        )
    )

fig.update_layout(
    title="P&L at Expiration",
    xaxis_title="Underlying Price",
    yaxis_title="P&L ($)",
    height=500,
    template="plotly_dark",
    hovermode="x unified",
    margin={"l": 60, "r": 20, "t": 50, "b": 40},
)

st.plotly_chart(fig, use_container_width=True)

# Legs detail table
st.subheader("Legs")
legs_display = []
for leg in legs:
    legs_display.append(
        {
            "Type": leg["option_type"].upper(),
            "Strike": f"${leg['strike_price']}",
            "Qty": leg["quantity"],
            "Premium": f"${leg['premium']:.2f}",
            "Side": "Long" if leg["quantity"] > 0 else "Short",
        }
    )
st.dataframe(legs_display, use_container_width=True, hide_index=True)
