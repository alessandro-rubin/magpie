"""Greeks dashboard page."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from magpie.dashboard.data import (
    get_contract_snapshots_df,
    get_contracts_for_symbol,
    get_greeks_exposure_df,
    get_iv_history_df,
    get_symbols,
)

st.header("Greeks Dashboard")

# ── Portfolio Greeks Exposure ────────────────────────────────────────────────
st.subheader("Portfolio Greeks Exposure (Open Positions)")

exposure_df = get_greeks_exposure_df()

if exposure_df.empty:
    st.info("No open option positions with Greeks data.")
else:
    greeks = ["total_delta", "total_theta", "total_vega", "total_gamma"]
    labels = ["Delta", "Theta", "Vega", "Gamma"]

    fig = go.Figure()
    for greek, label in zip(greeks, labels):
        fig.add_trace(
            go.Bar(
                x=exposure_df["underlying_symbol"],
                y=exposure_df[greek],
                name=label,
            )
        )

    fig.update_layout(
        barmode="group",
        height=400,
        template="plotly_dark",
        xaxis_title="Symbol",
        yaxis_title="Exposure",
        margin={"l": 60, "r": 20, "t": 20, "b": 40},
    )
    st.plotly_chart(fig, use_container_width=True)

    # Net portfolio summary
    st.markdown("**Net Portfolio Greeks:**")
    cols = st.columns(4)
    for i, (greek, label) in enumerate(zip(greeks, labels)):
        total = float(exposure_df[greek].sum())
        cols[i].metric(label, f"{total:+,.1f}")

# ── IV History ───────────────────────────────────────────────────────────────
st.divider()
st.subheader("Implied Volatility History")

symbols = get_symbols()

if not symbols:
    st.info("No symbols in the database yet.")
    st.stop()

selected_symbol = st.sidebar.selectbox("Symbol", symbols, key="greeks_symbol")
days = st.sidebar.selectbox("Days back", [30, 60, 90, 180], index=2, key="greeks_days")

iv_df = get_iv_history_df(selected_symbol, days=days)

if iv_df.empty:
    st.info(f"No option snapshot data for {selected_symbol} in the last {days} days.")
else:
    # Build a trace per contract (strike + type)
    iv_df["label"] = (
        iv_df["option_type"].str.upper()
        + " $"
        + iv_df["strike_price"].astype(str)
        + " ("
        + iv_df["expiration_date"].astype(str).str[:10]
        + ")"
    )

    fig_iv = go.Figure()
    for label, group in iv_df.groupby("label"):
        fig_iv.add_trace(
            go.Scatter(
                x=group["snapshot_time"],
                y=group["implied_volatility"],
                mode="lines",
                name=str(label),
                opacity=0.7,
            )
        )

    fig_iv.update_layout(
        height=400,
        template="plotly_dark",
        xaxis_title="Time",
        yaxis_title="IV",
        yaxis_tickformat=".1%",
        margin={"l": 60, "r": 20, "t": 20, "b": 40},
        legend={"font": {"size": 10}},
    )
    st.plotly_chart(fig_iv, use_container_width=True)

# ── Single Contract Greeks Over Time ─────────────────────────────────────────
st.divider()
st.subheader("Contract Greeks Over Time")

contracts_df = get_contracts_for_symbol(selected_symbol)

if contracts_df.empty:
    st.info(f"No option contracts found for {selected_symbol}.")
else:
    contract_labels = {
        f"{row['option_type'].upper()} ${row['strike_price']} "
        f"({str(row['expiration_date'])[:10]})": row["contract_id"]
        for _, row in contracts_df.iterrows()
    }

    selected_contract_label = st.sidebar.selectbox(
        "Contract", list(contract_labels.keys()), key="greeks_contract"
    )
    contract_id = contract_labels[selected_contract_label]

    snap_df = get_contract_snapshots_df(contract_id, days=days)

    if snap_df.empty:
        st.info("No snapshot data for this contract.")
    else:
        fig_greeks = go.Figure()
        greek_cols = [
            ("delta", "Delta", "#26a69a"),
            ("theta", "Theta", "#ef5350"),
            ("vega", "Vega", "#42a5f5"),
        ]
        for col, name, color in greek_cols:
            if col in snap_df.columns and snap_df[col].notna().any():
                fig_greeks.add_trace(
                    go.Scatter(
                        x=snap_df["snapshot_time"],
                        y=snap_df[col],
                        mode="lines",
                        name=name,
                        line={"color": color, "width": 2},
                    )
                )

        fig_greeks.update_layout(
            height=350,
            template="plotly_dark",
            xaxis_title="Time",
            yaxis_title="Greek Value",
            margin={"l": 60, "r": 20, "t": 20, "b": 40},
        )
        st.plotly_chart(fig_greeks, use_container_width=True)
