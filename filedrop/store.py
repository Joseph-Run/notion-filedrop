"""High-level operations the two pages call. Knows nothing about Streamlit."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .config import Settings
from .notion_client import Document, NotionError, NotionFiles, RemoteFile
from .validation import validate_submission


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
        files: Sequence[tuple[str, bytes]] | None = None,
        filename: str | None = None,
        data: bytes | None = None,
        passcode: str = "",
    ) -> SubmitResult:
        """Validate, push every file to Notion, create one row holding them all.

        Pass `files` as [(filename, bytes), ...] to put several files under one
        label; `filename`/`data` is the single-file shorthand. There is no edit,
        replace or delete path anywhere in this app, by design.
        """
        s = self.settings

        items: list[tuple[str, bytes]] = list(files or [])
        if filename is not None or data is not None:
            items.append((filename or "", data or b""))

        if s.upload_passcode and passcode != s.upload_passcode:
            return SubmitResult(False, "Wrong upload passcode.")

        check = validate_submission(
            items,
            max_bytes_per_file=s.max_upload_bytes,
            allowed_extensions=s.allowed_extensions,
            title=title,
            max_files=s.max_files_per_upload,
            max_total_bytes=s.max_total_upload_bytes,
        )
        if not check:
            return SubmitResult(False, check.error)

        try:
            attachments = [
                (self.client.upload_file(name, blob), name) for name, blob in items
            ]
            page = self.client.create_page(
                s.data_source_id,
                title=title.strip(),
                attachments=attachments,
                file_property=s.file_property,
                title_property=s.title_property,
                properties={s.approved_property: {"checkbox": not s.require_approval}},
            )
        except NotionError as exc:
            # The single most common setup mistake deserves its own wording.
            if exc.status == 401:
                return SubmitResult(
                    False,
                    "Notion rejected the integration token (401: "
                    f"{exc.message}). Check NOTION_API_KEY in the app's secrets - a left-in "
                    "placeholder, a doubled pair of quotes, or a truncated paste all fail "
                    "exactly this way. `python scripts/live_check.py` reports whether the "
                    "token in .streamlit/secrets.toml works.",
                )
            return SubmitResult(False, f"Upload failed: {exc}")
        except Exception as exc:  # surfaced verbatim in the UI, never swallowed
            return SubmitResult(False, f"Upload failed: {exc}")

        page_id = page.get("id", "")
        count = len(items)
        label = f"{count} files" if count > 1 else "Your file"
        return SubmitResult(
            True,
            f"{label} uploaded. It is pending review and will appear on the download "
            "page once approved."
            if s.require_approval
            else f"{label} uploaded and live on the download page now.",
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

    def fetch_attachment(self, page_id: str, index: int = 0) -> tuple[RemoteFile, bytes]:
        """Re-read the row for fresh signed urls, then pull one attachment's bytes."""
        s = self.settings
        doc = self.client.get_document(
            page_id, file_property=s.file_property, title_property=s.title_property
        )
        if not doc.attachments:
            raise FileNotFoundError("That entry has no file attached any more.")
        if index >= len(doc.attachments):
            raise IndexError(f"That entry has {len(doc.attachments)} files; asked for #{index + 1}.")
        attachment = doc.attachments[index]
        return attachment, self.client.fetch_bytes(attachment.url)

    def fetch_document_bytes(self, page_id: str) -> tuple[Document, bytes]:
        """The first attachment, for callers that only deal with one file."""
        s = self.settings
        doc = self.client.get_document(
            page_id, file_property=s.file_property, title_property=s.title_property
        )
        if not doc.attachments:
            raise FileNotFoundError("That entry has no file attached any more.")
        return doc, self.client.fetch_bytes(doc.attachments[0].url)
