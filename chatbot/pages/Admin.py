"""Admin placeholder — reads FastAPI /admin/* endpoints."""

from __future__ import annotations

import streamlit as st

from chatbot.api_client import admin_fetch
from chatbot.auth import require_auth, sign_out_button

st.set_page_config(page_title="Admin", layout="wide")
require_auth()

st.header("Admin configuration")
st.caption("Placeholder — configuration via FastAPI admin endpoints")
sign_out_button()

col1, col2 = st.columns(2)
try:
    with col1:
        st.subheader("Full health")
        st.json(admin_fetch("/admin/health/full"))
    with col2:
        st.subheader("RAG stats")
        st.json(admin_fetch("/admin/rag/stats"))
    st.subheader("Latest evals")
    st.json(admin_fetch("/admin/evals/latest"))
    st.subheader("Memory status")
    st.json(admin_fetch("/admin/memory/status"))
except Exception as exc:
    st.error(f"Could not reach API: {exc}")
