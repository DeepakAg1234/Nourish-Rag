"""Public page for the dietary guidance chatbot.

Streamlit calls answer_question. It does not retrieve, embed, or call the
chat model on its own. Each submit sends only the current question.
"""

from __future__ import annotations

import html
import os

import streamlit as st

_SECRET_KEYS = ("CHAT_MODEL", "CHAT_API_KEY", "CHAT_BASE_URL")

_PROMPTS = (
    "How long can cooked rice stay in the fridge?",
    "What does a healthy diet look like?",
    "How should I chill and defrost food safely?",
)


def apply_chat_secrets() -> None:
    """Copy Streamlit secrets into the environment when a name is unset.

    Existing variables win, matching load_env_file in src.answer.
    """
    if all(os.environ.get(key) for key in _SECRET_KEYS):
        return
    try:
        secrets = st.secrets
    except Exception:
        return
    for key in _SECRET_KEYS:
        if os.environ.get(key):
            continue
        try:
            value = secrets[key]
        except Exception:
            continue
        if value:
            os.environ[key] = str(value)


@st.cache_resource(show_spinner="Preparing the guidance index…")
def ensure_index() -> int:
    """Load the embedding model once, and build Chroma when it is missing."""
    from src.index_corpus import COLLECTION_NAME, build_index, get_client, get_model

    get_model()
    client = get_client()
    try:
        collection = client.get_collection(COLLECTION_NAME)
        count = collection.count()
    except Exception:
        count = 0
    if count:
        return count
    return build_index(client=client)


def _init_state() -> None:
    st.session_state.setdefault("result", None)
    st.session_state.setdefault("asked", "")
    st.session_state.setdefault("error", "")
    st.session_state.setdefault("form_id", 0)


def _remember(question: str) -> None:
    """Answer this question only, then rerun so the box can clear."""
    from src.answer import AnswerError
    from src.app import answer_question
    from src.retrieve import RetrieveError

    st.session_state.error = ""
    st.session_state.asked = question
    try:
        with st.spinner("Checking the guidance…"):
            st.session_state.result = answer_question(question)
    except AnswerError as exc:
        st.session_state.result = None
        st.session_state.error = str(exc)
    except RetrieveError as exc:
        st.session_state.result = None
        st.session_state.error = str(exc)
    except Exception:
        st.session_state.result = None
        st.session_state.error = "The question could not be answered."
    else:
        st.session_state.form_id += 1
    st.rerun()


def _render_result(result: dict | None, asked: str) -> None:
    if not result:
        return
    st.subheader(asked)
    stage = result.get("stage")
    if stage == "answered":
        for index, section in enumerate(result.get("sections") or [], start=1):
            for claim in section.get("claims") or []:
                st.html(_paragraph(claim))
            citation = section.get("citation") or {}
            name = _link_label(str(citation.get("document_name", "")))
            url = str(citation.get("source_url", ""))
            publisher = str(citation.get("publisher", ""))
            year = citation.get("year", "")
            st.markdown(f"{index}. [{name}]({url}) — {publisher}, {year}")
    else:
        st.html(_paragraph(str(result.get("message") or "")))

    if stage == "out_of_scope":
        log = "stage=out_of_scope"
    else:
        log = f"stage={stage}    filter={result.get('filter', 'all')}"
    with st.expander("Log"):
        st.text(log)


def _paragraph(text: str) -> str:
    """Show text as text. A refusal must not pick up links from Markdown."""
    return "<p>" + html.escape(text) + "</p>"


def _link_label(text: str) -> str:
    return text.replace("[", "\\[").replace("]", "\\]")


def main() -> None:
    st.set_page_config(page_title="Nourish", layout="centered")
    apply_chat_secrets()
    _init_state()
    st.title("Nourish")
    st.caption("One question at a time, answered only from official guidance.")
    count = ensure_index()
    st.caption(f"Indexed chunks: {count}")

    for prompt in _PROMPTS:
        if st.button(prompt, key=f"prompt-{prompt}"):
            _remember(prompt)

    with st.form("ask"):
        question = st.text_area(
            "Question",
            placeholder="Ask about a way of eating, or how long to keep food.",
            key=f"question-{st.session_state.form_id}",
        )
        submitted = st.form_submit_button("Ask")

    if submitted:
        if not isinstance(question, str) or not question.strip():
            st.session_state.error = "Enter a question."
            st.session_state.result = None
            st.session_state.asked = ""
        else:
            _remember(question.strip())

    if st.session_state.error:
        st.error(st.session_state.error)
    _render_result(st.session_state.result, st.session_state.asked)


main()
