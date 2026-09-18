"""Shared test fixtures.

The UI tests never read config from the environment or from
.streamlit/secrets.toml. They patch `ui.get_settings` / `ui.get_filedrop`
instead, because reading st.secrets mirrors the real secrets file into
os.environ and would otherwise point the app at the user's live Notion
workspace.
"""

from __future__ import annotations

import os
import sys

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, "tests"))

from fake_notion import FakeNotion  # noqa: E402

from filedrop import FileDrop, Settings  # noqa: E402

TOKEN = "ntn_test_token"
DS_ID = "3f1c0b0e-0000-4000-8000-abcdefabcdef"
APP = os.path.join(PROJECT_ROOT, "app.py")


@pytest.fixture()
def fake_notion():
    """A real HTTP server standing in for Notion, on a random local port."""
    with FakeNotion(token=TOKEN) as server:
        yield server


def build_settings(fake: FakeNotion, **overrides) -> Settings:
    fields = dict(
        notion_token=TOKEN,
        data_source_id=DS_ID,
        notion_api_base=fake.base_url,
        require_approval=False,
        allowed_extensions=("pdf", "txt", "csv", "docx"),
        upload_passcode="",
        site_name="Test Drop",
    )
    fields.update(overrides)
    return Settings(**fields)


@pytest.fixture()
def app_factory(fake_notion, monkeypatch):
    """Patch the pages' settings source and hand back the Settings in use."""
    import streamlit as st

    import ui

    def make(**overrides):
        settings = build_settings(fake_notion, **overrides)
        st.cache_resource.clear()
        st.cache_data.clear()
        monkeypatch.setattr(ui, "get_settings", lambda: settings)
        # lazy: constructing the client must only happen if the page asks for it
        monkeypatch.setattr(ui, "get_filedrop", lambda: FileDrop(settings))
        return settings

    monkeypatch.chdir(PROJECT_ROOT)
    return make
