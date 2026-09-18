"""Multi-part upload: what happens above Notion's 20 MB single-part ceiling.

Notion splits anything larger into 5-20 MB parts sent with a `part_number` field,
then a `/complete` call; the size rules are enforced here against the same shapes
the real API uses.
"""

from __future__ import annotations

import hashlib
import os

import pytest
from conftest import build_settings

from filedrop import FileDrop, NotionError
from filedrop.notion_client import (
    MAX_PART_BYTES,
    MAX_MULTIPART_BYTES,
    MIN_PART_BYTES,
    PART_SIZE_BYTES,
    plan_upload,
    split_into_parts,
)

MB = 1024 * 1024


@pytest.mark.parametrize(
    "size,expect_mode,expect_parts",
    [
        (1, "single_part", 1),
        (20 * MB, "single_part", 1),          # exactly the ceiling still fits in one part
        (20 * MB + 1, "multi_part", 3),
        (30 * MB, "multi_part", 3),
        (50 * MB, "multi_part", 5),
        (500 * MB, "multi_part", 50),
        (MAX_MULTIPART_BYTES, "multi_part", 512),
    ],
)
def test_upload_is_planned_by_size(size, expect_mode, expect_parts):
    """The decision is pure arithmetic, so it is tested without allocating files."""
    assert plan_upload(size) == (expect_mode, expect_parts)


def test_over_the_five_gigabyte_ceiling_is_refused():
    with pytest.raises(ValueError, match="5 GB"):
        plan_upload(MAX_MULTIPART_BYTES + 1)


def test_empty_file_is_refused():
    with pytest.raises(ValueError):
        plan_upload(0)


def test_parts_obey_notion_size_rules():
    payload = os.urandom(21 * MB)
    parts = split_into_parts(payload)
    assert len(parts) == 3
    for part in parts[:-1]:  # every part but the last must be 5-20 MB
        assert MIN_PART_BYTES <= len(part) <= MAX_PART_BYTES
    assert len(parts[-1]) == 21 * MB - 2 * PART_SIZE_BYTES
    assert b"".join(parts) == payload


def test_a_large_file_roundtrips_through_parts(fake_notion):
    """21 MB in, 21 MB out, byte for byte, and it really went up in parts."""
    payload = os.urandom(21 * MB)
    drop = FileDrop(build_settings(fake_notion, require_approval=False, max_upload_mb=50))

    result = drop.publish(title="Big report", filename="big.pdf", data=payload)
    assert result.ok, result.message

    upload = next(iter(fake_notion.state.uploads.values()))
    assert upload["mode"] == "multi_part"
    assert upload["number_of_parts"] == 3
    assert sorted(upload["parts"]) == [1, 2, 3]
    assert upload["data"] == payload, "parts were not reassembled in order"

    doc, data = drop.fetch_document_bytes(drop.documents()[0].page_id)
    assert hashlib.sha256(data).digest() == hashlib.sha256(payload).digest()
    assert doc.file.name == "big.pdf"


def test_complete_fails_while_parts_are_missing(fake_notion):
    client = FileDrop(build_settings(fake_notion)).client
    created = client.create_file_upload(
        "big.pdf", "application/pdf", mode="multi_part", number_of_parts=3
    )
    client.send_file(
        created["id"], b"a" * (6 * MB), "big.pdf", "application/pdf", part_number=1
    )
    with pytest.raises(NotionError) as err:
        client.complete_file_upload(created["id"])
    assert "missing parts: 2, 3" in err.value.message


def test_a_short_middle_part_is_rejected(fake_notion):
    """Notion requires >= 5 MB for every part except the final one."""
    client = FileDrop(build_settings(fake_notion)).client
    created = client.create_file_upload(
        "big.pdf", "application/pdf", mode="multi_part", number_of_parts=3
    )
    with pytest.raises(NotionError) as err:
        client.send_file(created["id"], b"tiny", "big.pdf", "application/pdf", part_number=1)
    assert "at least 5MB" in err.value.message


def test_a_part_out_of_range_is_rejected(fake_notion):
    client = FileDrop(build_settings(fake_notion)).client
    created = client.create_file_upload(
        "big.pdf", "application/pdf", mode="multi_part", number_of_parts=2
    )
    with pytest.raises(NotionError) as err:
        client.send_file(
            created["id"], b"a" * (6 * MB), "big.pdf", "application/pdf", part_number=7
        )
    assert "between 1 and 2" in err.value.message


def test_app_ceiling_is_configurable_and_capped(fake_notion):
    assert build_settings(fake_notion, max_upload_mb=50).max_upload_bytes == 50 * MB
    # nothing can exceed Notion's own ceiling, however high the setting goes
    assert build_settings(fake_notion, max_upload_mb=99999).max_upload_bytes == MAX_MULTIPART_BYTES


def test_a_file_over_the_configured_ceiling_is_refused_before_upload(fake_notion):
    drop = FileDrop(build_settings(fake_notion, max_upload_mb=5))
    result = drop.publish(title="Too big", filename="big.pdf", data=b"x" * (6 * MB))
    assert not result.ok
    assert "Too large" in result.message
    assert not fake_notion.state.uploads, "a rejected file still reached the API"
