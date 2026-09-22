"""Settings for the file-drop site.

Read from Streamlit secrets when running inside Streamlit, else from the
environment - which keeps the same code working for local runs, tests and
scripts/setup_notion.py.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_ALLOWED_EXTENSIONS: tuple[str, ...] = (
    "pdf", "doc", "docx", "odt", "rtf", "txt", "md",
    "csv", "tsv", "xls", "xlsx", "ods",
    "ppt", "pptx", "odp",
    "png", "jpg", "jpeg", "gif", "webp", "svg",
    "mp4",
    "zip",
)


def _parse_extensions(raw: str) -> tuple[str, ...]:
    """Turn the comma-separated ALLOWED_EXTENSIONS value into a tuple.

    Falls back to the defaults when unset, and tolerates leading dots so
    ".mp4,.mov" means the same as "mp4,mov".
    """
    if not (raw or "").strip():
        return DEFAULT_ALLOWED_EXTENSIONS
    return tuple(
        ext.strip().lower().lstrip(".")
        for ext in raw.split(",")
        if ext.strip()
    )


def _secret(name: str, default: str = "") -> str:
    """Streamlit secrets first, then the environment.

    Two things worth knowing about this precedence:

    * Secrets win because that is where a deployed app's config lives, and
      because in Streamlit >= 1.6x simply *reading* ``st.secrets`` mirrors the
      whole secrets.toml into ``os.environ`` (overwriting existing values). An
      "environment overrides secrets" rule would therefore be a lie: the read
      for an earlier key already rewrote the environment.
    * Because of that mirroring, a real .streamlit/secrets.toml leaks into any
      code that touches st.secrets in the same process. Tests must not depend on
      env vars to isolate themselves - they inject settings explicitly
      (see tests/conftest.py).
    """
    try:  # pragma: no cover - needs a Streamlit runtime
        import streamlit as st

        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return os.environ.get(name, default)


def _secret_flag(name: str, default: bool) -> bool:
    raw = _secret(name, "")
    if raw == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class Settings:
    notion_token: str = field(default_factory=lambda: _secret("NOTION_API_KEY"))
    data_source_id: str = field(default_factory=lambda: _secret("NOTION_DATA_SOURCE_ID"))
    notion_api_base: str = field(
        default_factory=lambda: _secret("NOTION_API_BASE") or "https://api.notion.com"
    )
    file_property: str = field(default_factory=lambda: _secret("NOTION_FILE_PROPERTY") or "Document")
    title_property: str = field(default_factory=lambda: _secret("NOTION_TITLE_PROPERTY") or "Name")
    approved_property: str = field(
        default_factory=lambda: _secret("NOTION_APPROVED_PROPERTY") or "Approved"
    )
    require_approval: bool = field(default_factory=lambda: _secret_flag("REQUIRE_APPROVAL", True))
    max_upload_mb: float = field(
        default_factory=lambda: float(_secret("MAX_UPLOAD_MB") or 50)
    )
    max_files_per_upload: int = field(
        default_factory=lambda: int(_secret("MAX_FILES_PER_UPLOAD") or 10)
    )
    max_total_upload_mb: float = field(
        default_factory=lambda: float(_secret("MAX_TOTAL_UPLOAD_MB") or 150)
    )
    allowed_extensions: tuple[str, ...] = field(
        default_factory=lambda: _parse_extensions(_secret("ALLOWED_EXTENSIONS"))
    )
    upload_passcode: str = field(default_factory=lambda: _secret("UPLOAD_PASSCODE"))
    site_name: str = field(default_factory=lambda: _secret("SITE_NAME") or "Community File Drop")

    @property
    def max_upload_bytes(self) -> int:
        # Files above 20 MB go up in parts; 5 GB is Notion's own ceiling.
        return int(min(self.max_upload_mb, 5 * 1024) * 1024 * 1024)

    @property
    def max_total_upload_bytes(self) -> int:
        """Per submission, because every chosen file is held in memory at once.

        Honours the configured value exactly: setting it below MAX_UPLOAD_MB simply
        makes the total the binding limit.
        """
        return int(self.max_total_upload_mb * 1024 * 1024)

    @property
    def configured(self) -> bool:
        return bool(self.notion_token and self.data_source_id)

    def missing(self) -> list[str]:
        gaps = []
        if not self.notion_token:
            gaps.append("NOTION_API_KEY")
        if not self.data_source_id:
            gaps.append("NOTION_DATA_SOURCE_ID")
        return gaps
