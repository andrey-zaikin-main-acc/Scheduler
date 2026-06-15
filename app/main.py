"""Streamlit entry point for the production planning MVP."""

import streamlit as st

from app.ui.navigation import render_navigation


def main() -> None:
    """Render the MVP shell."""
    st.set_page_config(page_title="Production Planner MVP", layout="wide")
    render_navigation()


if __name__ == "__main__":
    main()
