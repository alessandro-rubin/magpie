"""Strategy win rate charts page."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from magpie.dashboard.data import (
    get_pnl_distribution_df,
    get_winrate_by_prompt_df,
    get_winrate_by_strategy_df,
    get_winrate_by_symbol_df,
)

st.header("Win Rates & Performance")

# Sidebar controls
days = st.sidebar.selectbox("Time window (days)", [30, 60, 90, 180, 365], index=2, key="wr_days")

# ── Win Rate by Strategy ─────────────────────────────────────────────────────
st.subheader("Win Rate by Strategy Type")

strat_df = get_winrate_by_strategy_df(window_days=days)

if strat_df.empty:
    st.info("No closed trades with P&L data in this window.")
else:
    strat_df["win_rate"] = (strat_df["wins"] / strat_df["total"]) * 100

    fig_strat = go.Figure()
    fig_strat.add_trace(
        go.Bar(
            y=strat_df["strategy_type"],
            x=strat_df["win_rate"],
            orientation="h",
            marker_color=[
                "#26a69a" if wr >= 50 else "#ef5350" for wr in strat_df["win_rate"]
            ],
            text=[
                f"{wr:.0f}% ({n} trades)" for wr, n in zip(strat_df["win_rate"], strat_df["total"])
            ],
            textposition="auto",
        )
    )
    fig_strat.update_layout(
        height=max(250, len(strat_df) * 50),
        template="plotly_dark",
        xaxis_title="Win Rate %",
        xaxis_range=[0, 100],
        margin={"l": 150, "r": 20, "t": 20, "b": 40},
    )
    st.plotly_chart(fig_strat, use_container_width=True)

# ── Rolling Win Rate Over Time ───────────────────────────────────────────────
st.divider()
st.subheader("Rolling Win Rate (10-Trade Window)")

pnl_df = get_pnl_distribution_df(window_days=days)

if pnl_df.empty or len(pnl_df) < 3:
    st.info("Need at least 3 closed trades to show a rolling win rate.")
else:
    pnl_df["is_win"] = (pnl_df["realized_pnl"] > 0).astype(float)
    window = min(10, len(pnl_df))
    pnl_df["rolling_wr"] = pnl_df["is_win"].rolling(window=window, min_periods=2).mean() * 100

    fig_roll = go.Figure()
    fig_roll.add_trace(
        go.Scatter(
            x=pnl_df["exit_time"],
            y=pnl_df["rolling_wr"],
            mode="lines+markers",
            line={"color": "#42a5f5", "width": 2},
            marker={"size": 4},
            name="Rolling Win Rate",
        )
    )
    fig_roll.add_hline(y=50, line_dash="dash", line_color="white", opacity=0.3)
    fig_roll.update_layout(
        height=350,
        template="plotly_dark",
        xaxis_title="Exit Time",
        yaxis_title="Win Rate %",
        yaxis_range=[0, 100],
        margin={"l": 60, "r": 20, "t": 20, "b": 40},
    )
    st.plotly_chart(fig_roll, use_container_width=True)

# ── Win Rate by Prompt Version ───────────────────────────────────────────────
st.divider()
st.subheader("Win Rate by Prompt Version")

prompt_df = get_winrate_by_prompt_df()

if prompt_df.empty:
    st.info("No LLM analysis outcomes recorded yet.")
else:
    prompt_df["win_rate"] = (prompt_df["wins"] / prompt_df["total"]) * 100

    fig_prompt = go.Figure()
    fig_prompt.add_trace(
        go.Bar(
            x=prompt_df["prompt_version"],
            y=prompt_df["win_rate"],
            marker_color="#ab47bc",
            text=[
                f"{wr:.0f}% ({n})" for wr, n in zip(prompt_df["win_rate"], prompt_df["total"])
            ],
            textposition="auto",
        )
    )
    fig_prompt.update_layout(
        height=300,
        template="plotly_dark",
        xaxis_title="Prompt Version",
        yaxis_title="Win Rate %",
        yaxis_range=[0, 100],
        margin={"l": 60, "r": 20, "t": 20, "b": 40},
    )
    st.plotly_chart(fig_prompt, use_container_width=True)

# ── P&L Distribution ─────────────────────────────────────────────────────────
st.divider()
st.subheader("P&L Distribution (Return %)")

if pnl_df.empty:
    st.info("No closed trades with return data.")
else:
    fig_hist = go.Figure()
    fig_hist.add_trace(
        go.Histogram(
            x=pnl_df["return_pct"],
            nbinsx=30,
            marker_color="#42a5f5",
            opacity=0.8,
        )
    )
    fig_hist.add_vline(x=0, line_dash="solid", line_color="white", line_width=2)
    median_ret = float(pnl_df["return_pct"].median())
    fig_hist.add_vline(x=median_ret, line_dash="dash", line_color="#ffab40", opacity=0.7)
    fig_hist.add_annotation(
        x=median_ret, y=0, yref="paper", yanchor="bottom",
        text=f"Median: {median_ret:.1f}%", showarrow=False, font={"color": "#ffab40"},
    )
    fig_hist.update_layout(
        height=350,
        template="plotly_dark",
        xaxis_title="Return %",
        yaxis_title="Count",
        margin={"l": 60, "r": 20, "t": 20, "b": 40},
    )
    st.plotly_chart(fig_hist, use_container_width=True)

# ── Win Rate by Symbol ───────────────────────────────────────────────────────
st.divider()
st.subheader("Win Rate by Symbol")

sym_df = get_winrate_by_symbol_df(window_days=days)

if sym_df.empty:
    st.info("No data.")
else:
    sym_df["win_rate"] = (sym_df["wins"] / sym_df["total"]) * 100

    fig_sym = go.Figure()
    fig_sym.add_trace(
        go.Bar(
            x=sym_df["underlying_symbol"],
            y=sym_df["win_rate"],
            marker_color=[
                "#26a69a" if wr >= 50 else "#ef5350" for wr in sym_df["win_rate"]
            ],
            text=[
                f"{wr:.0f}% ({n})" for wr, n in zip(sym_df["win_rate"], sym_df["total"])
            ],
            textposition="auto",
        )
    )
    fig_sym.update_layout(
        height=350,
        template="plotly_dark",
        xaxis_title="Symbol",
        yaxis_title="Win Rate %",
        yaxis_range=[0, 100],
        margin={"l": 60, "r": 20, "t": 20, "b": 40},
    )
    st.plotly_chart(fig_sym, use_container_width=True)
