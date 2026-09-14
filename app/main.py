"""Streamlit entry point for the production planning MVP."""

import streamlit as st

from app.services.bootstrap_service import initialize_database_once
from app.ui.navigation import render_navigation


def main() -> None:
    """Render the MVP shell."""
    st.set_page_config(page_title="Production Planner MVP", layout="wide")
    # The module-level process guard makes this cheap on Streamlit reruns while
    # still bootstrapping a direct ``streamlit run app/main.py`` launch.
    initialize_database_once()
    render_navigation()


if __name__ == "__main__":
    main()
