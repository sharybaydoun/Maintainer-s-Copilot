"""Memory inspector placeholder — session-scoped Redis memory on API."""

from __future__ import annotations

import uuid

import streamlit as st

from chatbot.api_client import API_URL, admin_fetch
from chatbot.auth import require_auth, sign_out_button

st.set_page_config(page_title="Memory", layout="wide")
require_auth()

st.header("Memory inspector")
st.caption(f"Session memory is stored by the API (`{API_URL}`) when `REDIS_URL` is set.")
sign_out_button()

st.text_input("Session ID", key="session_id", value=st.session_state.get("session_id", ""))

try:
    st.subheader("API memory status")
    st.json(admin_fetch("/admin/memory/status"))
except Exception as exc:
    st.error(f"Could not reach API: {exc}")

st.info(
    "Use the **Chat** page with the same session ID to build conversational history. "
    "The API injects compressed prior turns into RAG prompts."
)

if st.button("Generate new session ID"):
    st.session_state["session_id"] = str(uuid.uuid4())
    st.session_state["messages"] = []
    st.rerun()
