"""High-level operations the two pages call. Knows nothing about Streamlit."""

from __future__ import annotations

from dataclasses import dataclass

from .config import Settings
from .notion_client import Document, NotionFiles
from .validation import validate_upload


@dataclass
class SubmitResult:
    ok: bool
    message: str
    page_url: str | None = None


class FileDrop:
    """The whole product surface: publish one document, list documents, fetch one."""

    def __init__(self, settings: Settings, client: NotionFiles | None = None):
        self.settings = settings
        self.client = client or NotionFiles(
            settings.notion_token, base_url=settings.notion_api_base
        )

    # -------------------------------------------------------------- uploading

    def publish(
        self,
        *,
        title: str,
        filename: str,
        data: bytes,
        passcode: str = "",
    ) -> SubmitResult:
        """Validate, push the bytes to Notion, create the row. No edit path exists."""
        s = self.settings

        if s.upload_passcode and passcode != s.upload_passcode:
            return SubmitResult(False, "Wrong upload passcode.")

        check = validate_upload(
            filename,
            len(data or b""),
            max_bytes=s.max_upload_bytes,
            allowed_extensions=s.allowed_extensions,
            title=title,
        )
        if not check:
            return SubmitResult(False, check.error)

        try:
            upload_id = self.client.upload_file(filename, data)
            page = self.client.create_page(
                s.data_source_id,
                title=title.strip(),
                file_upload_id=upload_id,
                file_property=s.file_property,
                title_property=s.title_property,
                filename=filename,
                properties={s.approved_property: {"checkbox": not s.require_approval}},
            )
        except Exception as exc:  # surfaced verbatim in the UI, never swallowed
            return SubmitResult(False, f"Upload failed: {exc}")

        page_id = page.get("id", "")
        return SubmitResult(
            True,
            "Uploaded. It is pending review and will appear on the download page once approved."
            if s.require_approval
            else "Uploaded. It is live on the download page now.",
            page_url=f"https://www.notion.so/{page_id.replace('-', '')}" if page_id else None,
        )

    # -------------------------------------------------------------- download

    def documents(self) -> list[Document]:
        """Everything the public is allowed to see."""
        s = self.settings
        return self.client.list_documents(
            s.data_source_id,
            approved_only=s.require_approval,
            file_property=s.file_property,
            title_property=s.title_property,
            approved_property=s.approved_property,
        )

    def fetch_document_bytes(self, page_id: str) -> tuple[Document, bytes]:
        """Re-read the row for a fresh signed url, then pull the bytes."""
        s = self.settings
        doc = self.client.get_document(
            page_id, file_property=s.file_property, title_property=s.title_property
        )
        if doc.file is None:
            raise FileNotFoundError("That entry has no file attached any more.")
        return doc, self.client.fetch_bytes(doc.file.url)
