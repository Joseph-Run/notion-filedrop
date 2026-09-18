"""Download page - the back end where anyone can take a document away.

Notion's download urls are signed and expire after an hour, so nothing is
cached here: bytes are pulled fresh from Notion the moment someone asks for a
file.
"""

from __future__ import annotations

import streamlit as st

from ui import config_gate, get_filedrop, get_settings, human_date, human_size, page_config

page_config("Download documents")

settings = get_settings()

st.title("📥 Download documents")
st.caption("Everything approved for sharing. Click **Get file** to pull a copy.")

if not config_gate():
    st.stop()

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
        + ("Uploads appear once a moderator approves them." if settings.require_approval else "Be the first to upload something.")
    )
    st.page_link("app.py", label="← Upload a document")
    st.stop()

st.write(f"{len(documents)} document{'s' if len(documents) != 1 else ''} available")

for index, doc in enumerate(documents):
    with st.container(border=True):
        left, right = st.columns([3, 1])
        with left:
            st.markdown(f"**{doc.title}**")
            st.caption(f"Added {human_date(doc.created_time)}")
        with right:
            if doc.page_id in prepared:
                data = prepared[doc.page_id]
                st.download_button(
                    "Save file",
                    data=data,
                    file_name=doc.file.name if doc.file else f"{doc.title}",
                    mime="application/octet-stream",
                    key=f"save-{doc.page_id}",
                    width="stretch",
                )
            elif st.button("Get file", key=f"get-{doc.page_id}", width="stretch"):
                try:
                    with st.spinner("Fetching from Notion…"):
                        _, data = drop.fetch_document_bytes(doc.page_id)
                    prepared[doc.page_id] = data
                    st.session_state["last_size"] = human_size(len(data))
                    st.rerun()
                except Exception as exc:
                    st.error(f"Download failed: {exc}")
        if doc.page_id in prepared:
            st.caption(f"Ready — {human_size(len(prepared[doc.page_id]))}")
    if index == 0:
        st.caption(
            "Each file is fetched from Notion with a fresh link at the moment you ask for it, "
            "so links can't go stale."
        )

st.divider()
st.page_link("app.py", label="← Upload a document")
