"""Streamlit auth helpers backed by the FastAPI ``/auth/jwt/login`` endpoint."""

from __future__ import annotations

import os

import httpx
import streamlit as st

API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")


def login(email: str, password: str) -> tuple[bool, str]:
    """Exchange email + password for a JWT. Returns (success, token_or_error)."""
    try:
        response = httpx.post(
            f"{API_URL}/auth/jwt/login",
            data={"username": email, "password": password},
            timeout=30.0,
        )
    except httpx.HTTPError as exc:
        return False, f"network error: {exc}"

    if response.status_code != 200:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        return False, f"HTTP {response.status_code}: {detail}"

    payload = response.json()
    token = payload.get("access_token")
    if not token:
        return False, "no access_token in response"
    return True, token


def require_auth() -> None:
    if not st.session_state.get("jwt"):
        st.warning("Please sign in on the home page.")
        st.stop()


def sign_out_button() -> None:
    if st.sidebar.button("Sign out"):
        st.session_state.clear()
        st.rerun()
