"""Streamlit entry — JWT login against the FastAPI backend."""

from __future__ import annotations

import uuid

import streamlit as st

from chatbot.auth import login, sign_out_button

st.set_page_config(
    page_title="Maintainer's Copilot", page_icon="🛠️", layout="wide"
)

if st.session_state.get("jwt"):
    st.title("Maintainer's Copilot")
    st.success(f"Signed in as **{st.session_state.get('email', 'user')}**")
    st.markdown("Use the sidebar to open **Chat**, **Admin**, or **Memory**.")
    sign_out_button()
    st.stop()

st.title("Maintainer's Copilot")
st.caption("Sign in with the credentials of a user created via `scripts/create_admin.py` or `/auth/register`.")

with st.form("login"):
    email = st.text_input("Email")
    password = st.text_input("Password", type="password")
    submitted = st.form_submit_button("Sign in")

if submitted:
    success, payload = login(email, password)
    if success:
        st.session_state["jwt"] = payload
        st.session_state["email"] = email
        st.session_state["session_id"] = str(uuid.uuid4())
        st.rerun()
    else:
        st.error(f"Login failed — {payload}")
