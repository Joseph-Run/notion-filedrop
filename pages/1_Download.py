"""Download page - the back end where anyone can take documents away.

A row can hold several files under one label, so each attachment gets its own
button. Notion's download urls are signed and expire after an hour, so nothing is
cached here: bytes are pulled fresh from Notion the moment someone asks.
"""

from __future__ import annotations

import streamlit as st

from ui import (
    config_gate,
    get_filedrop,
    get_settings,
    human_date,
    human_size,
    page_config,
    staging_notice,
)

page_config("Download documents")

settings = get_settings()

st.title("📥 Download documents")
st.caption("Everything approved for sharing. Click **Get file** to pull a copy.")

if not config_gate():
    st.stop()

staging_notice()

drop = get_filedrop()
prepared: dict[str, bytes] = st.session_state.setdefault("prepared", {})

if st.button("Refresh list", help="Re-check Notion for newly approved uploads"):
    st.cache_data.clear()
    prepared.clear()

try:
    documents = drop.documents()
except Exception as exc:
    st.error(f"Could not reach Notion: {exc}")
    st.stop()

if not documents:
    st.info(
        "Nothing here yet. "
        + (
            "Uploads appear once a moderator approves them."
            if settings.require_approval
            else "Be the first to upload something."
        )
    )
    st.page_link("Upload.py", label="← Upload a document")
    st.stop()

total_files = sum(len(doc.attachments) for doc in documents)
st.write(
    f"{len(documents)} document{'s' if len(documents) != 1 else ''}, "
    f"{total_files} file{'s' if total_files != 1 else ''} available"
)

for doc in documents:
    with st.container(border=True):
        st.markdown(f"**{doc.title}**")
        st.caption(f"Added {human_date(doc.created_time)}")

        if not doc.attachments:
            st.warning("No file is attached to this entry any more.")
            continue

        for index, attachment in enumerate(doc.attachments):
            key = f"{doc.page_id}:{index}"
            label = attachment.name if doc.multiple else "File"
            left, right = st.columns([3, 1])

            with left:
                st.markdown(f"{label}")
                if key in prepared:
                    st.caption(f"Ready — {human_size(len(prepared[key]))}")
                elif doc.multiple:
                    st.caption("Fetched from Notion when you ask for it.")

            with right:
                if key in prepared:
                    st.download_button(
                        "Save file",
                        data=prepared[key],
                        file_name=attachment.name,
                        mime="application/octet-stream",
                        key=f"save-{key}",
                        width="stretch",
                    )
                elif st.button("Get file", key=f"get-{key}", width="stretch"):
                    try:
                        with st.spinner("Fetching from Notion…"):
                            _, data = drop.fetch_attachment(doc.page_id, index)
                        prepared[key] = data
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Download failed: {exc}")

st.caption(
    "Each file is fetched from Notion with a fresh link at the moment you ask for it, "
    "so links can't go stale."
)
st.divider()
st.page_link("Upload.py", label="← Upload a document")
