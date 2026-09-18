"""Upload page - the front end where anyone can drop documents.

One label, one or more files. There is deliberately no edit, replace or delete
path anywhere in this app: once a submission goes in, it belongs to the drop,
not to the uploader.
"""

from __future__ import annotations

import streamlit as st

from ui import config_gate, get_filedrop, get_settings, human_size, page_config, staging_notice

page_config("Upload a document")

settings = get_settings()

st.title("📤 Upload a document")
st.caption(
    "Anyone can upload. Files are listed on the **Download** page for everyone — "
    "and they stay there. You cannot edit or remove your upload afterwards."
)

if not config_gate():
    st.stop()

staging_notice()

file_limit = settings.max_upload_bytes
total_limit = settings.max_total_upload_bytes
extensions = ", ".join(f".{e}" for e in settings.allowed_extensions)

with st.form("upload", clear_on_submit=True):
    title = st.text_input(
        "Name",
        max_chars=120,
        placeholder="e.g. Q3 supplier agreement",
        help=(
            "What this is. Every file you pick below sits under this one name on the "
            "download page."
        ),
    )
    uploaded = st.file_uploader(
        "Files",
        accept_multiple_files=True,
        help=(
            f"Pick one or several — they are published together under the name above. "
            f"Up to {settings.max_files_per_upload} files, "
            f"{file_limit // (1024 * 1024)} MB each, "
            f"{total_limit // (1024 * 1024)} MB in total. Allowed: {extensions}"
        ),
    )
    passcode = ""
    if settings.upload_passcode:
        passcode = st.text_input("Upload passcode", type="password")
    submitted = st.form_submit_button("Upload for everyone", type="primary")

if uploaded and not submitted:
    listing = " · ".join(f"{f.name} ({human_size(len(f.getvalue()))})" for f in uploaded)
    st.caption(f"{len(uploaded)} file{'s' if len(uploaded) != 1 else ''} ready: {listing}")

if submitted:
    if not uploaded:
        st.error("Choose at least one file.")
    else:
        with st.spinner("Sending to Notion…"):
            result = get_filedrop().publish(
                title=title,
                files=[(f.name, f.getvalue()) for f in uploaded],
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
1. Every file you pick is stored in the **{settings.site_name}** Notion workspace,
   attached to the single row named after the label you typed.
2. That name and its date are shown on the download page; each file is downloaded
   separately.
3. **{"A moderator reviews uploads first." if settings.require_approval else "It is published immediately."}**
4. Anyone can download it. Nobody — including you — can edit or delete it from this site.
5. Documents are for sharing what you are allowed to share. Nothing private.
        """
    )
