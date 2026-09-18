"""Several files under one label - the "one name, many documents" case.

Notion's `files` property holds a list, so one row (one label the uploader typed)
can carry several documents. Each attachment is uploaded on its own and then all
of them are referenced in a single page creation.
"""

from __future__ import annotations

import pytest
from conftest import build_settings

from filedrop import FileDrop
from filedrop.validation import validate_submission

MB = 1024 * 1024


def test_several_files_share_one_row(fake_notion):
    drop = FileDrop(
        build_settings(
            fake_notion,
            require_approval=False,
            allowed_extensions=("pdf", "csv", "png"),
        )
    )
    files = [
        ("agreement.pdf", b"%PDF-1.4 agreement"),
        ("budget.csv", b"item,cost\nwidget,10\n"),
        ("photo.png", b"\x89PNG\r\n\x1a\n fake"),
    ]

    result = drop.publish(title="Q3 pack", files=files)
    assert result.ok, result.message
    assert "3 files" in result.message

    docs = drop.documents()
    assert len(docs) == 1, "one label should mean one row"
    doc = docs[0]
    assert [a.name for a in doc.attachments] == ["agreement.pdf", "budget.csv", "photo.png"]
    assert doc.multiple

    for index, (name, blob) in enumerate(files):
        attachment, data = drop.fetch_attachment(doc.page_id, index)
        assert attachment.name == name
        assert data == blob, f"file {index} came back changed"


def test_a_single_file_still_reports_as_one(fake_notion):
    drop = FileDrop(build_settings(fake_notion, require_approval=False))
    result = drop.publish(title="Solo", filename="one.pdf", data=b"%PDF-1.4")
    assert result.ok
    assert "Your file" in result.message
    docs = drop.documents()
    assert not docs[0].multiple and len(docs[0].attachments) == 1


def test_one_bad_file_rejects_the_whole_submission(fake_notion):
    """Nothing is published when any file fails validation - no partial rows."""
    drop = FileDrop(build_settings(fake_notion, require_approval=False))
    result = drop.publish(
        title="Mixed bag",
        files=[("good.pdf", b"%PDF-1.4 fine"), ("payload.exe", b"MZ\x90\x00")],
    )
    assert not result.ok
    assert ".exe" in result.message
    assert fake_notion.state.uploads == {}, "a rejected submission still reached Notion"
    assert fake_notion.state.pages == []


def test_too_many_files_is_refused(fake_notion):
    drop = FileDrop(build_settings(fake_notion, require_approval=False, max_files_per_upload=3))
    result = drop.publish(
        title="Too many", files=[(f"f{i}.txt", b"x") for i in range(4)]
    )
    assert not result.ok
    assert "Up to 3 files" in result.message
    assert fake_notion.state.pages == []


def test_the_total_weight_of_a_submission_is_capped(fake_notion):
    drop = FileDrop(
        build_settings(
            fake_notion, require_approval=False, max_upload_mb=50, max_total_upload_mb=10
        )
    )
    result = drop.publish(
        title="Heavy", files=[("a.pdf", b"x" * (6 * MB)), ("b.pdf", b"y" * (6 * MB))]
    )
    assert not result.ok
    assert "add up to" in result.message and "Split it into two uploads" in result.message
    assert fake_notion.state.pages == []


def test_asking_for_a_file_that_is_not_there(fake_notion):
    drop = FileDrop(build_settings(fake_notion, require_approval=False))
    drop.publish(title="One", files=[("a.pdf", b"%PDF-1.4")])
    page_id = drop.documents()[0].page_id
    with pytest.raises(IndexError, match="asked for #3"):
        drop.fetch_attachment(page_id, 2)


@pytest.mark.parametrize(
    "files,max_files,max_total,expect_ok,needle",
    [
        ([], 5, None, False, "at least one file"),
        ([("a.pdf", b"x"), ("b.pdf", b"x")], 5, None, True, ""),
        ([("a.pdf", b"x")] * 6, 5, None, False, "Up to 5 files"),
        ([("a.pdf", b"x" * (7 * MB))], 5, 10 * MB, True, ""),
        ([("a.pdf", b"x" * (7 * MB)), ("b.pdf", b"x" * (7 * MB))], 5, 10 * MB, False, "add up to"),
    ],
)
def test_submission_validation_table(files, max_files, max_total, expect_ok, needle):
    result = validate_submission(
        files,
        max_bytes_per_file=50 * MB,
        allowed_extensions=("pdf",),
        title="T",
        max_files=max_files,
        max_total_bytes=max_total,
    )
    assert bool(result) is expect_ok, result.error
    if needle:
        assert needle in result.error


def test_notion_receives_one_upload_per_file(fake_notion):
    """Each file gets its own file_upload; they are attached together afterwards."""
    drop = FileDrop(build_settings(fake_notion, require_approval=False))
    drop.publish(
        title="Two", files=[("a.pdf", b"first"), ("b.txt", b"second")]
    )
    uploads = list(fake_notion.state.uploads.values())
    assert len(uploads) == 2
    assert {u["filename"] for u in uploads} == {"a.pdf", "b.txt"}
    # distinct content types are matched per file, not guessed once
    assert {u["content_type"] for u in uploads} == {"application/pdf", "text/plain"}
    page = fake_notion.state.pages[0]
    assert [name for _, name in page["attachments"]] == ["a.pdf", "b.txt"]
