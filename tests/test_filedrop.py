"""End-to-end tests for the file drop, run against a real local HTTP server.

Nothing here mocks the network: the app code talks HTTP to tests/fake_notion.py,
which reproduces Notion's documented request/response shapes - including the
detail that matters most for a download page, namely that a file attached from a
`file_upload` comes back as a signed `file` url that is regenerated on every read.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fake_notion import FakeNotion  # noqa: E402
from filedrop import FileDrop, NotionError, Settings, validate_upload  # noqa: E402

TOKEN = "ntn_test_token"
DS_ID = "3f1c0b0e-0000-4000-8000-abcdefabcdef"
PDF_BYTES = b"%PDF-1.4 fake document body\x00\x01\x02" * 50


@pytest.fixture()
def fake():
    with FakeNotion(token=TOKEN) as server:
        yield server


def make_settings(fake: FakeNotion, **overrides) -> Settings:
    fields = dict(
        notion_token=TOKEN,
        data_source_id=DS_ID,
        notion_api_base=fake.base_url,
        max_upload_mb=20,
        allowed_extensions=("pdf", "txt", "csv", "docx"),
        require_approval=True,
        upload_passcode="",
        site_name="Test Drop",
    )
    fields.update(overrides)
    return Settings(**fields)


# --------------------------------------------------------------------- upload


def test_upload_attach_list_and_download_roundtrip(fake):
    drop = FileDrop(make_settings(fake), client=None)
    # moderation off so the new row is immediately listable
    drop.settings.require_approval = False

    result = drop.publish(title="Supplier agreement", filename="agreement.pdf", data=PDF_BYTES)
    assert result.ok, result.message
    assert result.page_url and "notion.so" in result.page_url

    # the bytes really went over the wire as multipart/form-data under "file"
    stored = list(fake.state.uploads.values())
    assert len(stored) == 1 and stored[0]["data"] == PDF_BYTES
    assert stored[0]["filename"] == "agreement.pdf"

    docs = drop.documents()
    assert len(docs) == 1
    assert docs[0].title == "Supplier agreement"
    assert docs[0].file is not None and docs[0].file.name == "agreement.pdf"

    doc, data = drop.fetch_document_bytes(docs[0].page_id)
    assert data == PDF_BYTES
    assert doc.file.expiry_time is not None


def test_every_request_carries_the_integration_token(fake):
    drop = FileDrop(make_settings(fake))
    drop.publish(title="T", filename="a.txt", data=b"hello")
    assert fake.state.auth_seen, "no Authorization header ever sent"
    assert all(h == f"Bearer {TOKEN}" for h in fake.state.auth_seen)


def test_download_refetches_a_fresh_signed_url(fake):
    """Notion urls die after an hour, so a second download must not reuse the first url."""
    drop = FileDrop(make_settings(fake, require_approval=False))
    drop.publish(title="T", filename="a.txt", data=b"hello")
    page_id = drop.documents()[0].page_id

    _, first = drop.fetch_document_bytes(page_id)
    _, second = drop.fetch_document_bytes(page_id)

    assert first == second == b"hello"
    issued = fake.state.urls_issued
    assert len(issued) >= 2
    assert issued[-1] != issued[0], "the same signed url was reused instead of refreshed"


def test_download_retries_with_auth_when_the_url_demands_it(fake):
    """Notion calls these urls authenticated; the client must fall back to headers."""
    fake.state.require_auth_for_files = True
    drop = FileDrop(make_settings(fake, require_approval=False))
    drop.publish(title="T", filename="a.txt", data=b"authenticated bytes")

    page_id = drop.documents()[0].page_id
    _, data = drop.fetch_document_bytes(page_id)
    assert data == b"authenticated bytes"


def test_moderation_gate_hides_unapproved_rows(fake):
    gated = FileDrop(make_settings(fake, require_approval=True))
    gated.publish(title="Pending doc", filename="p.txt", data=b"pending")

    assert gated.documents() == [], "unapproved row leaked onto the public page"

    open_drop = FileDrop(make_settings(fake, require_approval=False))
    assert [d.title for d in open_drop.documents()] == ["Pending doc"]


def test_pagination_walks_every_row(fake):
    drop = FileDrop(make_settings(fake))
    for i in range(5):
        drop.publish(title=f"Doc {i}", filename=f"d{i}.txt", data=b"x")

    docs = drop.client.query_pages(DS_ID, approved_only=False, page_size=2)
    assert len(docs) == 5, "pagination stopped early"


def test_no_edit_or_delete_path_exists(fake):
    """The uploader's lockout is by design: the client exposes no mutation of a row."""
    client = FileDrop(make_settings(fake)).client
    mutators = [n for n in dir(client) if n.lower().startswith(("delete", "update", "remove", "archive"))]
    assert mutators == [], f"unexpected mutating API on the client: {mutators}"


def test_notion_error_is_surfaced_not_swallowed(fake):
    fake.state.fail_send = True
    result = FileDrop(make_settings(fake)).publish(title="T", filename="a.txt", data=b"hello")
    assert not result.ok
    assert "20MB" in result.message and "validation_error" in result.message


def test_upload_sends_one_matching_content_type(fake):
    """Regression: Notion 400s when `send` disagrees with the type declared at creation."""
    client = FileDrop(make_settings(fake)).client
    upload_id = client.upload_file("report.pdf", PDF_BYTES)
    assert fake.state.uploads[upload_id]["content_type"] == "application/pdf"


def test_mismatched_content_type_is_rejected(fake):
    client = FileDrop(make_settings(fake)).client
    created = client.create_file_upload("report.pdf", "application/pdf")
    with pytest.raises(NotionError) as err:
        client.send_file(created["id"], PDF_BYTES, "report.pdf", "application/octet-stream")
    assert "does not match the original content type" in err.value.message


def test_bad_token_is_reported(fake):
    client = FileDrop(make_settings(fake, notion_token="wrong")).client
    with pytest.raises(NotionError) as err:
        client.create_file_upload("a.txt", "text/plain")
    assert err.value.status == 401


def test_passcode_required_when_configured(fake):
    drop = FileDrop(make_settings(fake, upload_passcode="letmein"))
    assert not drop.publish(title="T", filename="a.txt", data=b"x").ok
    assert drop.publish(title="T", filename="a.txt", data=b"x", passcode="letmein").ok


# ----------------------------------------------------------------- validation


@pytest.mark.parametrize(
    "filename,size,title,expect_ok",
    [
        ("a.pdf", 1000, "Fine", True),
        ("a.pdf", 25 * 1024 * 1024, "Too big", False),
        ("a.exe", 1000, "Blocked type", False),
        ("a.pdf", 0, "Empty", False),
        ("a.pdf", 1000, "   ", False),
        ("a.zip", 1000, "Not on the allowlist", False),
        ("makefile", 1000, "No extension", False),
    ],
)
def test_validation_rules(filename, size, title, expect_ok):
    result = validate_upload(
        filename, size, max_bytes=20 * 1024 * 1024, allowed_extensions=("pdf", "txt"), title=title
    )
    assert bool(result) is expect_ok, result.error


def test_the_size_message_is_unambiguous_at_the_boundary():
    """One byte over used to read 'Too large: 50.0 MB; the limit is 50 MB'."""
    limit = 50 * 1024 * 1024
    over = validate_upload(
        "a.pdf", limit + 1, max_bytes=limit, allowed_extensions=("pdf",), title="Edge"
    )
    assert not over
    assert f"{limit + 1:,} bytes" in over.error and f"{limit:,} bytes" in over.error

    exact = validate_upload(
        "a.pdf", limit, max_bytes=limit, allowed_extensions=("pdf",), title="Edge"
    )
    assert exact, exact.error


# -------------------------------------------------------------------- scripts


def test_setup_script_creates_a_database_with_the_right_schema(fake, monkeypatch, capsys):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))
    import setup_notion  # noqa: E402

    monkeypatch.setenv("NOTION_API_KEY", TOKEN)
    exit_code = setup_notion.main(
        [
            "--parent-page", "https://www.notion.so/Root-11111111222233334444555555555555",
            "--base-url", fake.base_url,
            "--write-secrets", os.path.join(os.path.expandvars("%TEMP%"), "fd_secrets_test.toml"),
        ]
    )
    out = capsys.readouterr().out
    assert exit_code == 0
    created = fake.state.databases_created
    assert len(created) == 1
    props = created[0]["initial_data_source"]["properties"]
    assert set(props) == {"Name", "Document", "Approved"}
    assert props["Name"] == {"title": {}}
    assert props["Document"] == {"files": {}}
    assert props["Approved"] == {"checkbox": {}}
    assert created[0]["parent"]["page_id"] == "11111111-2222-3333-4444-555555555555"
    assert "NOTION_DATA_SOURCE_ID" in out
