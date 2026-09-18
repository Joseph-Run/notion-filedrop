"""Thin Notion client for the file-drop site.

No Streamlit import here on purpose: this module is unit-testable and reusable
from a CLI (see scripts/setup_notion.py).

Notion API facts this code depends on (verified against developers.notion.com,
API version 2026-03-11):
  * Files <= 20 MB go up in one part:  POST /v1/file_uploads  ->  POST /v1/file_uploads/{id}/send
  * Larger files need mode=multi_part (paid workspaces, up to 5 GB) - not used here.
  * A file_upload is attached by referencing its id in a `files` page property.
  * `file_upload` is WRITE-ONLY. Reading a page back returns a Notion-hosted
    `file` object whose url is SIGNED AND EXPIRES AFTER 1 HOUR.
    => never cache download urls; re-read the page for every download.
  * There is no API to delete a file upload, and no API to set database view
    filters. Moderation is a checkbox + a filter in the query.
"""

from __future__ import annotations

import json
import mimetypes
from dataclasses import dataclass
from typing import Any, Iterator

import requests

NOTION_BASE = "https://api.notion.com"
API_VERSION = "2026-03-11"
MAX_SINGLE_PART_BYTES = 20 * 1024 * 1024  # Notion's documented single-part limit


def guess_content_type(filename: str, provided: str | None = None) -> str:
    """The content type must be identical at create and send time.

    Notion infers a type from the filename at creation and then rejects the
    upload with a 400 if the send disagrees ("Current file content type of
    application/octet-stream does not match the original content type"), so both
    steps have to be given the same value.
    """
    if provided:
        return provided
    return mimetypes.guess_type(filename or "")[0] or "application/octet-stream"


class NotionError(RuntimeError):
    """Any non-2xx answer from Notion, with the API's own message preserved."""

    def __init__(self, status: int, code: str, message: str, path: str):
        super().__init__(f"Notion {status} {code} on {path}: {message}")
        self.status = status
        self.code = code
        self.message = message
        self.path = path


@dataclass(frozen=True)
class RemoteFile:
    """A downloadable file as Notion describes it, with a 1-hour signed url."""

    name: str
    url: str
    expiry_time: str | None


@dataclass(frozen=True)
class Document:
    """One row of the drop: what the download page renders."""

    page_id: str
    title: str
    created_time: str
    approved: bool
    file: RemoteFile | None

    @property
    def notion_url(self) -> str:
        return f"https://www.notion.so/{self.page_id.replace('-', '')}"


class NotionFiles:
    """Create file uploads, attach them to database rows, list and fetch them."""

    def __init__(
        self,
        token: str,
        *,
        base_url: str = NOTION_BASE,
        version: str = API_VERSION,
        session: requests.Session | None = None,
        timeout: float = 60.0,
    ):
        if not token:
            raise ValueError("A Notion integration token is required.")
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.version = version
        self.timeout = timeout
        self.session = session or requests.Session()

    # ---------------------------------------------------------------- helpers

    def _headers(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": self.version,
        }
        if extra:
            headers.update(extra)
        return headers

    def _raise_for_status(self, response: requests.Response, path: str) -> None:
        if response.status_code < 400:
            return
        code, message = "unknown", response.text[:500]
        try:
            body = response.json()
            code = body.get("code", code)
            message = body.get("message", message)
        except ValueError:
            pass
        raise NotionError(response.status_code, code, message, path)

    def _json(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        # A body on GET is both wrong and, on a keep-alive connection, leaves
        # unread bytes behind that corrupt the next request line. Only POST/PATCH
        # get one.
        body = json.dumps(payload) if payload else None
        headers = self._headers({"Content-Type": "application/json"} if body else None)
        response = self.session.request(
            method,
            f"{self.base_url}{path}",
            headers=headers,
            data=body,
            timeout=self.timeout,
        )
        self._raise_for_status(response, path)
        return response.json()

    # ------------------------------------------------------------ file upload

    def create_file_upload(self, filename: str, content_type: str | None = None) -> dict[str, Any]:
        """Step 1: reserve a file upload slot. Returns id + upload_url."""
        payload: dict[str, Any] = {"filename": filename}
        if content_type:
            payload["content_type"] = content_type
        return self._json("POST", "/v1/file_uploads", payload)

    def send_file(
        self,
        file_upload_id: str,
        data: bytes,
        filename: str,
        content_type: str = "application/octet-stream",
    ) -> dict[str, Any]:
        """Step 2: POST the bytes as multipart/form-data under the `file` key."""
        path = f"/v1/file_uploads/{file_upload_id}/send"
        # Do not set Content-Type by hand - requests builds the MIME boundary.
        response = self.session.post(
            f"{self.base_url}{path}",
            headers=self._headers(),
            files={"file": (filename, data, content_type)},
            timeout=self.timeout,
        )
        self._raise_for_status(response, path)
        return response.json()

    def upload_file(
        self, filename: str, data: bytes, content_type: str | None = None
    ) -> str:
        """Steps 1+2 together. Returns the file_upload id to attach."""
        if len(data) > MAX_SINGLE_PART_BYTES:
            raise ValueError(
                f"{filename} is {len(data) / 1e6:.1f} MB; Notion's single-part limit is 20 MB."
            )
        # One content type for both calls - see guess_content_type().
        resolved_type = guess_content_type(filename, content_type)
        created = self.create_file_upload(filename, resolved_type)
        sent = self.send_file(created["id"], data, filename, resolved_type)
        upload_id = sent.get("id") or created["id"]
        if sent.get("status") not in (None, "uploaded"):
            raise NotionError(400, sent.get("status", "bad_status"), "upload incomplete", f"/v1/file_uploads/{upload_id}")
        return upload_id

    # ----------------------------------------------------------------- pages

    def create_page(
        self,
        data_source_id: str,
        *,
        title: str,
        file_upload_id: str,
        file_property: str = "Document",
        title_property: str = "Name",
        filename: str | None = None,
        properties: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create one row: the title, the attached file, plus any extra properties.

        Extra properties are merged, which is where the moderation flag is set.
        """
        file_value: dict[str, Any] = {"type": "file_upload", "file_upload": {"id": file_upload_id}}
        if filename:
            file_value["name"] = filename

        payload_properties: dict[str, Any] = {
            title_property: {"title": [{"text": {"content": title[:2000]}}]},
            file_property: {"type": "files", "files": [file_value]},
        }
        if properties:
            payload_properties.update(properties)

        return self._json(
            "POST",
            "/v1/pages",
            {
                "parent": {"type": "data_source_id", "data_source_id": data_source_id},
                "properties": payload_properties,
            },
        )

    def query_pages(
        self,
        data_source_id: str,
        *,
        approved_only: bool = True,
        approved_property: str = "Approved",
        page_size: int = 100,
        max_pages: int = 20,
    ) -> list[dict[str, Any]]:
        """Every row of the drop, following pagination (list_pages is capped at 100/page)."""
        results: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(max_pages):
            payload: dict[str, Any] = {
                "page_size": min(page_size, 100),
                "sorts": [{"timestamp": "created_time", "direction": "descending"}],
            }
            if approved_only:
                payload["filter"] = {
                    "property": approved_property,
                    "checkbox": {"equals": True},
                }
            if cursor:
                payload["start_cursor"] = cursor
            body = self._json("POST", f"/v1/data_sources/{data_source_id}/query", payload)
            results.extend(body.get("results", []))
            if not body.get("has_more"):
                break
            cursor = body.get("next_cursor")
            if not cursor:
                break
        return results

    # -------------------------------------------------------------- read side

    @staticmethod
    def parse_file(page: dict[str, Any], file_property: str = "Document") -> RemoteFile | None:
        """Pull the (write-only) file_upload back out as a signed, temporary url."""
        prop = (page.get("properties") or {}).get(file_property) or {}
        files = prop.get("files") or []
        if not files:
            return None
        first = files[0]
        source = first.get(first.get("type", ""), {}) or {}
        url = source.get("url")
        if not url:
            return None
        return RemoteFile(
            name=first.get("name") or "download",
            url=url,
            expiry_time=source.get("expiry_time"),
        )

    @staticmethod
    def parse_title(page: dict[str, Any], title_property: str = "Name") -> str:
        prop = (page.get("properties") or {}).get(title_property) or {}
        parts = prop.get("title") or []
        return "".join(piece.get("plain_text", "") for piece in parts).strip() or "Untitled"

    @staticmethod
    def parse_approved(page: dict[str, Any], approved_property: str = "Approved") -> bool:
        prop = (page.get("properties") or {}).get(approved_property) or {}
        return bool(prop.get("checkbox"))

    def list_documents(
        self,
        data_source_id: str,
        *,
        approved_only: bool = True,
        file_property: str = "Document",
        title_property: str = "Name",
        approved_property: str = "Approved",
    ) -> list[Document]:
        docs: list[Document] = []
        for page in self.query_pages(
            data_source_id, approved_only=approved_only, approved_property=approved_property
        ):
            docs.append(
                Document(
                    page_id=page.get("id", ""),
                    title=self.parse_title(page, title_property),
                    created_time=page.get("created_time", ""),
                    approved=self.parse_approved(page, approved_property),
                    file=self.parse_file(page, file_property),
                )
            )
        return docs

    def get_document(
        self, page_id: str, *, file_property: str = "Document", title_property: str = "Name"
    ) -> Document:
        """Re-read a single row so its signed url is fresh (they die after 1 hour)."""
        page = self._json("GET", f"/v1/pages/{page_id}")
        return Document(
            page_id=page.get("id", page_id),
            title=self.parse_title(page, title_property),
            created_time=page.get("created_time", ""),
            approved=self.parse_approved(page),
            file=self.parse_file(page, file_property),
        )

    def fetch_bytes(self, url: str) -> bytes:
        """Download the signed url server-side.

        Notion's signed storage urls generally work bare, but the API docs call
        it an authenticated url, so try with the integration header first and
        fall back only on 401/403.
        """
        response = self.session.get(url, timeout=self.timeout)
        if response.status_code in (401, 403):
            response = self.session.get(url, headers=self._headers(), timeout=self.timeout)
        self._raise_for_status(response, "file-download")
        return response.content

    # ------------------------------------------------------------- dev helper

    def iter_pages(self, data_source_id: str, **kwargs: Any) -> Iterator[dict[str, Any]]:
        yield from self.query_pages(data_source_id, **kwargs)
