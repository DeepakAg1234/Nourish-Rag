"""Public page for the dietary guidance chatbot.

Streamlit calls answer_question. It does not retrieve, embed, or call the
chat model on its own. Each submit sends only the current question.
The sidebar can show up to five earlier questions. Opening one redisplays
the stored result and does not send it with the next question.
"""

from __future__ import annotations

import copy
import html
import json
import os
from pathlib import Path

import streamlit as st

_SECRET_KEYS = ("CHAT_MODEL", "CHAT_API_KEY", "CHAT_BASE_URL")
_HISTORY_LIMIT = 5
_CATALOG_PATH = Path(__file__).resolve().parent / "data" / "catalog.json"

_PROMPTS = (
    "What does a healthy diet look like?",
    "How should I chill and defrost food safely?",
)

_PLACEHOLDER = "Ask about a way of eating, or how long to keep food."


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
    st.session_state.setdefault("history", [])
    st.session_state.setdefault("view", "ask")


def _push_history(history: list[dict], question: str, result: dict) -> list[dict]:
    """Keep the newest five questions. A repeat moves to the top."""
    kept = [item for item in history if item["question"] != question]
    kept.insert(0, {"question": question, "result": copy.deepcopy(result)})
    return kept[:_HISTORY_LIMIT]


def _remember(question: str) -> None:
    """Answer this question only, then rerun so the box can clear."""
    from src.answer import AnswerError
    from src.app import answer_question
    from src.retrieve import RetrieveError

    st.session_state.error = ""
    st.session_state.asked = question
    st.session_state.view = "ask"
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
        st.session_state.history = _push_history(
            st.session_state.history, question, st.session_state.result
        )
    st.rerun()


def _open_saved(index: int) -> None:
    """Show a stored result. This does not call the model."""
    item = st.session_state.history[index]
    st.session_state.view = "ask"
    st.session_state.asked = item["question"]
    st.session_state.result = item["result"]
    st.session_state.error = ""


def _start_new() -> None:
    st.session_state.view = "ask"
    st.session_state.result = None
    st.session_state.asked = ""
    st.session_state.error = ""


def _show_sources() -> None:
    st.session_state.view = "sources"


def _sidebar_label(question: str) -> str:
    text = " ".join(question.split())
    if len(text) <= 64:
        return text
    return text[:61].rstrip() + "…"


def _load_catalog() -> list[dict]:
    return json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))


def _active_history_index() -> int | None:
    if st.session_state.view != "ask" or not st.session_state.result:
        return None
    asked = st.session_state.asked
    for index, item in enumerate(st.session_state.history):
        if item["question"] == asked:
            return index
    return None


def _inject_css() -> None:
    active = _active_history_index()
    active_rule = ""
    if active is not None:
        active_rule = (
            f".st-key-hist-{active} button {{"
            "background: #fffcf8;"
            "border-color: #1f4d3a;"
            "color: #1c1915;"
            "}"
        )
    st.markdown(
        f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Sans:ital,opsz,wght@0,9..40,400;0,9..40,500;0,9..40,600;1,9..40,400&family=Newsreader:opsz,wght@6..72,400;6..72,500&display=swap');
        html, body, [class*="css"] {{
          font-family: "DM Sans", "Segoe UI", sans-serif;
        }}
        footer {{ visibility: hidden; height: 0; }}
        [data-testid="stSidebar"] {{
          background: #f6f3ee;
          border-right: 1px solid #e6e0d6;
        }}
        [data-testid="stSidebar"] button {{
          justify-content: flex-start;
          text-align: left;
          border-radius: 8px;
        }}
        [data-testid="stSidebar"] button p {{
          text-align: left;
          width: 100%;
        }}
        .nourish-wordmark {{
          margin: 0.2rem 0 0.85rem;
          font-family: Newsreader, Georgia, serif;
          font-size: 1.7rem;
          font-weight: 500;
          letter-spacing: -0.02em;
          color: #1c1915;
        }}
        .nourish-trust {{
          margin: 0 0 1.1rem;
          padding: 0;
          list-style: none;
          color: #6b645c;
          font-size: 0.92rem;
        }}
        .nourish-trust li {{
          position: relative;
          margin: 0.28rem 0;
          padding-left: 0.95rem;
        }}
        .nourish-trust li::before {{
          content: "";
          position: absolute;
          left: 0;
          top: 0.45rem;
          width: 6px;
          height: 6px;
          background: #a6844a;
          transform: rotate(45deg);
        }}
        .nourish-recent {{
          margin: 1.15rem 0 0.35rem;
          color: #6b645c;
          font-size: 0.78rem;
          font-weight: 600;
          letter-spacing: 0.04em;
          text-transform: uppercase;
        }}
        [data-testid="stMainBlockContainer"] {{
          max-width: 920px;
        }}
        .stMain:has(.nourish-landing) [data-testid="stMainBlockContainer"] {{
          min-height: 100vh;
          display: flex;
          flex-direction: column;
          justify-content: center;
          padding-top: 0;
          padding-bottom: 2rem;
        }}
        .stMain:has(.nourish-landing) [data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] {{
          flex: 0 0 auto !important;
        }}
        .stMarkdown p.nourish-kicker {{
          margin: 0 0 0.35rem;
          font-family: Newsreader, Georgia, serif;
          font-size: 1.35rem;
          line-height: 1.2;
          color: #1c1915;
        }}
        .stMarkdown p.nourish-headline {{
          margin: 0 0 0.55rem;
          font-family: Newsreader, Georgia, serif;
          font-size: 1.875rem;
          font-weight: 500;
          line-height: 1.2;
          letter-spacing: -0.02em;
          color: #1c1915;
        }}
        .nourish-landing p.nourish-headline {{
          font-size: 2.25rem;
        }}
        .stMarkdown p.nourish-proof {{
          margin: 0 0 0.9rem;
          color: #6b645c;
          font-size: 1rem;
          line-height: 1.45;
        }}
        [data-testid="stTextArea"] textarea {{
          background: #fffcf8;
          border-radius: 12px;
          min-height: 110px;
        }}
        .st-key-prompts button {{
          border-radius: 999px;
          background: #fffcf8;
          border: 1px solid #e6e0d6;
          font-weight: 400;
          white-space: normal;
          line-height: 1.3;
          min-height: 44px;
        }}
        .nourish-source {{
          background: #fffcf8;
          border: 1px solid #e6e0d6;
          border-radius: 12px;
          padding: 0.9rem 1rem 0.7rem;
          margin: 0 0 0.75rem;
        }}
        .nourish-source h2 {{
          margin: 0 0 0.2rem;
          font-family: Newsreader, Georgia, serif;
          font-size: 1.25rem;
          font-weight: 500;
        }}
        .nourish-source p {{
          margin: 0;
          color: #6b645c;
        }}
        .nourish-source a {{
          color: #1f4d3a;
          font-weight: 500;
        }}
        {active_rule}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_sidebar() -> None:
    with st.sidebar:
        st.markdown('<p class="nourish-wordmark">Nourish</p>', unsafe_allow_html=True)
        st.markdown(
            """
            <ul class="nourish-trust">
              <li>The document behind every claim</li>
              <li>Seven official health guides</li>
              <li>No medical or weight advice</li>
            </ul>
            """,
            unsafe_allow_html=True,
        )
        st.button("New question", width="stretch", on_click=_start_new)
        st.markdown('<p class="nourish-recent">Recent</p>', unsafe_allow_html=True)
        history = st.session_state.history
        if not history:
            st.caption("Your last five questions will show up here.")
        for index, item in enumerate(history):
            st.button(
                _sidebar_label(item["question"]),
                key=f"hist-{index}",
                help=item["question"],
                width="stretch",
                wrap=True,
                on_click=_open_saved,
                args=(index,),
            )
        st.button("Sources", width="stretch", on_click=_show_sources)


def _render_landing() -> None:
    st.markdown(
        """
        <div class="nourish-landing">
          <p class="nourish-kicker">Nourish</p>
          <p class="nourish-headline">General food advice guesses.<br>This quotes the agency that published the rule.</p>
          <p class="nourish-proof">Don't get fooled by general advice. If WHO, FAO, FDA, USDA, the UK Food Standards Agency,<br>or Public Health England didn't publish it, Nourish won't say it.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    with st.form("ask"):
        question = st.text_area(
            "Question",
            placeholder=_PLACEHOLDER,
            label_visibility="collapsed",
            height=110,
            key=f"question-{st.session_state.form_id}",
        )
        submitted = st.form_submit_button("Ask", type="primary", width="stretch")
    if submitted:
        if not isinstance(question, str) or not question.strip():
            st.session_state.error = "Enter a question."
            st.session_state.result = None
            st.session_state.asked = ""
            st.rerun()
        else:
            _remember(question.strip())
    if st.session_state.error:
        st.error(st.session_state.error)
    with st.container(key="prompts"):
        columns = st.columns(len(_PROMPTS), gap="small")
        for column, prompt in zip(columns, _PROMPTS, strict=True):
            with column:
                if st.button(prompt, key=f"prompt-{prompt}", width="stretch", wrap=True):
                    _remember(prompt)


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


def _render_sources() -> None:
    st.markdown(
        '<p class="nourish-headline">Sources</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<p class="nourish-proof">These seven documents are the only sources an answer can cite.</p>',
        unsafe_allow_html=True,
    )
    for doc in _load_catalog():
        name = html.escape(str(doc["document_name"]))
        publisher = html.escape(str(doc["publisher"]))
        year = html.escape(str(doc["year"]))
        url = html.escape(str(doc["source_url"]), quote=True)
        st.markdown(
            f"""
            <article class="nourish-source">
              <h2>{name}</h2>
              <p>{publisher}, {year}</p>
              <a href="{url}">Official source</a>
            </article>
            """,
            unsafe_allow_html=True,
        )


def _paragraph(text: str) -> str:
    """Show text as text. A refusal must not pick up links from Markdown."""
    return "<p>" + html.escape(text) + "</p>"


def _link_label(text: str) -> str:
    return text.replace("[", "\\[").replace("]", "\\]")


def main() -> None:
    st.set_page_config(
        page_title="Nourish",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    apply_chat_secrets()
    _init_state()
    ensure_index()
    _inject_css()
    _render_sidebar()
    if st.session_state.view == "sources":
        _render_sources()
        return
    if st.session_state.result:
        _render_result(st.session_state.result, st.session_state.asked)
        followup = st.chat_input(_PLACEHOLDER)
        if followup and followup.strip():
            _remember(followup.strip())
        return
    _render_landing()


if __name__ == "__main__":
    main()
