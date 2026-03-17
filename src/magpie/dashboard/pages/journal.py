"""Trade journal browser page."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from magpie.dashboard.data import (
    get_trades_df,
    get_trading_notes_df,
    get_trading_rules_df,
)

st.header("Journal")

tab_trades, tab_notes, tab_rules = st.tabs(["Trades", "Notes", "Rules"])

# ── Trades tab ──────────────────────────────────────────────────
with tab_trades:
    # Filters
    col_status, col_symbol, col_window = st.columns(3)
    with col_status:
        status_filter = st.selectbox(
            "Status",
            ["all", "open", "closed", "pending_approval", "expired", "cancelled"],
        )
    with col_symbol:
        symbol_filter = st.text_input("Symbol", placeholder="e.g. AAPL").strip().upper()
    with col_window:
        window_filter = st.selectbox("Time window", [None, 7, 30, 60, 90, 180, 365], format_func=lambda x: "All time" if x is None else f"Last {x} days")

    df = get_trades_df(
        status=status_filter if status_filter != "all" else None,
        symbol=symbol_filter or None,
        window_days=window_filter,
    )

    if df.empty:
        st.info("No trades found matching filters.")
    else:
        st.caption(f"{len(df)} trade(s)")

        for _, row in df.iterrows():
            pnl = row.get("realized_pnl") if row["status"] == "closed" else row.get("unrealized_pnl")
            pnl_label = ""
            if pd.notna(pnl):
                color = "green" if pnl > 0 else "red" if pnl < 0 else "gray"
                pnl_label = f"  :{color}[${pnl:+,.0f}]"

            header = (
                f"**{row['underlying_symbol']}** — "
                f"{row.get('strategy_type') or 'unknown'} · "
                f"`{row['status']}`{pnl_label}"
            )

            with st.expander(header, expanded=False):
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Entry Price", f"${row['entry_price']:.2f}" if pd.notna(row.get("entry_price")) else "—")
                c2.metric("Qty", int(row["quantity"]) if pd.notna(row.get("quantity")) else "—")
                if row["status"] == "closed" and pd.notna(row.get("exit_price")):
                    c3.metric("Exit Price", f"${row['exit_price']:.2f}")
                elif pd.notna(row.get("current_underlying_price")):
                    c3.metric("Underlying", f"${row['current_underlying_price']:.2f}")
                else:
                    c3.metric("Underlying", "—")
                if pd.notna(row.get("dte_at_entry")):
                    c4.metric("DTE at Entry", int(row["dte_at_entry"]))
                else:
                    c4.metric("DTE at Entry", "—")

                # Greeks
                greeks = {}
                for g in ["delta", "theta", "vega", "gamma", "iv"]:
                    val = row.get(f"entry_{g}")
                    if pd.notna(val):
                        greeks[g] = val
                if greeks:
                    gcols = st.columns(len(greeks))
                    for i, (g, v) in enumerate(greeks.items()):
                        gcols[i].metric(g.capitalize(), f"{v:.3f}" if g != "iv" else f"{v:.1%}")

                # Rationale
                if pd.notna(row.get("entry_rationale")):
                    st.markdown(f"**Entry rationale:** {row['entry_rationale']}")
                if pd.notna(row.get("exit_rationale")):
                    st.markdown(f"**Exit rationale:** {row['exit_rationale']}")
                if pd.notna(row.get("exit_reason")):
                    st.caption(f"Exit reason: {row['exit_reason']}")

                # Legs
                if pd.notna(row.get("legs")):
                    try:
                        legs = json.loads(row["legs"]) if isinstance(row["legs"], str) else row["legs"]
                        if legs:
                            st.markdown("**Legs:**")
                            legs_display = []
                            for leg in legs:
                                if isinstance(leg, str):
                                    leg = json.loads(leg)
                                legs_display.append({
                                    "Type": leg.get("option_type", "").upper(),
                                    "Strike": f"${leg['strike_price']}" if "strike_price" in leg else "—",
                                    "Qty": leg.get("quantity", ""),
                                    "Premium": f"${leg['premium']:.2f}" if "premium" in leg else "—",
                                    "Side": "Long" if leg.get("quantity", 0) > 0 else "Short",
                                })
                            st.dataframe(legs_display, use_container_width=True, hide_index=True)
                    except (json.JSONDecodeError, TypeError):
                        pass

                # Timestamps
                times = []
                if pd.notna(row.get("entry_time")):
                    times.append(f"Entered: {str(row['entry_time'])[:16]}")
                if pd.notna(row.get("exit_time")):
                    times.append(f"Exited: {str(row['exit_time'])[:16]}")
                if times:
                    st.caption(" · ".join(times))

                st.caption(f"ID: `{row['id']}`")


# ── Notes tab ───────────────────────────────────────────────────
with tab_notes:
    show_resolved = st.checkbox("Include resolved", value=False)
    notes_df = get_trading_notes_df(include_resolved=show_resolved)

    if notes_df.empty:
        st.info("No trading notes found. Add notes via `magpie notes add` or the MCP server.")
    else:
        st.caption(f"{len(notes_df)} note(s)")
        for _, note in notes_df.iterrows():
            badge = f"`{note['category']}`"
            resolved = " · ~~resolved~~" if note.get("resolved") else ""
            expires = ""
            if pd.notna(note.get("expires_at")):
                expires = f" · expires {str(note['expires_at'])[:10]}"

            with st.expander(f"{badge} **{note['title']}**{resolved}{expires}", expanded=False):
                st.markdown(note["content"])
                meta = [f"Created: {str(note['created_at'])[:16]}"]
                if pd.notna(note.get("source_trade_id")):
                    meta.append(f"Linked trade: `{note['source_trade_id']}`")
                st.caption(" · ".join(meta))


# ── Rules tab ───────────────────────────────────────────────────
with tab_rules:
    show_inactive = st.checkbox("Include inactive", value=False)
    rules_df = get_trading_rules_df(include_inactive=show_inactive)

    if rules_df.empty:
        st.info("No trading rules found. Add rules via `magpie rules add` or the MCP server.")
    else:
        # Group by category
        categories = rules_df["category"].unique()
        for cat in sorted(categories):
            st.subheader(cat.capitalize())
            cat_rules = rules_df[rules_df["category"] == cat]
            for _, rule in cat_rules.iterrows():
                inactive = " *(inactive)*" if not rule.get("active") else ""
                st.markdown(f"- {rule['rule']}{inactive}")
                meta = [f"Added: {str(rule['created_at'])[:10]}"]
                if pd.notna(rule.get("source_trade_id")):
                    meta.append(f"From trade: `{rule['source_trade_id']}`")
                st.caption(" · ".join(meta))
