"""Phase 5 checks. Fixtures stand in for the model. These tests do not call the network."""

import unittest

from src.answer import build_messages, respond
from src.ingest import load_catalog
from src.scope import OUT_OF_SCOPE_MESSAGE
from src.validate import (
    ANSWERED,
    NOT_IN_CORPUS,
    format_sections,
    not_in_corpus_message,
    validate,
)

CATALOG = {row["document_id"]: row for row in load_catalog()}


class _RecordingClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls: list[list[dict]] = []

    def complete(self, messages):
        self.calls.append(messages)
        return self.payload


class _ForbiddenClient:
    def complete(self, messages):
        raise AssertionError("model was called")


def _chunk(document_id: str, chunk_id: str, text: str, similarity: float = 0.2) -> dict:
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
        "similarity": similarity,
    }


def _section(document_id: str, claims: list[str], **overrides) -> dict:
    row = CATALOG[document_id]
    citation = {
        "document_name": row["document_name"],
        "publisher": row["publisher"],
        "year": row["year"],
        "source_url": row["source_url"],
    }
    citation.update(overrides)
    return {"document_id": document_id, "claims": claims, "citation": citation}


class CoverageGateTests(unittest.TestCase):
    def test_empty_retrieval_names_all_seven_and_does_not_call_the_model(self):
        result = respond("What is the smoke point of olive oil?", [], client=_ForbiddenClient())
        self.assertEqual(result["stage"], NOT_IN_CORPUS)
        self.assertEqual(result["sections"], [])
        self.assertEqual(result["message"], not_in_corpus_message(None))
        names = [row["document_name"] for row in load_catalog()]
        self.assertEqual(len(names), 7)
        for earlier, later in zip(names, names[1:]):
            self.assertLess(result["message"].index(earlier), result["message"].index(later))
        self.assertNotIn("qualified professional", result["message"])
        self.assertNotEqual(result["message"], OUT_OF_SCOPE_MESSAGE)

    def test_empty_filtered_retrieval_names_only_that_document(self):
        result = respond(
            "oils",
            [],
            document_filter="eatwell-guide",
            client=_ForbiddenClient(),
        )
        self.assertEqual(result["message"], not_in_corpus_message("eatwell-guide"))
        self.assertIn("The Eatwell Guide booklet", result["message"])
        self.assertNotIn("Cold Food Storage Chart", result["message"])
        self.assertNotIn("Kitchen Companion", result["message"])
        self.assertNotIn("http", result["message"])

    def test_a_low_similarity_chunk_still_calls_the_model(self):
        """The gate does not apply a second floor. Retrieval already did."""
        chunks = [
            _chunk(
                "cold-food-storage",
                "cold-food-storage:2:35",
                "Food: Eggs. Type: Raw eggs in shell. Refrigerator: 3 to 5 weeks.",
                similarity=0.0,
            )
        ]
        client = _RecordingClient(
            {
                "covered": True,
                "sections": [
                    _section(
                        "cold-food-storage",
                        ["Raw eggs in shell keep for 3 to 5 weeks in the refrigerator."],
                    )
                ],
            }
        )
        result = respond("How long can raw eggs stay in the refrigerator?", chunks, client=client)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(result["stage"], ANSWERED)
        prompt = client.calls[0][1]["content"]
        self.assertIn("3 to 5 weeks", prompt)
        self.assertIn("cold-food-storage:2:35", prompt)


class PromptTests(unittest.TestCase):
    def test_prompt_labels_full_text_and_abstain_rules(self):
        long_text = "full stored text " * 80
        chunks = [
            _chunk("kitchen-companion", "kitchen-companion:215:0", long_text.strip()),
            _chunk("kitchen-companion", "kitchen-companion:217:0", long_text.strip()),
        ]
        messages = build_messages("What do the guidelines say about fats and oils?", chunks)
        system = messages[0]["content"]
        user = messages[1]["content"]
        self.assertIn("Use only those chunks.", system)
        self.assertIn('what "the guidelines" say', system)
        self.assertIn("kitchen-companion:216:10", system)
        self.assertIn("smoke point of olive oil", system)
        self.assertIn("100 g of chicken", system)
        self.assertIn("personal calorie target", system)
        self.assertIn("covered", system)
        self.assertIn(long_text.strip(), user)
        self.assertEqual(user.count(long_text.strip()), 2)
        for field in (
            "chunk_id: kitchen-companion:215:0",
            "chunk_id: kitchen-companion:217:0",
            "document_id: kitchen-companion",
            "document_name: Kitchen Companion: Your Safe Food Handbook",
            "publisher: USDA Food Safety and Inspection Service",
            "year: 2008",
            "source_url: https://www.fsis.usda.gov/sites/default/files/media_file/2020-12/Kitchen-Companion.pdf",
            "section_heading: Eggs",
        ):
            self.assertIn(field, user)
        for name in (row["document_name"] for row in load_catalog()):
            self.assertIn(name, user)

    def test_filtered_prompt_names_only_the_filtered_document(self):
        chunks = [_chunk("eatwell-guide", "eatwell-guide:105:4", "Oils and spreads: choose unsaturated oils.")]
        user = build_messages("oils", chunks, document_filter="eatwell-guide")[1]["content"]
        self.assertIn("Search scope: The Eatwell Guide booklet", user)
        self.assertNotIn("Cold Food Storage Chart", user)
        self.assertIn("Oils and spreads: choose unsaturated oils.", user)


class ValidateTests(unittest.TestCase):
    def test_covered_false_discards_sections_and_names_the_scope(self):
        chunks = [_chunk("who-healthy-diet", "who-healthy-diet:1:0", "Less than 30% of total energy from fat.")]
        payload = {
            "covered": False,
            "sections": [_section("who-healthy-diet", ["Less than 30% of total energy intake from fat."])],
        }
        result = validate(payload, chunks)
        self.assertEqual(result["stage"], NOT_IN_CORPUS)
        self.assertEqual(result["sections"], [])
        self.assertEqual(result["message"], not_in_corpus_message(None))
        self.assertNotIn("30%", result["message"])

        filtered = validate(payload, chunks, document_filter="who-healthy-diet")
        self.assertEqual(filtered["message"], not_in_corpus_message("who-healthy-diet"))
        self.assertIn("Healthy diet (Fact sheet)", filtered["message"])
        self.assertNotIn("The Eatwell Guide booklet", filtered["message"])

    def test_two_documents_stay_separate_and_follow_catalog_order(self):
        chunks = [
            _chunk("kitchen-companion", "kitchen-companion:1:0", "Store salads for 3 to 5 days."),
            _chunk("cold-food-storage", "cold-food-storage:2:0", "Salads: 3 to 4 days."),
        ]
        payload = {
            "covered": True,
            "sections": [
                _section("kitchen-companion", ["Salads keep for 3 to 5 days in the refrigerator."]),
                _section("cold-food-storage", ["Salads keep for 3 to 4 days in the refrigerator."]),
            ],
        }
        result = validate(payload, chunks)
        self.assertEqual(
            [section["document_id"] for section in result["sections"]],
            ["cold-food-storage", "kitchen-companion"],
        )
        self.assertEqual(result["sections"][0]["claims"], ["Salads keep for 3 to 4 days in the refrigerator."])
        self.assertEqual(result["sections"][1]["claims"], ["Salads keep for 3 to 5 days in the refrigerator."])
        rendered = format_sections(result["sections"])
        cold, kitchen = rendered.split("\n\n")
        self.assertIn("3 to 4 days", cold)
        self.assertNotIn("3 to 5 days", cold)
        self.assertIn("FoodSafety.gov", cold)
        self.assertNotIn("USDA Food Safety and Inspection Service", cold)
        self.assertIn("3 to 5 days", kitchen)
        self.assertNotIn("3 to 4 days", kitchen)
        self.assertIn("USDA Food Safety and Inspection Service", kitchen)
        self.assertNotIn("the guidelines", rendered.casefold())

    def test_egg_pair_renders_two_sections(self):
        chunks = [
            _chunk(
                "cold-food-storage",
                "cold-food-storage:2:35",
                "Food: Eggs. Type: Raw eggs in shell. Refrigerator [40°F (4°C) or below]: 3 to 5 weeks.",
            ),
            _chunk(
                "kitchen-companion",
                "kitchen-companion:285:0",
                "Egg Storage Chart. Product: Raw eggs in shell. Refrigerator: 3 to 5 weeks.",
            ),
        ]
        payload = {
            "covered": True,
            "sections": [
                _section("kitchen-companion", ["Raw eggs in shell: refrigerator 3 to 5 weeks."]),
                _section("cold-food-storage", ["Raw eggs in shell: refrigerator 3 to 5 weeks."]),
            ],
        }
        result = validate(payload, chunks)
        self.assertEqual(result["stage"], ANSWERED)
        self.assertEqual(
            [section["document_id"] for section in result["sections"]],
            ["cold-food-storage", "kitchen-companion"],
        )
        rendered = format_sections(result["sections"])
        self.assertIn("https://www.foodsafety.gov/food-safety-charts/cold-food-storage-charts", rendered)
        self.assertIn("https://www.fsis.usda.gov/sites/default/files/media_file/2020-12/Kitchen-Companion.pdf", rendered)
        self.assertEqual(rendered.count("3 to 5 weeks"), 2)
        self.assertNotIn("ham", rendered.casefold())

    def test_wrong_citation_url_drops_that_section(self):
        chunks = [
            _chunk("cold-food-storage", "cold-food-storage:2:35", "Raw eggs in shell: 3 to 5 weeks."),
            _chunk("kitchen-companion", "kitchen-companion:285:0", "Raw eggs in shell: 3 to 5 weeks."),
        ]
        payload = {
            "covered": True,
            "sections": [
                _section(
                    "cold-food-storage",
                    ["Raw eggs in shell: refrigerator 3 to 5 weeks."],
                    source_url="https://example.com/not-the-catalog",
                ),
                _section("kitchen-companion", ["Raw eggs in shell: refrigerator 3 to 5 weeks."]),
            ],
        }
        result = validate(payload, chunks)
        self.assertEqual([section["document_id"] for section in result["sections"]], ["kitchen-companion"])
        self.assertNotIn("example.com", format_sections(result["sections"]))

        only_bad = validate(
            {
                "covered": True,
                "sections": [
                    _section(
                        "cold-food-storage",
                        ["Raw eggs in shell: refrigerator 3 to 5 weeks."],
                        source_url="https://example.com/not-the-catalog",
                    )
                ],
            },
            chunks[:1],
        )
        self.assertEqual(only_bad["stage"], NOT_IN_CORPUS)
        self.assertEqual(only_bad["sections"], [])
        self.assertNotIn("example.com", only_bad["message"])

    def test_document_outside_the_retrieved_set_is_dropped(self):
        chunks = [_chunk("eatwell-guide", "eatwell-guide:105:4", "Oils and spreads.")]
        payload = {
            "covered": True,
            "sections": [
                _section("eatwell-guide", ["Choose unsaturated oils and spreads."]),
                _section("who-healthy-diet", ["Less than 30% of total energy from fat."]),
            ],
        }
        result = validate(payload, chunks)
        self.assertEqual([section["document_id"] for section in result["sections"]], ["eatwell-guide"])

    def test_empty_claims_and_wrong_publisher_are_dropped(self):
        chunks = [_chunk("who-healthy-diet", "who-healthy-diet:1:0", "Fat guidance.")]
        empty = validate(
            {"covered": True, "sections": [_section("who-healthy-diet", ["  "])]},
            chunks,
        )
        self.assertEqual(empty["stage"], NOT_IN_CORPUS)
        wrong = validate(
            {
                "covered": True,
                "sections": [_section("who-healthy-diet", ["Less than 30%."], publisher="Not WHO")],
            },
            chunks,
        )
        self.assertEqual(wrong["stage"], NOT_IN_CORPUS)

    def test_duplicate_document_keeps_the_first_matching_citation_only(self):
        chunks = [_chunk("cold-food-storage", "cold-food-storage:2:35", "Raw eggs in shell: 3 to 5 weeks.")]
        payload = {
            "covered": True,
            "sections": [
                _section("cold-food-storage", ["Raw eggs in shell: refrigerator 3 to 5 weeks."]),
                _section("cold-food-storage", ["Also includes ham, fish, and leftovers."]),
            ],
        }
        result = validate(payload, chunks)
        self.assertEqual(result["sections"][0]["claims"], ["Raw eggs in shell: refrigerator 3 to 5 weeks."])
        self.assertNotIn("ham", format_sections(result["sections"]))

        repaired = validate(
            {
                "covered": True,
                "sections": [
                    _section(
                        "cold-food-storage",
                        ["Raw eggs in shell: refrigerator 3 to 5 weeks."],
                        source_url="https://example.com/not-the-catalog",
                    ),
                    _section("cold-food-storage", ["Refrigerator time is 3 to 5 weeks."]),
                ],
            },
            chunks,
        )
        self.assertEqual(repaired["sections"][0]["claims"], ["Refrigerator time is 3 to 5 weeks."])

    def test_unreadable_model_payload_is_not_in_corpus(self):
        client = _RecordingClient("not-json-object")
        chunks = [_chunk("fsa-chill", "fsa-chill:1:0", "Chill food.")]
        result = respond("How should food be chilled?", chunks, client=client)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(result["stage"], NOT_IN_CORPUS)
        self.assertEqual(result["message"], not_in_corpus_message(None))


if __name__ == "__main__":
    unittest.main()
