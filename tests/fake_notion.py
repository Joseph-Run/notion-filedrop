"""A local stand-in for the parts of the Notion API this app uses.

Why it exists: the real API needs an integration token, which means the whole
upload -> attach -> list -> download path cannot be exercised in CI. This fake
speaks the same HTTP shapes (including the write-only `file_upload` property
that comes back as a signed, expiring `file` url) over a real socket, so the
tests drive genuine requests/multipart/form-data rather than mocks.
"""

from __future__ import annotations

import datetime as dt
import email
import email.policy
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


def _iso_now(offset_seconds: int = 3600) -> str:
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=offset_seconds)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )


class FakeNotionState:
    def __init__(self, token: str = "ntn_test_token", data_source_id: str = "ds-1"):
        self.token = token
        self.data_source_id = data_source_id
        self.uploads: dict[str, dict] = {}   # file_upload id -> {filename, data, content_type}
        self.pages: list[dict] = []          # stored page rows
        self.requests: list[tuple[str, str]] = []
        self.auth_seen: list[str] = []
        self.url_serial = 0                  # bumps every time a url is handed out
        self.urls_issued: list[str] = []
        self.fail_send = False               # simulate a Notion 400 on file send
        self.databases_created: list[dict] = []


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    state: FakeNotionState = None  # type: ignore[assignment]

    def log_message(self, *args):  # silence test output
        pass

    # ----------------------------------------------------------------- plumbing

    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, payload: bytes, status: int = 200, name: str = "file.bin") -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Disposition", f'attachment; filename="{name}"')
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def _send_error_json(self, status: int, code: str, message: str) -> None:
        self._send_json({"object": "error", "status": status, "code": code, "message": message}, status)

    def _read_body(self) -> bytes:
        length = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(length) if length else b""

    def _read_json(self) -> dict:
        raw = self._read_body()
        return json.loads(raw) if raw else {}

    def _authorized(self) -> bool:
        auth = self.headers.get("Authorization", "")
        self.state.auth_seen.append(auth)
        return auth == f"Bearer {self.state.token}"

    def _base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    # -------------------------------------------------------------- page shape

    def _fresh_file_url(self, upload_id: str, filename: str) -> str:
        """Notion hands out a NEW signed url every read; the old one dies in 1h."""
        self.state.url_serial += 1
        url = f"{self._base_url()}/fake-files/{upload_id}?sig={self.state.url_serial}"
        self.state.urls_issued.append(url)
        return url

    def _page_response(self, page: dict) -> dict:
        upload_id = page["upload_id"]
        record = self.state.uploads.get(upload_id, {})
        filename = page["filename"]
        return {
            "object": "page",
            "id": page["id"],
            "created_time": page["created_time"],
            "last_edited_time": page["created_time"],
            "url": f"https://www.notion.so/{page['id'].replace('-', '')}",
            "properties": {
                "Name": {
                    "id": "title",
                    "type": "title",
                    "title": [{"plain_text": page["title"], "type": "text"}],
                },
                "Approved": {"id": "chk", "type": "checkbox", "checkbox": page["approved"]},
                "Document": {
                    "id": "fls",
                    "type": "files",
                    "files": [
                        {
                            "name": filename,
                            "type": "file",
                            "file": {
                                "url": self._fresh_file_url(upload_id, filename),
                                "expiry_time": _iso_now(),
                            },
                        }
                    ]
                    if record
                    else [],
                },
            },
        }

    # ---------------------------------------------------------------- routing

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        self.state.requests.append(("GET", path))

        if path.startswith("/v1/pages/"):
            if not self._authorized():
                return self._send_error_json(401, "unauthorized", "bad token")
            page_id = path.rsplit("/", 1)[-1]
            for page in self.state.pages:
                if page["id"] == page_id:
                    return self._send_json(self._page_response(page))
            return self._send_error_json(404, "object_not_found", "no such page")

        if path.startswith("/fake-files/"):
            upload_id = path.rsplit("/", 1)[-1]
            record = self.state.uploads.get(upload_id)
            if not record:
                return self._send_error_json(404, "object_not_found", "no such file")
            return self._send_bytes(record["data"], name=record["filename"])

        return self._send_error_json(404, "object_not_found", path)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        self.state.requests.append(("POST", path))

        if path == "/v1/file_uploads":
            if not self._authorized():
                return self._send_error_json(401, "unauthorized", "bad token")
            body = self._read_json()
            upload_id = str(uuid.uuid4())
            self.state.uploads[upload_id] = {
                "filename": body.get("filename") or "upload.bin",
                "content_type": body.get("content_type") or "application/octet-stream",
                "data": b"",
                "mode": body.get("mode") or "single_part",
                "number_of_parts": body.get("number_of_parts"),
                "parts": {},
            }
            return self._send_json(
                {
                    "object": "file_upload",
                    "id": upload_id,
                    "status": "pending",
                    "filename": None,
                    "content_type": None,
                    "content_length": None,
                    "mode": self.state.uploads[upload_id]["mode"],
                    "number_of_parts": body.get("number_of_parts"),
                    "upload_url": f"{self._base_url()}/v1/file_uploads/{upload_id}/send",
                    "expiry_time": _iso_now(),
                }
            )

        if path.startswith("/v1/file_uploads/") and path.endswith("/complete"):
            if not self._authorized():
                return self._send_error_json(401, "unauthorized", "bad token")
            upload_id = path.split("/")[3]
            record = self.state.uploads.get(upload_id)
            if record is None:
                return self._send_error_json(404, "object_not_found", "no such upload")
            expected = int(record.get("number_of_parts") or 0)
            missing = [str(i) for i in range(1, expected + 1) if i not in record["parts"]]
            if missing:
                return self._send_error_json(
                    400, "validation_error", f"missing parts: {', '.join(missing)}"
                )
            record["data"] = b"".join(record["parts"][i] for i in sorted(record["parts"]))
            return self._send_json(
                {
                    "object": "file_upload",
                    "id": upload_id,
                    "status": "uploaded",
                    "filename": record["filename"],
                    "content_type": record["content_type"],
                    "content_length": str(len(record["data"])),
                }
            )

        if path.startswith("/v1/file_uploads/") and path.endswith("/send"):
            if not self._authorized():
                return self._send_error_json(401, "unauthorized", "bad token")
            upload_id = path.split("/")[3]
            record = self.state.uploads.get(upload_id)
            if record is None:
                return self._send_error_json(404, "object_not_found", "no such upload")
            if self.state.fail_send:
                return self._send_error_json(
                    400, "validation_error", "content length greater than the 20MB limit"
                )
            raw = self._read_body()
            fields = self._parse_multipart_fields(raw, self.headers.get("Content-Type", ""))
            filename, data, content_type = fields.get(
                "file", ("upload.bin", b"", "application/octet-stream")
            )
            # Notion rejects a send whose content type differs from the one
            # declared at creation - reproduce that so the client can't regress.
            declared = (record.get("content_type") or "").strip()
            if declared and content_type != declared:
                return self._send_error_json(
                    400,
                    "validation_error",
                    f"Current file content type of `{content_type}` does not match the "
                    f"original content type of `{declared}`.",
                )

            if record["mode"] == "multi_part":
                expected = int(record.get("number_of_parts") or 0)
                part_field = fields.get("part_number")
                if part_field is None:
                    return self._send_error_json(
                        400, "validation_error", "part_number is required for a multi-part upload"
                    )
                try:
                    part_number = int((part_field[1] or b"").decode().strip())
                except ValueError:
                    return self._send_error_json(400, "validation_error", "part_number must be an integer")
                if not 1 <= part_number <= expected:
                    return self._send_error_json(
                        400,
                        "validation_error",
                        f"part_number must be between 1 and {expected}, got {part_number}",
                    )
                if len(data) > 20 * 1024 * 1024:
                    return self._send_error_json(
                        400, "validation_error", "each part must be at most 20MB"
                    )
                if len(data) < 5 * 1024 * 1024 and part_number != expected:
                    return self._send_error_json(
                        400,
                        "validation_error",
                        "each part must be at least 5MB unless it is the final part",
                    )
                record["parts"][part_number] = data
                record.update({"filename": filename, "content_type": content_type})
                return self._send_json(
                    {
                        "object": "file_upload",
                        "id": upload_id,
                        "status": "pending",
                        "filename": filename,
                        "content_type": content_type,
                        "content_length": str(len(data)),
                        "part_number": str(part_number),
                    }
                )

            record.update({"filename": filename, "data": data, "content_type": content_type})
            return self._send_json(
                {
                    "object": "file_upload",
                    "id": upload_id,
                    "status": "uploaded",
                    "filename": filename,
                    "content_type": content_type,
                    "content_length": str(len(data)),
                }
            )

        if path == "/v1/pages":
            if not self._authorized():
                return self._send_error_json(401, "unauthorized", "bad token")
            body = self._read_json()
            parent = body.get("parent") or {}
            props = body.get("properties") or {}
            title_parts = ((props.get("Name") or {}).get("title")) or []
            title = "".join(p.get("text", {}).get("content", "") for p in title_parts)
            files = ((props.get("Document") or {}).get("files")) or []
            upload_id = ""
            filename = "document"
            if files:
                upload_id = (files[0].get("file_upload") or {}).get("id", "")
                filename = files[0].get("name") or self.state.uploads.get(upload_id, {}).get(
                    "filename", "document"
                )
            page = {
                "id": str(uuid.uuid4()),
                "created_time": _iso_now(offset_seconds=0),
                "title": title,
                "approved": bool((props.get("Approved") or {}).get("checkbox")),
                "upload_id": upload_id,
                "filename": filename,
                "parent": parent,
            }
            self.state.pages.append(page)
            return self._send_json(self._page_response(page))

        if path.startswith("/v1/data_sources/") and path.endswith("/query"):
            if not self._authorized():
                return self._send_error_json(401, "unauthorized", "bad token")
            body = self._read_json()
            want_approved = None
            flt = body.get("filter") or {}
            if flt.get("property") == "Approved":
                want_approved = bool((flt.get("checkbox") or {}).get("equals"))
            if flt.get("property") and flt.get("property") != "Approved":
                # the app only ever filters on the moderation flag
                return self._send_error_json(400, "validation_error", "unexpected filter")

            rows = list(reversed(self.state.pages))  # newest first
            if want_approved is not None:
                rows = [r for r in rows if r["approved"] is want_approved]

            page_size = int(body.get("page_size") or 100)
            start = int(body.get("start_cursor") or 0)
            chunk = rows[start : start + page_size]
            has_more = start + page_size < len(rows)
            return self._send_json(
                {
                    "object": "list",
                    "results": [self._page_response(p) for p in chunk],
                    "has_more": has_more,
                    "next_cursor": str(start + page_size) if has_more else None,
                    "type": "page",
                }
            )

        if path == "/v1/databases":
            if not self._authorized():
                return self._send_error_json(401, "unauthorized", "bad token")
            body = self._read_json()
            self.state.databases_created.append(body)
            ds_id = str(uuid.uuid4())
            return self._send_json(
                {
                    "object": "database",
                    "id": str(uuid.uuid4()),
                    "title": body.get("title"),
                    "data_sources": [{"object": "data_source", "id": ds_id, "name": "Fake"}],
                }
            )

        if path == "/v1/search":
            if not self._authorized():
                return self._send_error_json(401, "unauthorized", "bad token")
            return self._send_json(
                {
                    "object": "list",
                    "results": [
                        {
                            "object": "page",
                            "id": "11111111-2222-3333-4444-555555555555",
                            "url": "https://www.notion.so/Root-11111111222233334444555555555555",
                            "properties": {
                                "title": {"type": "title", "title": [{"plain_text": "Root page"}]}
                            },
                        }
                    ],
                    "has_more": False,
                    "next_cursor": None,
                }
            )

        return self._send_error_json(404, "object_not_found", path)

    # ------------------------------------------------------------------ helper

    @staticmethod
    def _parse_multipart_fields(
        raw: bytes, content_type: str
    ) -> dict[str, tuple[str | None, bytes, str | None]]:
        """Map every form field to (filename, payload, content_type)."""
        parsed: dict[str, tuple[str | None, bytes, str | None]] = {}
        if not raw:
            return parsed
        message = email.parser.BytesParser(policy=email.policy.default).parsebytes(
            b"Content-Type: "
            + content_type.encode()
            + b"\r\nMIME-Version: 1.0\r\n\r\n"
            + raw
        )
        if not message.is_multipart():
            parsed["file"] = ("upload.bin", raw, "application/octet-stream")
            return parsed
        for part in message.iter_parts():
            name = part.get_param("name", header="content-disposition")
            if not name:
                continue
            parsed[name] = (
                part.get_filename(),
                part.get_payload(decode=True) or b"",
                part.get_content_type(),
            )
        return parsed


class FakeNotion:
    """Context manager that serves the fake API on a random localhost port."""

    def __init__(self, token: str = "ntn_test_token"):
        self.state = FakeNotionState(token=token)
        handler = type("Handler", (_Handler,), {"state": self.state})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def __enter__(self) -> "FakeNotion":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.server.shutdown()
        self.server.server_close()
