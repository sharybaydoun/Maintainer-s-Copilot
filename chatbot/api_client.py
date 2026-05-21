"""HTTP client for FastAPI backend — attaches the session JWT as a bearer token."""

from __future__ import annotations

import os

import httpx
import streamlit as st

API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")


def _auth_headers() -> dict[str, str]:
    token = st.session_state.get("jwt") if hasattr(st, "session_state") else None
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def rag_query(query: str, session_id: str) -> dict:
    """Legacy direct-RAG endpoint (kept for backward compatibility)."""
    with httpx.Client(timeout=120.0) as client:
        response = client.post(
            f"{API_URL}/rag/query",
            json={"query": query, "session_id": session_id},
            headers=_auth_headers(),
        )
        response.raise_for_status()
        return response.json()


def chat(message: str, session_id: str) -> dict:
    with httpx.Client(timeout=180.0) as client:
        response = client.post(
            f"{API_URL}/chat",
            json={"message": message, "session_id": session_id},
            headers=_auth_headers(),
        )
        response.raise_for_status()
        return response.json()


def admin_fetch(path: str) -> dict | list:
    with httpx.Client(timeout=30.0) as client:
        response = client.get(
            f"{API_URL}{path}",
            headers=_auth_headers(),
        )
        response.raise_for_status()
        return response.json()


def admin_post(path: str, json: dict) -> dict:
    with httpx.Client(timeout=30.0) as client:
        response = client.post(
            f"{API_URL}{path}",
            json=json,
            headers={**_auth_headers(), "Content-Type": "application/json"},
        )
        response.raise_for_status()
        return response.json()


def admin_patch(path: str, json: dict) -> dict:
    with httpx.Client(timeout=30.0) as client:
        response = client.patch(
            f"{API_URL}{path}",
            json=json,
            headers={**_auth_headers(), "Content-Type": "application/json"},
        )
        response.raise_for_status()
        return response.json()


def admin_delete(path: str) -> None:
    with httpx.Client(timeout=30.0) as client:
        response = client.delete(
            f"{API_URL}{path}",
            headers=_auth_headers(),
        )
        response.raise_for_status()


def public_api_url() -> str:
    return API_URL
