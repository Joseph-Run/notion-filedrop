"""Upload page - the front end where anyone can drop a document.

There is deliberately no edit, replace or delete path anywhere in this app:
once a file is submitted it belongs to the drop, not to the uploader.
"""

from __future__ import annotations

import streamlit as st

from ui import config_gate, get_filedrop, get_settings, page_config

page_config("Upload a document")

settings = get_settings()

st.title("📤 Upload a document")
st.caption(
    "Anyone can upload. Files are listed on the **Download** page for everyone — "
    "and they stay there. You cannot edit or remove your upload afterwards."
)

if not config_gate():
    st.stop()

with st.form("upload", clear_on_submit=True):
    title = st.text_input(
        "Name",
        max_chars=120,
        placeholder="e.g. Q3 supplier agreement",
        help="What this document is. This is the label everyone sees.",
    )
    uploaded = st.file_uploader(
        "File",
        help=(
            f"Up to {settings.max_upload_bytes // (1024 * 1024)} MB. "
            "Allowed: " + ", ".join(f".{e}" for e in settings.allowed_extensions)
        ),
    )
    passcode = ""
    if settings.upload_passcode:
        passcode = st.text_input("Upload passcode", type="password")
    submitted = st.form_submit_button("Upload for everyone", type="primary")

if submitted:
    if uploaded is None:
        st.error("Choose a file first.")
    else:
        with st.spinner("Sending to Notion…"):
            result = get_filedrop().publish(
                title=title,
                filename=uploaded.name,
                data=uploaded.getvalue(),
                passcode=passcode,
            )
        if result.ok:
            st.success(result.message)
            if settings.require_approval:
                st.info("A moderator checks each upload before it is published.")
            st.page_link("pages/1_Download.py", label="Go to the download page →")
        else:
            st.error(result.message)

st.divider()
with st.expander("What happens to my file?"):
    st.markdown(
        f"""
1. Your file is stored in the **{settings.site_name}** Notion workspace, where it
   is attached to the row you just created.
2. Its name and date are shown on the download page.
3. **{"A moderator reviews uploads first." if settings.require_approval else "It is published immediately."}**
4. Anyone can download it. Nobody — including you — can edit or delete it from this site.
5. Documents are for sharing what you are allowed to share. Nothing private.
        """
    )
