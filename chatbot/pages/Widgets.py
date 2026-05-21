"""Widget configuration — list, create, edit, delete, embed snippet."""

from __future__ import annotations

import json
from typing import Any

import streamlit as st

from chatbot.api_client import (
    admin_delete,
    admin_fetch,
    admin_patch,
    admin_post,
    public_api_url,
)
from chatbot.auth import require_auth, sign_out_button

ALL_TOOLS = [
    "classify_issue",
    "extract_entities",
    "summarize_thread",
    "search_docs",
    "write_memory",
]

st.set_page_config(page_title="Widgets", layout="wide")
require_auth()

st.header("Embeddable widgets")
st.caption("Configure embeddable widgets and their allowed host origins.")
sign_out_button()


def _load_widgets() -> list[dict[str, Any]]:
    try:
        result = admin_fetch("/admin/widgets")
    except Exception as exc:
        st.error(f"Could not load widgets: {exc}")
        return []
    if isinstance(result, list):
        return result
    if isinstance(result, dict) and "widgets" in result:
        return list(result["widgets"])
    return []


def _embed_snippet(widget_id: str) -> str:
    return (
        f'<script src="{public_api_url()}/widget.js" '
        f'data-widget-id="{widget_id}"></script>'
    )


# --- list --------------------------------------------------------------------

widgets = _load_widgets()
st.subheader(f"Existing widgets ({len(widgets)})")

if not widgets:
    st.info("No widgets configured yet. Create one below.")

for widget in widgets:
    wid = widget["id"]
    with st.expander(f"{widget.get('name', '?')}  —  {wid}"):
        col1, col2 = st.columns([2, 1])
        with col1:
            new_name = st.text_input(
                "Name", value=widget.get("name", ""), key=f"name-{wid}"
            )
            origins_str = st.text_area(
                "Allowed origins (one per line, exact http(s) origin or *)",
                value="\n".join(widget.get("allowed_origins") or []),
                key=f"origins-{wid}",
                height=120,
            )
            greeting = st.text_area(
                "Greeting (shown when the widget opens)",
                value=widget.get("greeting") or "",
                key=f"greeting-{wid}",
                height=80,
            )
            theme_json = st.text_area(
                "Theme (JSON; supports primary_color, bubble_color, title)",
                value=json.dumps(widget.get("theme") or {}, indent=2),
                key=f"theme-{wid}",
                height=120,
            )
            enabled = st.multiselect(
                "Enabled tools",
                options=ALL_TOOLS,
                default=widget.get("enabled_tools") or [],
                key=f"tools-{wid}",
            )
            if st.button("Save", key=f"save-{wid}"):
                try:
                    body = {
                        "name": new_name,
                        "allowed_origins": [
                            o.strip() for o in origins_str.splitlines() if o.strip()
                        ],
                        "greeting": greeting or None,
                        "theme": json.loads(theme_json) if theme_json.strip() else None,
                        "enabled_tools": enabled,
                    }
                    admin_patch(f"/admin/widgets/{wid}", body)
                    st.success("Saved.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Save failed: {exc}")
            if st.button("Delete", key=f"del-{wid}"):
                try:
                    admin_delete(f"/admin/widgets/{wid}")
                    st.success("Deleted.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Delete failed: {exc}")
        with col2:
            st.markdown("**Embed snippet**")
            st.code(_embed_snippet(wid), language="html")
            st.caption(f"Updated: {widget.get('updated_at', '—')}")


# --- create ------------------------------------------------------------------

st.divider()
st.subheader("Create a new widget")

with st.form("create-widget"):
    name = st.text_input("Name", placeholder="docs.example.com support")
    origins = st.text_area(
        "Allowed origins (one per line)",
        placeholder="https://docs.example.com\nhttps://staging.example.com",
        height=100,
    )
    greeting_in = st.text_area(
        "Greeting",
        placeholder="Hi! Ask me anything about our docs.",
        height=70,
    )
    theme_in = st.text_area(
        "Theme JSON (optional)",
        value='{"primary_color": "#2563eb", "title": "Docs Copilot"}',
        height=100,
    )
    tools_in = st.multiselect(
        "Enabled tools",
        options=ALL_TOOLS,
        default=["search_docs"],
    )
    submitted = st.form_submit_button("Create")
    if submitted:
        try:
            payload = {
                "name": name,
                "allowed_origins": [
                    o.strip() for o in (origins or "").splitlines() if o.strip()
                ],
                "greeting": greeting_in or None,
                "theme": json.loads(theme_in) if theme_in.strip() else None,
                "enabled_tools": tools_in,
            }
            created = admin_post("/admin/widgets", payload)
            st.success(f"Created widget {created['id']}.")
            st.code(_embed_snippet(created["id"]), language="html")
            st.rerun()
        except Exception as exc:
            st.error(f"Creation failed: {exc}")
