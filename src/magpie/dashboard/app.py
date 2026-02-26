"""Magpie Dashboard — Streamlit multipage app root."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

# Ensure DB is initialized once per Streamlit session
if "db_initialized" not in st.session_state:
    from magpie.db.connection import get_connection

    get_connection()
    st.session_state.db_initialized = True

st.set_page_config(
    page_title="Magpie Dashboard",
    page_icon=":bird:",
    layout="wide",
)

_pages_dir = Path(__file__).parent / "pages"

pages = [
    st.Page(str(_pages_dir / "equity.py"), title="Equity & Drawdown", icon=":material/show_chart:"),
    st.Page(
        str(_pages_dir / "payoff_page.py"),
        title="Payoff Diagrams",
        icon=":material/functions:",
    ),
    st.Page(str(_pages_dir / "greeks.py"), title="Greeks Dashboard", icon=":material/analytics:"),
    st.Page(str(_pages_dir / "winrate.py"), title="Win Rates", icon=":material/leaderboard:"),
]

pg = st.navigation(pages)
pg.run()
