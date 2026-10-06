"""Stateless CLI and localhost page. Each question is independent.

There is no chat history. The page calls answer_question. It does not
grow a second pipeline.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from src.scope import OUT_OF_SCOPE, OUT_OF_SCOPE_MESSAGE, classify
from src.validate import ANSWERED, format_sections

_PAGE_PATH = Path(__file__).resolve().parents[1] / "web" / "index.html"
_HOST = "127.0.0.1"
_PORT = 8765


def answer_question(question: str, retrieve_fn=None, client=None) -> dict:
    """Run scope, retrieval, the coverage gate, and the citation check.

    There is no document_id argument. Phrase detection is the only filter.
    """
    if classify(question) == OUT_OF_SCOPE:
        return {
            "stage": OUT_OF_SCOPE,
            "chunk_ids": [],
            "message": OUT_OF_SCOPE_MESSAGE,
            "sections": [],
        }

    from src.answer import respond
    from src.retrieve import resolve_document_filter, retrieve as default_retrieve

    search = retrieve_fn if retrieve_fn is not None else default_retrieve
    chunks = search(question)
    document_filter = resolve_document_filter(question)
    result = respond(question, chunks, document_filter, client=client)
    result["filter"] = document_filter or "all"
    result["chunk_ids"] = [chunk["chunk_id"] for chunk in chunks]
    return result


def format_log(result: dict) -> str:
    """One line: stage, and, when retrieval ran, the filter and chunk ids.

    An out-of-scope line has no chunk ids.
    """
    if result["stage"] == OUT_OF_SCOPE:
        return f"stage={OUT_OF_SCOPE}"
    chunk_ids = ",".join(result["chunk_ids"])
    return f"stage={result['stage']}\tfilter={result['filter']}\tchunks={chunk_ids}"


def format_result(result: dict) -> str:
    """Log line, then the refusal or the cited sections."""
    if result["stage"] == ANSWERED:
        body = format_sections(result["sections"])
    else:
        body = result["message"]
    if not body:
        return format_log(result)
    return f"{format_log(result)}\n{body}"


def question_response(raw: bytes) -> tuple[int, dict]:
    """JSON body for one question. An empty question does not call the model path.

    A document_id in the body is ignored. Phrase detection stays inside
    answer_question.
    """
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return 400, {"error": "question is empty"}
    if not isinstance(payload, dict):
        return 400, {"error": "question is empty"}
    question = payload.get("question")
    if not isinstance(question, str) or not question.strip():
        return 400, {"error": "question is empty"}
    return 200, answer_question(question.strip())


class _QuestionHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path.split("?", 1)[0] not in {"/", "/index.html"}:
            self.send_error(404)
            return
        body = _PAGE_PATH.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path.split("?", 1)[0] != "/question":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0") or "0")
        status, payload = question_response(self.rfile.read(length))
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, fmt: str, *args) -> None:
        return


def serve() -> None:
    """Listen on localhost only. GET serves the page. POST /question answers one question."""
    server = ThreadingHTTPServer((_HOST, _PORT), _QuestionHandler)
    print(f"http://{_HOST}:{_PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if args == ["--serve"]:
        serve()
        return
    question = " ".join(args).strip()
    if not question:
        print('usage: python -m src.app "question"', file=sys.stderr)
        raise SystemExit(2)
    try:
        result = answer_question(question)
    except Exception as exc:
        # Match by name so an out-of-scope question does not import the index.
        if type(exc).__module__ != "src.retrieve" or type(exc).__name__ != "RetrieveError":
            raise
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(format_result(result))


if __name__ == "__main__":
    main()
