"""Answer from retrieved chunks only.

The coverage gate is the empty kept list. It does not apply a second
similarity floor. The chat model is called only when at least one chunk
remains. Citation checks live in src.validate and run before anything
is returned.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from src.validate import validate

_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"

_SYSTEM_PROMPT = """\
You answer only from the chunks in the user message. Do not add facts from general knowledge, even when the chunks are silent.

Rules:
- Use only those chunks.
- Write one section per document_id. Several chunks from one document are one section. kitchen-companion:215:0 and kitchen-companion:217:0 share their text and still belong to one Kitchen Companion section.
- Never write a combined claim about what "the guidelines" say. Do not attribute one fact to more than one publisher.
- Copy citation fields from the chunk labels: document_name, publisher, year, and source_url. Do not invent a publisher, year, or URL.
- Leave an empty table cell empty. Do not fill it from the row above. kitchen-companion:216:10 does not inherit a time from the row above.
- Nearby chunks are not a substitute answer. Fat and oil guidance does not answer "What is the smoke point of olive oil?" A protein share of dietary energy does not answer "How much protein is in 100 g of chicken?" The WHO fat share and the Eatwell age-band table are population figures. Do not turn them into a personal calorie target.
- Set covered to false and leave sections an empty array when the chunks do not contain the answer.

Return only this JSON object:
{
  "covered": true,
  "sections": [
    {
      "document_id": "document id copied from a chunk label",
      "claims": ["what that document's chunks support"],
      "citation": {
        "document_name": "copied from the chunk label",
        "publisher": "copied from the chunk label",
        "year": 2018,
        "source_url": "copied from the chunk label"
      }
    }
  ]
}
"""


def load_env_file(path: Path = _ENV_PATH) -> None:
    """Read `.env` into the process environment. Existing variables win."""
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


class AnswerError(Exception):
    """The chat client is not configured."""


class ModelResponseError(Exception):
    """The model reply was not the answer JSON. Do not ask it to repair the reply."""


class OpenAIChatClient:
    """OpenAI-compatible chat client. Model name and key come from the environment."""

    def complete(self, messages: list[dict[str, str]]) -> dict:
        load_env_file()
        api_key = os.environ.get("CHAT_API_KEY")
        model = os.environ.get("CHAT_MODEL")
        if not api_key or not model:
            raise AnswerError("CHAT_MODEL and CHAT_API_KEY are required")
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise AnswerError("openai is not installed") from exc

        kwargs = {"api_key": api_key}
        base_url = os.environ.get("CHAT_BASE_URL")
        if base_url:
            kwargs["base_url"] = base_url
        client = OpenAI(**kwargs)
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or ""
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ModelResponseError("model did not return JSON") from exc
        if not isinstance(payload, dict):
            raise ModelResponseError("model JSON was not an object")
        return payload


def build_messages(
    question: str,
    chunks: list[dict],
    document_filter: str | None = None,
) -> list[dict[str, str]]:
    """Question, catalog search scope, and the full text of each kept chunk."""
    from src.validate import search_scope_names

    scope = "; ".join(search_scope_names(document_filter))
    labeled = "\n\n".join(_label_chunk(chunk) for chunk in chunks)
    user = f"Question: {question.strip()}\n\nSearch scope: {scope}\n\nChunks:\n{labeled}"
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def respond(
    question: str,
    chunks: list[dict],
    document_filter: str | None = None,
    client=None,
) -> dict:
    """Validate an answer, or refuse when the coverage gate has no chunks.

    An empty kept list does not call `client`. Retrieval already applied
    SIMILARITY_FLOOR; this function does not apply another one.
    """
    if not chunks:
        return validate({"covered": False, "sections": []}, [], document_filter)

    completer = client if client is not None else OpenAIChatClient()
    messages = build_messages(question, chunks, document_filter)
    try:
        payload = completer.complete(messages)
    except ModelResponseError:
        payload = {"covered": False, "sections": []}
    return validate(payload, chunks, document_filter)


def _label_chunk(chunk: dict) -> str:
    text = chunk.get("text") or ""
    return "\n".join(
        [
            f"chunk_id: {chunk.get('chunk_id', '')}",
            f"document_id: {chunk.get('document_id', '')}",
            f"document_name: {chunk.get('document_name', '')}",
            f"publisher: {chunk.get('publisher', '')}",
            f"year: {chunk.get('year', '')}",
            f"source_url: {chunk.get('source_url', '')}",
            f"section_heading: {chunk.get('section_heading', '')}",
            "text:",
            text,
        ]
    )
