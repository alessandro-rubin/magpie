"""Equity curve & drawdown page."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from magpie.dashboard.data import get_equity_df

st.header("Equity & Drawdown")

# Sidebar controls
days = st.sidebar.selectbox("Time window", [30, 60, 90, 180, 365], index=2)

df = get_equity_df(days=days)

if df.empty:
    st.info(
        "No portfolio snapshots yet. Run `magpie positions sync` during market hours "
        "to start building your equity curve."
    )
    st.stop()

# Compute derived columns
df["peak"] = df["equity"].cummax()
df["drawdown_pct"] = ((df["equity"] - df["peak"]) / df["peak"]) * 100

# Summary metrics
total_return = float(df["equity"].iloc[-1] - df["equity"].iloc[0])
total_return_pct = (total_return / float(df["equity"].iloc[0])) * 100 if float(df["equity"].iloc[0]) else 0
max_dd = float(df["drawdown_pct"].min())
current_equity = float(df["equity"].iloc[-1])

col1, col2, col3, col4 = st.columns(4)
col1.metric("Current Equity", f"${current_equity:,.2f}")
col2.metric("Total Return", f"${total_return:,.2f}", f"{total_return_pct:+.1f}%")
col3.metric("Max Drawdown", f"{max_dd:.1f}%")
col4.metric("Snapshots", len(df))

# Charts — stacked with shared x-axis
fig = make_subplots(
    rows=3,
    cols=1,
    shared_xaxes=True,
    vertical_spacing=0.06,
    row_heights=[0.5, 0.25, 0.25],
    subplot_titles=("Portfolio Equity", "Drawdown %", "Daily Realized P&L"),
)

# Equity line
fig.add_trace(
    go.Scatter(
        x=df["snapshot_date"],
        y=df["equity"],
        mode="lines",
        fill="tozeroy",
        fillcolor="rgba(38, 166, 154, 0.15)",
        line={"color": "#26a69a", "width": 2},
        name="Equity",
    ),
    row=1,
    col=1,
)

# Drawdown
fig.add_trace(
    go.Scatter(
        x=df["snapshot_date"],
        y=df["drawdown_pct"],
        mode="lines",
        fill="tozeroy",
        fillcolor="rgba(239, 83, 80, 0.25)",
        line={"color": "#ef5350", "width": 1.5},
        name="Drawdown %",
    ),
    row=2,
    col=1,
)

# Daily P&L bars
if "realized_pnl_today" in df.columns and df["realized_pnl_today"].notna().any():
    colors = ["#26a69a" if v >= 0 else "#ef5350" for v in df["realized_pnl_today"].fillna(0)]
    fig.add_trace(
        go.Bar(
            x=df["snapshot_date"],
            y=df["realized_pnl_today"],
            marker_color=colors,
            name="Daily P&L",
        ),
        row=3,
        col=1,
    )

fig.update_layout(
    height=750,
    showlegend=False,
    template="plotly_dark",
    margin={"l": 60, "r": 20, "t": 40, "b": 40},
)
fig.update_yaxes(title_text="$", row=1, col=1)
fig.update_yaxes(title_text="%", row=2, col=1)
fig.update_yaxes(title_text="$", row=3, col=1)

st.plotly_chart(fig, use_container_width=True)
