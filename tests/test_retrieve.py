"""Phase 3 checks for name detection, the per-document cap, and live search."""

import unittest

from src.index_corpus import build_index, get_client, load_chunk_rows
from src.retrieve import (
    SIMILARITY_FLOOR,
    cap_all_documents,
    matched_document_ids,
    resolve_document_filter,
    retrieve,
    similarity_from_distance,
)


def _hit(chunk_id: str, document_id: str, similarity: float = 0.9) -> dict:
    return {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "similarity": similarity,
    }


class RetrieveRuleTests(unittest.TestCase):
    def test_similarity_is_one_minus_cosine_distance(self):
        self.assertAlmostEqual(similarity_from_distance(0.25), 0.75)
        self.assertEqual(SIMILARITY_FLOOR, 0.0)

    def test_name_detection(self):
        self.assertEqual(
            resolve_document_filter("According to the Eatwell Guide, what does it say about oils?"),
            "eatwell-guide",
        )
        self.assertEqual(resolve_document_filter("Five Keys to safer food"), "who-five-keys")
        self.assertEqual(resolve_document_filter("What are healthy diets?"), "fao-who-healthy-diets")
        self.assertEqual(
            resolve_document_filter("the healthy diet fact sheet"),
            "who-healthy-diet",
        )
        self.assertIsNone(resolve_document_filter("What is a healthy diet?"))
        self.assertEqual(
            matched_document_ids("What is a healthy diet?"),
            {"who-healthy-diet", "fao-who-healthy-diets"},
        )
        self.assertIsNone(
            resolve_document_filter("What do the Eatwell Guide and the Kitchen Companion say about oil?")
        )
        self.assertIsNone(resolve_document_filter("What share of energy does WHO recommend from fat?"))
        self.assertEqual(
            resolve_document_filter("How long for eggs?", document_id="cold-food-storage"),
            "cold-food-storage",
        )

    def test_cap_keeps_a_second_document_past_a_kitchen_companion_run(self):
        ranked = [_hit(f"kitchen-companion:{index}:0", "kitchen-companion") for index in range(10)]
        ranked.append(_hit("cold-food-storage:2:35", "cold-food-storage", 0.5))
        kept = cap_all_documents(ranked)
        self.assertEqual(sum(1 for chunk in kept if chunk["document_id"] == "kitchen-companion"), 3)
        self.assertIn("cold-food-storage:2:35", [chunk["chunk_id"] for chunk in kept])
        self.assertLessEqual(len(kept), 8)

    def test_chunks_under_the_floor_are_dropped_before_the_cap(self):
        ranked = [
            _hit("kitchen-companion:1:0", "kitchen-companion", -0.1),
            _hit("cold-food-storage:2:35", "cold-food-storage", 0.4),
        ]
        kept = [chunk for chunk in ranked if chunk["similarity"] >= SIMILARITY_FLOOR]
        kept = cap_all_documents(kept)
        self.assertEqual([chunk["chunk_id"] for chunk in kept], ["cold-food-storage:2:35"])


class LiveIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.rows = load_chunk_rows()
        cls.count = build_index(cls.rows)

    def test_index_replaces_the_collection_with_every_chunk(self):
        self.assertEqual(self.count, 339)
        collection = get_client().get_collection("guidance")
        self.assertEqual(collection.count(), 339)
        self.assertEqual(collection.metadata.get("hnsw:space"), "cosine")
        both = collection.get(ids=["kitchen-companion:215:0", "kitchen-companion:217:0"])
        self.assertEqual(sorted(both["ids"]), ["kitchen-companion:215:0", "kitchen-companion:217:0"])
        eggs = collection.get(ids=["cold-food-storage:2:35", "kitchen-companion:285:0", "eatwell-guide:105:4"])
        self.assertEqual(len(eggs["ids"]), 3)
        by_id = dict(zip(eggs["ids"], eggs["documents"]))
        self.assertIn("3 to 5 weeks", by_id["cold-food-storage:2:35"])
        self.assertIn("3 to 5 weeks", by_id["kitchen-companion:285:0"])

    def test_refrigerator_eggs_keep_the_foodsafety_row(self):
        chunks = retrieve("How long can raw eggs stay in the refrigerator?")
        ids = [chunk["chunk_id"] for chunk in chunks]
        self.assertIn("cold-food-storage:2:35", ids)
        egg = next(chunk for chunk in chunks if chunk["chunk_id"] == "cold-food-storage:2:35")
        self.assertIn("3 to 5 weeks", egg["text"])
        self.assertIn("Refrigerator", egg["text"])
        self.assertIn("foodsafety.gov", egg["source_url"])
        self.assertGreaterEqual(egg["similarity"], SIMILARITY_FLOOR)
        self.assertLessEqual(len(chunks), 8)
        per_document = {}
        for chunk in chunks:
            per_document[chunk["document_id"]] = per_document.get(chunk["document_id"], 0) + 1
        self.assertTrue(all(count <= 3 for count in per_document.values()))

    def test_eatwell_filter_returns_only_that_document(self):
        chunks = retrieve("According to the Eatwell Guide, what does it say about oils?")
        self.assertTrue(chunks)
        self.assertLessEqual(len(chunks), 5)
        self.assertTrue(all(chunk["document_id"] == "eatwell-guide" for chunk in chunks))
        ids = {chunk["chunk_id"] for chunk in chunks}
        self.assertTrue(
            ids & {"eatwell-guide:105:4"}
            or any(chunk["section_heading"].endswith("A closer look at Oils and spreads") for chunk in chunks)
        )

    def test_two_named_documents_and_bare_who_are_unfiltered(self):
        both = retrieve("What do the Eatwell Guide and the Kitchen Companion say about fats?")
        self.assertTrue(both)
        who = retrieve("What share of energy intake does WHO recommend from fat?")
        self.assertTrue(who)
        self.assertIsNone(
            resolve_document_filter("What do the Eatwell Guide and the Kitchen Companion say about fats?")
        )
        self.assertIsNone(resolve_document_filter("What share of energy intake does WHO recommend from fat?"))


if __name__ == "__main__":
    unittest.main()
