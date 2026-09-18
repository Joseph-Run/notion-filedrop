"""Shared UI helpers for both pages."""

from __future__ import annotations

import datetime as dt

import streamlit as st

from filedrop import FileDrop, Settings


@st.cache_resource(show_spinner=False)
def get_settings() -> Settings:
    return Settings()


@st.cache_resource(show_spinner=False)
def get_filedrop() -> FileDrop:
    return FileDrop(get_settings())


def page_config(title: str) -> None:
    st.set_page_config(page_title=title, page_icon="📁", layout="centered")


def config_gate() -> bool:
    """Render a setup notice instead of a broken page when secrets are missing."""
    settings = get_settings()
    if settings.configured:
        return True
    st.error("This file drop is not connected to Notion yet.")
    st.markdown(
        "Missing setting(s): `" + "`, `".join(settings.missing()) + "`.\n\n"
        "Run `python scripts/setup_notion.py` with a Notion integration token, "
        "then put `NOTION_API_KEY` and `NOTION_DATA_SOURCE_ID` in `.streamlit/secrets.toml`."
    )
    return False


def human_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    if num_bytes < 1024 * 1024:
        return f"{num_bytes / 1024:.0f} KB"
    return f"{num_bytes / (1024 * 1024):.1f} MB"


def human_date(iso: str) -> str:
    if not iso:
        return "—"
    try:
        stamp = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso[:10]
    return stamp.strftime("%d %b %Y, %H:%M UTC")
