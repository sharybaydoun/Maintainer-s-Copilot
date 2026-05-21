"""Chat page — calls POST /chat (tool-calling chatbot)."""

from __future__ import annotations

import streamlit as st

from chatbot.api_client import API_URL, chat
from chatbot.auth import require_auth, sign_out_button

st.set_page_config(page_title="Chat", layout="wide")
require_auth()

st.header("Maintainer chat")
st.caption(f"Backend: `{API_URL}/chat` · session `{st.session_state.get('session_id', '')}`")
sign_out_button()

if "messages" not in st.session_state:
    st.session_state["messages"] = []

for message in st.session_state["messages"]:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        if message.get("tool_trace"):
            with st.expander(f"Tool trace ({len(message['tool_trace'])})"):
                for call in message["tool_trace"]:
                    st.markdown(
                        f"**{call['name']}** · {call['result_summary']}"
                        + (f"\n\nerror: `{call['error']}`" if call.get("error") else "")
                    )
                    if call.get("arguments"):
                        st.json(call["arguments"])

if prompt := st.chat_input(
    "Ask about startup validation, paste an issue body to classify, etc."
):
    st.session_state["messages"].append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    try:
        data = chat(prompt, st.session_state["session_id"])
    except Exception as exc:
        st.error(f"API error: {exc}")
    else:
        reply = data.get("reply", "")
        sources = data.get("sources", [])
        tool_trace = data.get("tool_trace", [])
        refused = data.get("refused", False)

        display = reply
        if sources:
            display += "\n\n**Sources:** " + ", ".join(sources)

        st.session_state["messages"].append(
            {
                "role": "assistant",
                "content": display,
                "tool_trace": tool_trace,
            }
        )

        with st.chat_message("assistant"):
            if refused:
                st.warning(data.get("refusal_reason") or "Refused.")
            st.markdown(display)
            if tool_trace:
                with st.expander(f"Tool trace ({len(tool_trace)})"):
                    for call in tool_trace:
                        st.markdown(
                            f"**{call['name']}** · {call['result_summary']}"
                            + (
                                f"\n\nerror: `{call['error']}`"
                                if call.get("error")
                                else ""
                            )
                        )
                        if call.get("arguments"):
                            st.json(call["arguments"])
