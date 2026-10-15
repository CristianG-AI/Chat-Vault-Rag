#!/usr/bin/env python3
"""
app.py — Streamlit chat UI over the RAG loop in ask.py.

Every question goes through `ask()` → retrieval (Chroma) + generation with
citations (Claude). Streaming arrives live in the browser via the `on_text`
callback — the same one the CLI uses.

Run locally (chat with YOUR own vault):
    streamlit run app.py        # after building your index — see README Quickstart

Public demo on Streamlit Cloud:
    Set DEMO_MODE=true plus OPENAI_API_KEY / ANTHROPIC_API_KEY in Settings → Secrets.
    On first boot the app auto-builds a vector index from demo_vault/ (~30 s,
    ~$0.002 in embeddings) so visitors can try it with zero setup.
"""

# ── ChromaDB sqlite shim (Streamlit Cloud / Linux) ──────────────────────
# ChromaDB needs sqlite3 >= 3.35; some hosted Linux images ship an older one.
# pysqlite3-binary (installed only on Linux — see requirements.txt) provides a
# modern build; swap it in BEFORE anything imports chromadb. No-op locally.
try:
    __import__("pysqlite3")
    import sys
    sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
except ImportError:
    pass

import os

# Load API keys from Streamlit secrets (Streamlit Cloud) into os.environ BEFORE
# importing ask/search, which call load_dotenv() at import time. load_dotenv()
# does not overwrite existing env vars, so this takes priority.
try:
    import streamlit as _st
    for _key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        if _key not in os.environ:
            _val = _st.secrets.get(_key)
            if _val:
                os.environ[_key] = _val
except Exception:
    pass

import streamlit as st

from ask import ask

st.set_page_config(page_title="VaultChat", page_icon="💬")

# DEMO_MODE serves the public synthetic demo_vault with zero setup. Left off
# (the default), the app chats with YOUR own index built via the Quickstart.
DEMO_MODE = os.getenv("DEMO_MODE", "").lower() in ("1", "true", "yes")

if DEMO_MODE:
    from demo_setup import CHROMA_DIR, ensure_index
    # Auto-build the demo index on cold start.
    if not CHROMA_DIR.exists() or not any(CHROMA_DIR.iterdir()):
        _status = st.empty()
        with st.spinner("Building vector index… (~30 s on first run)"):
            ensure_index(status_fn=lambda msg: _status.caption(msg))
        _status.empty()
        st.rerun()

st.title("💬 VaultChat")
if DEMO_MODE:
    st.caption(
        "Chat with your notes — every answer cites the source note [n], and says "
        "\"I don't know\" instead of making things up.  \n"
        "> **Public demo:** a synthetic corpus of 12 ML/AI notes. The author's real "
        "(private) vault has 100+ study notes with measured eval metrics."
    )
    st.info(
        "**Want this on your own vault?** "
        "[Run it yourself, free & open source](https://github.com/CristianG-AI/Chat-Vault-Rag) · "
        "[Join the waitlist for a hosted version](https://cristiang-ai.github.io/Chat-Vault-Rag/)",
        icon="💡",
    )
else:
    st.caption(
        "Chat with your own notes — every answer cites the source note [n], "
        "and says \"I don't know\" instead of making things up."
    )

# Streamlit re-runs the WHOLE script on every interaction (its core mental
# model). History lives in session_state so it survives those reruns.
if "history" not in st.session_state:
    st.session_state.history = []  # [{question, answer, sources, usage}]

# --- Sidebar: session state ---
with st.sidebar:
    st.header("Session")
    total = sum(t["usage"]["cost_usd"] for t in st.session_state.history)
    st.metric("Questions", len(st.session_state.history))
    st.metric("Total cost", f"${total:.4f}")
    st.divider()
    st.markdown(
        "**Pipeline:** question → embedding (OpenAI) → Chroma top-k → "
        "Claude → answer with `[n]` citations."
    )
    st.markdown(
        "If the answer isn't in your notes, the assistant says so — "
        "it doesn't make things up (anti-hallucination rule)."
    )
    if DEMO_MODE:
        st.divider()
        st.markdown("**Topics in this demo vault:**")
        st.markdown(
            "- Embeddings, Transformers, RAG\n"
            "- Gradient Descent, Backpropagation\n"
            "- Overfitting, Bias-Variance Tradeoff\n"
            "- Loss Functions, Neural Networks\n"
            "- Cross-Validation, Vector DBs\n"
            "- Prompt Engineering"
        )
        st.divider()
        st.markdown(
            "🧠 [Run this on your own vault](https://github.com/CristianG-AI/Chat-Vault-Rag)\n\n"
            "📬 [Join the waitlist](https://cristiang-ai.github.io/Chat-Vault-Rag/)"
        )


def render_turn(turn: dict) -> None:
    """Draw a full history turn: question, answer, and sources."""
    with st.chat_message("user"):
        st.markdown(turn["question"])
    with st.chat_message("assistant"):
        st.markdown(turn["answer"])
        u = turn["usage"]
        with st.expander(f"Sources ({len(turn['sources'])}) · ${u['cost_usd']}"):
            for s in turn["sources"]:
                head = f" › {s['heading']}" if s["heading"] else ""
                st.markdown(f"**[{s['n']}] {s['title']}**{head}  \n`{s['source']}`")


# Redraw history on each rerun
for turn in st.session_state.history:
    render_turn(turn)

question = st.chat_input("Ask your notes anything…")
if question:
    with st.chat_message("user"):
        st.markdown(question)

    with st.chat_message("assistant"):
        placeholder = st.empty()
        placeholder.markdown("_Searching your vault…_")
        parts: list[str] = []

        def on_text(t: str) -> None:
            parts.append(t)
            placeholder.markdown("".join(parts) + "▌")  # streaming cursor

        result = ask(question, on_text=on_text)
        placeholder.markdown(result["answer"])

    st.session_state.history.append(
        {
            "question": question,
            "answer": result["answer"],
            "sources": result["sources"],
            "usage": result["usage"],
        }
    )
    # Rerun so history + sidebar metrics refresh
    st.rerun()
