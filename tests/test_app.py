"""UI-level checks: both Streamlit pages must actually execute and render.

Streamlit does not run a page's script until a session connects, so a passing
health check proves nothing (see the streamlit-cloud-deploy skill). AppTest runs
the real script, including widget callbacks and reruns.

AppTest has no API for `st.file_uploader`, so the browser-side drag-and-drop is
covered by the module tests plus the live browser check described in the README.
"""

from __future__ import annotations

import os

from conftest import APP

from streamlit.testing.v1 import AppTest

from filedrop import FileDrop


def open_app():
    return AppTest.from_file(APP, default_timeout=60).run()


def open_download_page():
    """Navigate exactly as a visitor does: load the app, then switch page."""
    at = open_app()
    at.switch_page("pages/1_Download.py")
    return at.run()


def test_upload_page_renders_without_exception(app_factory):
    app_factory()
    at = open_app()
    assert not at.exception, at.exception
    assert any("Upload a document" in t.value for t in at.title)
    # the three things a visitor must be given: a name field, a file picker, a submit
    assert at.text_input, "no name field on the upload page"
    assert at.button, "no submit button on the upload page"


def test_upload_page_warns_when_credentials_are_missing(app_factory):
    app_factory(notion_token="", data_source_id="")
    at = open_app()
    assert not at.exception, at.exception
    errors = " ".join(e.value for e in at.error) + " " + " ".join(m.value for m in at.markdown)
    assert "not connected to Notion" in errors
    assert "NOTION_API_KEY" in errors


def test_download_page_renders_every_approved_document(app_factory, fake_notion):
    settings = app_factory(require_approval=False)
    drop = FileDrop(settings)
    drop.publish(title="Annual report", filename="report.pdf", data=b"%PDF-1.4 body")
    drop.publish(title="Budget sheet", filename="budget.csv", data=b"a,b,c\n1,2,3\n")

    at = open_download_page()
    assert not at.exception, at.exception
    body = "\n".join(m.value for m in at.markdown) + "\n".join(m.value for m in at.caption)
    assert "Annual report" in body and "Budget sheet" in body
    assert "2 documents" in body and "2 files available" in body


def test_download_page_hides_unapproved_uploads(app_factory, fake_notion):
    settings = app_factory(require_approval=True)
    FileDrop(settings).publish(title="Pending secret", filename="secret.pdf", data=b"%PDF-1.4")

    at = open_download_page()
    assert not at.exception, at.exception
    text = "\n".join(m.value for m in at.markdown) + "\n".join(i.value for i in at.info)
    assert "Pending secret" not in text
    assert "Nothing here yet" in text

    # and it appears as soon as a moderator ticks the box in Notion
    fake_notion.state.pages[0]["approved"] = True
    at = open_download_page()
    text = "\n".join(m.value for m in at.markdown)
    assert "Pending secret" in text


def test_a_row_with_several_files_gets_a_button_each(app_factory):
    """One label, three files: three independent fetch/save pairs on the page."""
    settings = app_factory(require_approval=False)
    FileDrop(settings).publish(
        title="Q3 pack",
        files=[("agreement.pdf", b"%PDF agreement"), ("budget.csv", b"a,b\n1,2\n")],
    )

    at = open_download_page()
    assert not at.exception, at.exception
    body = "\n".join(m.value for m in at.markdown) + "\n".join(c.value for c in at.caption)
    assert "Q3 pack" in body
    assert "agreement.pdf" in body and "budget.csv" in body, "attachments not listed by name"
    assert "1 document" in body and "2 files" in body

    get_buttons = [b for b in at.button if b.label == "Get file"]
    assert len(get_buttons) == 2, "each attachment needs its own fetch button"

    # fetching one leaves the other untouched
    get_buttons[0].click().run()
    assert not at.exception, at.exception
    assert len([b for b in at.get("download_button")]) == 1
    assert len([b for b in at.button if b.label == "Get file"]) == 1


def test_get_file_button_then_save_file_button(app_factory):
    """The public download path, exercised through the widgets a visitor clicks.

    The exact bytes are asserted in test_filedrop.py's round-trip test; here the
    point is that the click produces a real download served by this app (a media
    url of our own) rather than leaking the Notion signed url, which expires.
    """
    settings = app_factory(require_approval=False)
    FileDrop(settings).publish(title="Handover notes", filename="notes.txt", data=b"the real bytes")

    at = open_download_page()
    get_buttons = [b for b in at.button if b.label == "Get file"]
    assert len(get_buttons) == 1

    get_buttons[0].click().run()
    assert not at.exception, at.exception
    buttons = at.get("download_button")
    assert buttons, "clicking Get file did not produce a Save file button"
    proto = buttons[0].proto
    assert proto.label == "Save file"
    assert proto.url, "no download url on the Save file button"
    assert "notion" not in proto.url and "s3" not in proto.url, (
        f"the expiring Notion url was exposed instead of being proxied: {proto.url}"
    )
    assert "/media/" in proto.url
