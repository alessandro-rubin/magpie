"""Options payoff diagram page."""

from __future__ import annotations

import json

import numpy as np
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
        if row.get("entry_underlying_price")
        else None,
        "id": row["id"],
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

# Compute payoff
price_low, price_high = price_range_for_legs(legs, underlying_price)
prices = np.linspace(price_low, price_high, 500)
pnl = compute_payoff(legs, prices)
breakevens = find_breakevens(legs, price_low, price_high)

max_profit = float(pnl.max())
max_loss = float(pnl.min())

# Summary
col1, col2, col3 = st.columns(3)
col1.metric("Max Profit", f"${max_profit:,.0f}" if max_profit < 1e8 else "Unlimited")
col2.metric("Max Loss", f"${max_loss:,.0f}")
col3.metric("Breakeven(s)", ", ".join(f"${b:,.2f}" for b in breakevens) if breakevens else "N/A")

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

# Current price marker
if underlying_price:
    fig.add_vline(x=underlying_price, line_dash="dot", line_color="#ffab40", opacity=0.7)
    fig.add_annotation(
        x=underlying_price,
        y=max_profit * 0.8,
        text=f"Entry ${underlying_price:.2f}",
        showarrow=False,
        font={"color": "#ffab40"},
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
