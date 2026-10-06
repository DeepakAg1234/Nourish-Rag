"""Phase 6 routing. A fake answer client stands in for the model.

These tests do not rebuild data/index/ and do not call the network.
"""

import inspect
import json
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

from src.app import answer_question, format_log, format_result, main, question_response
from src.ingest import load_catalog
from src.scope import OUT_OF_SCOPE, OUT_OF_SCOPE_MESSAGE
from src.validate import ANSWERED, NOT_IN_CORPUS, not_in_corpus_message

CATALOG = {row["document_id"]: row for row in load_catalog()}


class _RecordingClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def complete(self, messages):
        self.calls += 1
        return self.payload


class _ForbiddenClient:
    def complete(self, messages):
        raise AssertionError("model was called")


def _chunk(document_id: str, chunk_id: str, text: str) -> dict:
    row = CATALOG[document_id]
    return {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "document_name": row["document_name"],
        "publisher": row["publisher"],
        "year": row["year"],
        "source_url": row["source_url"],
        "section_heading": "Eggs",
        "text": text,
        "similarity": 0.2,
    }


def _section(document_id: str, claims: list[str]) -> dict:
    row = CATALOG[document_id]
    return {
        "document_id": document_id,
        "claims": claims,
        "citation": {
            "document_name": row["document_name"],
            "publisher": row["publisher"],
            "year": row["year"],
            "source_url": row["source_url"],
        },
    }


class OutOfScopeRoutingTests(unittest.TestCase):
    def test_weight_question_has_no_chunk_ids_and_does_not_retrieve(self):
        self._assert_stopped("What should I weigh?")

    def test_calorie_question_has_no_chunk_ids_and_does_not_retrieve(self):
        self._assert_stopped("How many calories should I eat to lose 5 kg?")

    def test_answer_question_has_no_document_id_argument(self):
        self.assertNotIn("document_id", inspect.signature(answer_question).parameters)

    def _assert_stopped(self, question: str):
        calls = []

        def retrieve_fn(*args, **kwargs):
            calls.append((args, kwargs))
            return []

        result = answer_question(question, retrieve_fn=retrieve_fn, client=_ForbiddenClient())
        self.assertEqual(result["stage"], OUT_OF_SCOPE)
        self.assertNotIn("filter", result)
        self.assertEqual(result["chunk_ids"], [])
        self.assertEqual(result["message"], OUT_OF_SCOPE_MESSAGE)
        self.assertEqual(result["sections"], [])
        self.assertEqual(calls, [])
        log = format_log(result)
        self.assertEqual(log, "stage=out_of_scope")
        self.assertNotIn("chunks=", log)


class InScopeRoutingTests(unittest.TestCase):
    def test_empty_retrieval_does_not_call_the_model(self):
        def retrieve_fn(question):
            return []

        result = answer_question(
            "How much protein is in 100 g of chicken?",
            retrieve_fn=retrieve_fn,
            client=_ForbiddenClient(),
        )
        self.assertEqual(result["stage"], NOT_IN_CORPUS)
        self.assertEqual(result["filter"], "all")
        self.assertEqual(result["chunk_ids"], [])
        self.assertEqual(result["message"], not_in_corpus_message(None))
        self.assertEqual(result["sections"], [])
        self.assertNotIn("qualified professional", result["message"])

    def test_retrieved_chunks_that_do_not_cover_keep_their_ids(self):
        chunks = [
            _chunk(
                "who-healthy-diet",
                "who-healthy-diet:12:0",
                "Unsaturated fats are preferable to saturated fats.",
            )
        ]

        def retrieve_fn(question):
            return chunks

        result = answer_question(
            "What is the smoke point of olive oil?",
            retrieve_fn=retrieve_fn,
            client=_RecordingClient({"covered": False, "sections": []}),
        )
        self.assertEqual(result["stage"], NOT_IN_CORPUS)
        self.assertEqual(result["filter"], "all")
        self.assertEqual(result["chunk_ids"], ["who-healthy-diet:12:0"])
        self.assertEqual(result["sections"], [])
        self.assertIn("Healthy diet (Fact sheet)", result["message"])

    def test_eatwell_oils_is_filtered_and_cites_only_that_document(self):
        chunks = [
            _chunk("eatwell-guide", "eatwell-guide:105:5", "Oils and spreads: choose unsaturated oils."),
        ]
        calls = []

        def retrieve_fn(*args, **kwargs):
            calls.append((args, kwargs))
            return chunks

        client = _RecordingClient(
            {
                "covered": True,
                "sections": [
                    _section("eatwell-guide", ["Choose unsaturated oils and use them in small amounts."])
                ],
            }
        )
        result = answer_question(
            "According to the Eatwell Guide, what does it say about oils?",
            retrieve_fn=retrieve_fn,
            client=client,
        )
        self.assertEqual(calls, [(("According to the Eatwell Guide, what does it say about oils?",), {})])
        self.assertEqual(client.calls, 1)
        self.assertEqual(result["stage"], ANSWERED)
        self.assertEqual(result["filter"], "eatwell-guide")
        self.assertEqual(result["chunk_ids"], ["eatwell-guide:105:5"])
        self.assertEqual(result["message"], "")
        self.assertEqual([section["document_id"] for section in result["sections"]], ["eatwell-guide"])
        self.assertEqual(result["sections"][0]["citation"]["source_url"], CATALOG["eatwell-guide"]["source_url"])

    def test_answered_log_lists_the_filter_and_chunk_ids(self):
        result = {
            "stage": ANSWERED,
            "filter": "all",
            "chunk_ids": ["cold-food-storage:2:35"],
            "message": "",
            "sections": [
                _section("cold-food-storage", ["Raw eggs in shell keep for 3 to 5 weeks in the refrigerator."])
            ],
        }
        text = format_result(result)
        self.assertTrue(text.startswith("stage=answered\tfilter=all\tchunks=cold-food-storage:2:35\n"))
        self.assertIn("3 to 5 weeks", text)
        self.assertIn(CATALOG["cold-food-storage"]["source_url"], text)


class CliTests(unittest.TestCase):
    def test_empty_question_exits_2_without_calling_answer_question(self):
        for argv in ([], ["   "]):
            with patch("src.app.answer_question") as answer:
                with self.assertRaises(SystemExit) as caught:
                    main(argv)
            self.assertEqual(caught.exception.code, 2)
            answer.assert_not_called()

    def test_cli_prints_the_result_log(self):
        payload = {
            "stage": OUT_OF_SCOPE,
            "chunk_ids": [],
            "message": OUT_OF_SCOPE_MESSAGE,
            "sections": [],
        }
        buf = StringIO()
        with patch("src.app.answer_question", return_value=payload), redirect_stdout(buf):
            main(["What should I weigh?"])
        printed = buf.getvalue()
        self.assertIn("stage=out_of_scope", printed)
        self.assertNotIn("chunks=", printed)
        self.assertIn("qualified professional", printed)


class PageHandlerTests(unittest.TestCase):
    def test_whitespace_question_does_not_call_answer_question(self):
        with patch("src.app.answer_question") as answer:
            status, body = question_response(b'{"question": "   "}')
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "question is empty")
        answer.assert_not_called()

    def test_document_id_in_the_body_is_ignored(self):
        raw = json.dumps(
            {"question": "What should I weigh?", "document_id": "eatwell-guide"}
        ).encode()
        status, body = question_response(raw)
        self.assertEqual(status, 200)
        self.assertEqual(body["stage"], OUT_OF_SCOPE)
        self.assertNotIn("filter", body)
        self.assertEqual(body["chunk_ids"], [])

    def test_serve_flag_starts_the_page(self):
        with patch("src.app.serve") as serve:
            main(["--serve"])
        serve.assert_called_once()
