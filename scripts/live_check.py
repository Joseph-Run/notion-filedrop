"""Live check against your real Notion workspace.

Run after scripts/setup_notion.py:

    python scripts/live_check.py                # one small file
    python scripts/live_check.py --files 3      # three files under one label
    python scripts/live_check.py --big 50       # one 50 MB file (forces multi-part)
    python scripts/live_check.py --files 2 --big 25

It proves, against the real API rather than the test double:
  1. the files land in Notion (create -> send -> attach, one upload per file),
  2. the moderation gate keeps the row off the public list until it is approved,
  3. approving it (the tick you make in Notion, done here over the API) publishes it,
  4. every attachment downloads byte-for-byte as sent,
  5. the test rows are archived again so your workspace is left as it was.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import pathlib
import sys
import tomllib

import requests

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from filedrop.config import Settings  # noqa: E402
from filedrop.notion_client import API_VERSION  # noqa: E402
from filedrop.store import FileDrop  # noqa: E402

TEST_BYTES = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog>>endobj\n"
    b"% live check document - safe to delete\n%%EOF\n"
) * 20


def build_payload(name: str, index: int, size_mb: int) -> bytes:
    """A unique payload per file, so a mix-up between attachments cannot pass."""
    header = f"%PDF-1.4\n% {name} #{index} marker-{os.urandom(4).hex()}\n".encode()
    if not size_mb:
        return header + TEST_BYTES
    target = size_mb * 1024 * 1024
    if len(header) >= target:
        raise SystemExit(f"payload header already exceeds {size_mb} MB")
    return header + os.urandom(target - len(header))


def _patch(token: str, page_id: str, base_url: str, body: dict) -> requests.Response:
    response = requests.patch(
        f"{base_url}/v1/pages/{page_id}",
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": API_VERSION,
            "Content-Type": "application/json",
        },
        json=body,
        timeout=30,
    )
    response.raise_for_status()
    return response


def approve(token: str, page_id: str, base_url: str, approved: bool = True) -> None:
    """What the moderator does by ticking the box in Notion."""
    _patch(token, page_id, base_url, {"properties": {"Approved": {"checkbox": approved}}})


def archive(token: str, page_id: str, base_url: str) -> None:
    """Documented as `archived` up to 2025-09-03 and `in_trash` in 2026-03-11."""
    try:
        _patch(token, page_id, base_url, {"in_trash": True})
    except requests.HTTPError:
        _patch(token, page_id, base_url, {"archived": True})


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="End-to-end check against your real Notion workspace.")
    parser.add_argument("--files", type=int, default=1, metavar="N", help="files under one label")
    parser.add_argument(
        "--big",
        type=int,
        default=0,
        metavar="MB",
        help="size of each file (above 20 MB forces Notion's multi-part path)",
    )
    args = parser.parse_args(argv)
    if args.files < 1:
        parser.error("--files must be at least 1")

    secrets_path = ROOT / ".streamlit" / "secrets.toml"
    if not secrets_path.exists():
        print(f"No {secrets_path}. Run scripts/setup_notion.py first.")
        return 2
    config = tomllib.loads(secrets_path.read_text(encoding="utf-8"))

    items = [
        (f"live-check-{i + 1}.pdf", build_payload(f"live-check-{i + 1}.pdf", i + 1, args.big))
        for i in range(args.files)
    ]
    weight = sum(len(blob) for _, blob in items)

    token = config["NOTION_API_KEY"]
    settings = Settings(
        notion_token=token,
        data_source_id=config["NOTION_DATA_SOURCE_ID"],
        notion_api_base=config.get("NOTION_API_BASE", "https://api.notion.com"),
        require_approval=True,  # force the gate on so step 2 is meaningful
    )
    drop = FileDrop(settings)
    failures: list[str] = []
    title = f"LIVE CHECK {dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    print(
        f"1. uploading {len(items)} file(s) as {title!r} "
        f"({weight / 1024 ** 2:.1f} MB total) ..."
    )
    result = drop.publish(title=title, files=items)
    if not result.ok:
        print(f"   FAILED: {result.message}")
        return 1
    print(f"   ok: {result.page_url}")

    page_id = result.page_url.rsplit("/", 1)[-1]
    page_id = f"{page_id[0:8]}-{page_id[8:12]}-{page_id[12:16]}-{page_id[16:20]}-{page_id[20:32]}"

    print("2. moderation gate ...")
    if page_id in [d.page_id for d in drop.documents()]:
        failures.append("the unapproved upload appeared on the public list")
    else:
        print("   ok: held back until approved")

    print("3. approving it (as the moderator would) ...")
    approve(token, page_id, settings.notion_api_base)
    published = [d for d in drop.documents() if d.page_id == page_id]
    if len(published) != 1:
        failures.append(f"approved upload did not appear on the list (found {len(published)})")
    else:
        print("   ok: published")

    print(f"4. downloading all {len(items)} attachment(s) ...")
    if published:
        row = published[0]
        names = [a.name for a in row.attachments]
        expected_names = [name for name, _ in items]
        if names != expected_names:
            failures.append(f"attachments are {names}, expected {expected_names}")
        else:
            print(f"   ok: row carries {names}")
        for index, (name, blob) in enumerate(items):
            try:
                attachment, data = drop.fetch_attachment(page_id, index)
            except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                failures.append(f"attachment {index + 1} ({name}) failed to download: {exc}")
                continue
            if data != blob:
                failures.append(
                    f"attachment {index + 1} ({name}) came back changed: "
                    f"sent {len(blob)} bytes, got {len(data)}"
                )
            else:
                print(f"   ok: {name} — {len(data)} bytes round-tripped, name preserved")

    print("5. cleaning up ...")
    # sweep every test row, in case an earlier run left one behind
    for doc in drop.client.list_documents(settings.data_source_id, approved_only=False):
        if doc.title.startswith("LIVE CHECK"):
            archive(token, doc.page_id, settings.notion_api_base)
            print(f"   archived {doc.page_id}")
    print("   ok: test rows archived in Notion")

    if failures:
        print("\nFAILED:")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("\nAll live checks passed against the real Notion API.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
