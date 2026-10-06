"""Phase 1 checks for catalog join rules. These do not download the block file."""

import unittest

from src.ingest import IngestError, ingest


CATALOG = [
    {
        "document_id": "cold-food-storage",
        "document_name": "Cold Food Storage Chart",
        "retrieval_date": "2026-10-05",
    },
    {
        "document_id": "fao-who-healthy-diets",
        "document_name": "What are healthy diets? Joint statement",
        "retrieval_date": "2026-10-05",
    },
]


def _line(document_id: str, ordinal: int, text: str, type_: str = "paragraph") -> str:
    import json

    return json.dumps(
        {
            "document_id": document_id,
            "ordinal": ordinal,
            "type": type_,
            "text": text,
            "heading_path": ["Section"],
        }
    )


class IngestTests(unittest.TestCase):
    def test_unknown_document_id_is_an_error(self):
        raw = _line("not-a-document", 0, "Some guidance.")
        with self.assertRaises(IngestError) as caught:
            ingest(raw, CATALOG)
        self.assertIn("unknown document_id: not-a-document", str(caught.exception))

    def test_missing_catalog_document_is_an_error(self):
        raw = _line("cold-food-storage", 0, "Eggs keep for 3 to 5 weeks.")
        with self.assertRaises(IngestError) as caught:
            ingest(raw, CATALOG)
        self.assertIn("fao-who-healthy-diets", str(caught.exception))

    def test_page_furniture_is_dropped_and_blocks_are_sorted(self):
        furniture = (
            "2 What are healthy diets? Joint statement by the Food and Agriculture "
            "Organization of the United Nations and the World Health Organization"
        )
        guidance_with_header = furniture + " dietary fibre as consumed in foods."
        raw = "\n".join(
            [
                _line("fao-who-healthy-diets", 2, "Adequate diets meet nutrient needs."),
                _line("cold-food-storage", 1, "Eggs keep for 3 to 5 weeks."),
                _line("fao-who-healthy-diets", 1, furniture),
                _line("fao-who-healthy-diets", 3, guidance_with_header),
                _line("cold-food-storage", 0, "Cold Food Storage Chart", "heading"),
            ]
        )
        kept, raw_counts, dropped, _warnings = ingest(raw, CATALOG)
        self.assertEqual(dropped, 1)
        self.assertEqual(raw_counts["fao-who-healthy-diets"], 3)
        self.assertEqual([block["ordinal"] for block in kept if block["document_id"] == "cold-food-storage"], [0, 1])
        self.assertEqual(
            [block["text"] for block in kept if block["document_id"] == "fao-who-healthy-diets"],
            ["Adequate diets meet nutrient needs.", guidance_with_header],
        )


if __name__ == "__main__":
    unittest.main()
