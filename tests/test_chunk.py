"""Phase 2 checks for heading groups, table rows, and the FAO Table 1 lines."""

import json
import unittest
from collections import defaultdict

from src.chunk import FAO_TABLE1_ORDINALS, TOKEN_LIMIT, build_chunks, estimate_tokens
from src.ingest import BLOCKS_PATH, load_catalog


def _catalog_row(document_id: str = "cold-food-storage") -> dict:
    return {
        "document_id": document_id,
        "document_name": "Cold Food Storage Chart",
        "publisher": "FoodSafety.gov",
        "year": 2023,
        "source_url": "https://www.foodsafety.gov/food-safety-charts/cold-food-storage-charts",
        "retrieval_date": "2026-10-05",
        "kind": "food_safety",
    }


def _block(ordinal: int, type_: str, text: str, heading_path: list[str], **extra) -> dict:
    block = {
        "document_id": extra.pop("document_id", "cold-food-storage"),
        "ordinal": ordinal,
        "type": type_,
        "text": text,
        "heading_path": heading_path,
    }
    block.update(extra)
    return block


class ChunkRuleTests(unittest.TestCase):
    def test_heading_is_not_a_chunk_and_sections_do_not_merge(self):
        blocks = [
            _block(0, "heading", "Eggs", ["Eggs"]),
            _block(1, "paragraph", "Keep eggs in the refrigerator.", ["Eggs"]),
            _block(2, "heading", "Leftovers", ["Leftovers"]),
            _block(3, "paragraph", "Store leftovers in a shallow container.", ["Leftovers"]),
        ]
        chunks = build_chunks(blocks, [_catalog_row()])
        self.assertEqual([chunk["ordinals"] for chunk in chunks], [[1], [3]])
        self.assertEqual(chunks[0]["section_heading"], "Eggs")
        self.assertNotIn("Leftovers", chunks[0]["text"])
        self.assertNotIn("refrigerator", chunks[1]["text"])

    def test_long_block_is_not_cut_into_a_character_window(self):
        paragraph = "storage " * 400
        blocks = [
            _block(0, "heading", "Eggs", ["Eggs"]),
            _block(1, "paragraph", paragraph, ["Eggs"]),
        ]
        chunks = build_chunks(blocks, [_catalog_row()], token_limit=10)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["text"], paragraph.strip())
        self.assertGreater(estimate_tokens(chunks[0]["text"]), 10)

    def test_mid_list_flush_repeats_the_introducing_paragraph(self):
        intro = "Cut saturated fat by choosing these foods."
        blocks = [_block(0, "heading", "Fats", ["Fats"]), _block(1, "paragraph", intro, ["Fats"])]
        for ordinal in range(2, 8):
            blocks.append(_block(ordinal, "list_item", f"food {ordinal} " * 30, ["Fats"]))
        chunks = build_chunks(blocks, [_catalog_row()], token_limit=80)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertIn(intro, chunk["text"])
            self.assertNotEqual(chunk["text"], chunk["text"].split("\n")[-1])
        self.assertEqual(chunks[0]["ordinals"][0], 1)
        self.assertNotIn(1, chunks[1]["ordinals"])

    def test_empty_table_cell_is_not_filled_from_the_row_above(self):
        blocks = [
            _block(0, "heading", "Roasts", ["Roasts"]),
            _block(
                1,
                "table",
                "| Meat | Time |\n| --- | --- |",
                ["Roasts"],
                header=["Meat", "Time"],
                rows=[
                    ["Whole turkey", "3 to 3 1/2 hours"],
                    ["Country ham", ""],
                ],
            ),
        ]
        chunks = build_chunks(blocks, [_catalog_row()])
        self.assertEqual([chunk["chunk_id"] for chunk in chunks], ["cold-food-storage:1:0", "cold-food-storage:1:1"])
        self.assertIn("Time: 3 to 3 1/2 hours", chunks[0]["text"])
        self.assertIn("Meat: Country ham", chunks[1]["text"])
        self.assertIn("Time:", chunks[1]["text"])
        self.assertNotIn("3 to 3 1/2 hours", chunks[1]["text"])

    def test_caption_is_copied_onto_every_row_and_ids_use_the_table_ordinal(self):
        heading = ["Special Guidelines for Certain Food", "Roasts", "Watch Temperatures Closely"]
        blocks = [
            _block(1, "heading", "Watch Temperatures Closely", heading),
            _block(
                10,
                "table",
                "whole chart",
                heading,
                caption="Roasting Chart",
                header=["Meat", "Oven"],
                rows=[["Beef", "325 °F"], ["Lamb", "325 °F"]],
            ),
            _block(
                12,
                "table",
                "whole chart again",
                heading,
                header=["Meat", "Oven"],
                rows=[["Chicken", "350 °F"]],
            ),
        ]
        chunks = build_chunks(blocks, [_catalog_row()])
        self.assertEqual(
            [chunk["chunk_id"] for chunk in chunks],
            ["cold-food-storage:10:0", "cold-food-storage:10:1", "cold-food-storage:12:0"],
        )
        self.assertTrue(all(chunk["text"].startswith("Roasting Chart") for chunk in chunks[:2]))
        self.assertNotIn("Roasting Chart", chunks[2]["text"])
        self.assertNotIn("Beef", chunks[2]["text"])
        self.assertNotIn("whole chart", chunks[0]["text"])


class CorpusChunkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load_catalog()
        cls.blocks = [
            json.loads(line)
            for line in BLOCKS_PATH.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        cls.chunks = build_chunks(cls.blocks, cls.catalog)
        cls.by_id = {chunk["chunk_id"]: chunk for chunk in cls.chunks}

    def test_raw_egg_refrigerator_row_is_its_own_chunk(self):
        chunk = self.by_id["cold-food-storage:2:35"]
        self.assertEqual(chunk["source"], "table_row")
        self.assertIn("Raw eggs in shell", chunk["text"])
        self.assertIn("3 to 5 weeks", chunk["text"])
        self.assertIn("Refrigerator [40°F (4°C) or below]", chunk["text"])
        lowered = chunk["text"].lower()
        self.assertNotIn("ham", lowered)
        self.assertNotIn("fish", lowered)
        self.assertNotIn("leftover", lowered)
        self.assertNotIn("| --- |", chunk["text"])

    def test_fao_saturated_fat_line_stays_with_the_table_heading(self):
        chunk = self.by_id["fao-who-healthy-diets:23:0"]
        self.assertEqual(chunk["source"], "fao_table1")
        self.assertEqual(chunk["ordinals"], [23])
        self.assertIn("Saturated 10% or less", chunk["text"])
        self.assertIn("proportion of dietary energy intake", chunk["text"])
        self.assertIn("Adults", chunk["text"])
        self.assertIn("Table 1", chunk["section_heading"])
        self.assertNotIn("Proteins provide the building blocks", chunk["text"])
        essay = next(
            item
            for item in self.chunks
            if item["document_id"] == "fao-who-healthy-diets" and 40 in item["ordinals"]
        )
        self.assertNotIn(23, essay["ordinals"])
        self.assertEqual(
            sorted(item["chunk_id"] for item in self.chunks if item["source"] == "fao_table1"),
            [f"fao-who-healthy-diets:{ordinal}:0" for ordinal in sorted(FAO_TABLE1_ORDINALS)],
        )

    def test_oils_table_row_and_oils_prose_are_different_chunks(self):
        prose = [
            chunk
            for chunk in self.chunks
            if chunk["section_heading"].endswith("A closer look at Oils and spreads")
        ]
        table_row = self.by_id["eatwell-guide:105:4"]
        self.assertEqual(len(prose), 1)
        self.assertEqual(prose[0]["source"], "prose")
        self.assertIn("Oils and spreads", table_row["text"])
        self.assertIn("Food group:", table_row["text"])
        self.assertNotEqual(prose[0]["chunk_id"], table_row["chunk_id"])
        self.assertNotIn("Although some fat in the diet is essential", table_row["text"])
        self.assertNotIn("Fruit and vegetables", prose[0]["text"])

    def test_turkey_roasting_row_keeps_the_caption_temperatures(self):
        chunk = self.by_id["kitchen-companion:252:0"]
        self.assertIn("4 to 6 pounds (breast)", chunk["text"])
        self.assertIn("325 °F", chunk["text"])
        self.assertIn("165 °F", chunk["text"])
        self.assertTrue(all("325 °F" in item["text"] and "165 °F" in item["text"] for item in self._rows(252)))

    def test_country_ham_keeps_its_empty_cells(self):
        chunk = self.by_id["kitchen-companion:216:10"]
        self.assertIn("Country", chunk["text"])
        self.assertIn("Timing (Approximate):", chunk["text"])
        self.assertNotIn("10 to 18 minutes per lb.", chunk["text"])
        joined = "\n".join(item["text"] for item in self._rows(216))
        self.assertNotIn("Beef", joined)

    def test_every_chunk_has_citation_fields_and_a_section(self):
        catalog = {row["document_id"]: row for row in self.catalog}
        self.assertEqual(len(self.by_id), len(self.chunks))
        for chunk in self.chunks:
            row = catalog[chunk["document_id"]]
            self.assertTrue(chunk["section_heading"].strip())
            self.assertEqual(chunk["publisher"], row["publisher"])
            self.assertEqual(chunk["year"], row["year"])
            self.assertEqual(chunk["source_url"], row["source_url"])
            self.assertEqual(chunk["document_name"], row["document_name"])
            self.assertEqual(chunk["embed_text"], f"{chunk['section_heading']}\n{chunk['text']}")

    def test_table_rows_and_fao_lines_match_the_snapshot(self):
        self.assertEqual(sum(1 for chunk in self.chunks if chunk["source"] == "table_row"), 146)
        self.assertEqual(sum(1 for chunk in self.chunks if chunk["source"] == "fao_table1"), 7)
        captions = {
            92: "Cold Storage Chart",
            214: "Roasting Chart",
            232: "Turkey Thawing Chart",
            252: "325 °F",
            254: "165 °F",
            285: "Egg Storage Chart",
        }
        for ordinal, needle in captions.items():
            rows = self._rows(ordinal)
            self.assertGreater(len(rows), 1)
            self.assertTrue(all(needle in chunk["text"] for chunk in rows))

    def test_short_list_items_keep_the_paragraph_that_introduces_them(self):
        fats = [
            chunk
            for chunk in self.chunks
            if chunk["document_id"] == "who-healthy-diet" and chunk["section_heading"].endswith("Fats")
        ]
        self.assertEqual(len(fats), 1)
        self.assertIn("less than 30% of total energy", fats[0]["text"])
        self.assertIn("reducing saturated fats to less than 10% of total energy intake", fats[0]["text"])
        self.assertLess(estimate_tokens(fats[0]["text"]), TOKEN_LIMIT)

        owned = defaultdict(list)
        for chunk in self.chunks:
            for ordinal in chunk["ordinals"]:
                owned[(chunk["document_id"], ordinal)].append(chunk)

        grouped = defaultdict(list)
        for block in self.blocks:
            grouped[block["document_id"]].append(block)

        for document_id, doc_blocks in grouped.items():
            last_paragraph = None
            current_path = None
            for block in sorted(doc_blocks, key=lambda item: item["ordinal"]):
                path = tuple(block.get("heading_path") or [])
                if block["type"] == "heading" or path != current_path:
                    last_paragraph = None
                    current_path = path
                if block["type"] == "heading" or block["type"] == "table":
                    continue
                text = (block.get("text") or "").strip()
                if not text:
                    continue
                owners = owned[(document_id, block["ordinal"])]
                self.assertEqual(len(owners), 1, f"{document_id}:{block['ordinal']} ownership")
                self.assertIn(text, owners[0]["text"])
                if document_id == "fao-who-healthy-diets" and block["ordinal"] in FAO_TABLE1_ORDINALS:
                    continue
                if block["type"] == "paragraph":
                    last_paragraph = text
                elif block["type"] == "list_item" and last_paragraph:
                    self.assertIn(last_paragraph, owners[0]["text"])

    def _rows(self, ordinal: int) -> list[dict]:
        return [
            chunk
            for chunk in self.chunks
            if chunk["document_id"] == "kitchen-companion"
            and chunk["ordinals"] == [ordinal]
            and chunk["source"] == "table_row"
        ]


if __name__ == "__main__":
    unittest.main()
