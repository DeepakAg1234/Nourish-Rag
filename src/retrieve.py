"""All-document and single-document search over the local chunk index.

This module embeds the question with the same local model the index used.
It does not call the chat model.
"""

from __future__ import annotations

import sys
from collections import Counter

from src.index_corpus import COLLECTION_NAME, embed_texts, get_client

# Phase 7 tunes this against the acceptance questions.
# 0.0 keeps every non-negative cosine similarity from the candidate pool.
SIMILARITY_FLOOR = 0.0

CANDIDATE_POOL = 32
MAX_CHUNKS = 8
MAX_PER_DOCUMENT = 3
SINGLE_DOCUMENT_K = 5

# Longer phrases are listed first. Matching is case-insensitive.
_PHRASES: tuple[tuple[str, str], ...] = (
    ("what are healthy diets", "fao-who-healthy-diets"),
    ("joint statement", "fao-who-healthy-diets"),
    ("food standards agency", "fsa-chill"),
    ("foodsafety.gov", "cold-food-storage"),
    ("cold food storage", "cold-food-storage"),
    ("kitchen companion", "kitchen-companion"),
    ("five keys", "who-five-keys"),
    ("eatwell", "eatwell-guide"),
    ("fact sheet", "who-healthy-diet"),
)

_NUTRITION_PAIR = frozenset({"who-healthy-diet", "fao-who-healthy-diets"})


class RetrieveError(Exception):
    """The index could not answer a search."""


def similarity_from_distance(distance: float) -> float:
    """Chroma cosine distance is 1 minus cosine similarity."""
    return 1.0 - distance


def matched_document_ids(question: str) -> set[str]:
    """Catalog ids named by the question.

    A bare WHO matches none of them. "healthy diet" on its own matches both
    the WHO fact sheet and the FAO/WHO joint statement.
    """
    folded = question.casefold()
    found: set[str] = set()
    for phrase, document_id in _PHRASES:
        if phrase in folded:
            found.add(document_id)
    mentions_healthy_diet = "healthy diet" in folded or "healthy diets" in folded
    if mentions_healthy_diet and not (found & _NUTRITION_PAIR):
        found |= set(_NUTRITION_PAIR)
    return found


def resolve_document_filter(question: str, document_id: str | None = None) -> str | None:
    """One document id, or None when search stays across the whole index."""
    if document_id:
        return document_id
    found = matched_document_ids(question)
    if len(found) == 1:
        return next(iter(found))
    return None


def cap_all_documents(ranked: list[dict]) -> list[dict]:
    """Keep at most 3 chunks per document and at most 8 chunks overall."""
    kept: list[dict] = []
    per_document: Counter[str] = Counter()
    for chunk in ranked:
        if len(kept) >= MAX_CHUNKS:
            break
        document_id = chunk["document_id"]
        if per_document[document_id] >= MAX_PER_DOCUMENT:
            continue
        kept.append(chunk)
        per_document[document_id] += 1
    return kept


def retrieve(question: str, document_id: str | None = None) -> list[dict]:
    """Return kept chunks in rank order, each with a cosine similarity."""
    if not question or not question.strip():
        raise RetrieveError("question is empty")
    document_filter = resolve_document_filter(question, document_id)
    client = get_client()
    try:
        collection = client.get_collection(COLLECTION_NAME)
    except Exception as exc:
        raise RetrieveError("index is missing; run python -m src.index_corpus") from exc

    limit = SINGLE_DOCUMENT_K if document_filter else CANDIDATE_POOL
    where = {"document_id": document_filter} if document_filter else None
    available = _available(collection, where)
    if available == 0:
        return []
    result = collection.query(
        query_embeddings=embed_texts([question.strip()]),
        n_results=min(limit, available),
        where=where,
        include=["documents", "metadatas", "distances"],
    )
    ranked = [
        chunk
        for chunk in _hits(result)
        if chunk["similarity"] >= SIMILARITY_FLOOR
    ]
    if document_filter:
        return ranked[:SINGLE_DOCUMENT_K]
    return cap_all_documents(ranked)


def _available(collection, where: dict | None) -> int:
    found = collection.get(where=where, include=[])
    return len(found["ids"])


def _hits(result: dict) -> list[dict]:
    ids = result.get("ids") or [[]]
    documents = result.get("documents") or [[]]
    metadatas = result.get("metadatas") or [[]]
    distances = result.get("distances") or [[]]
    hits = []
    for chunk_id, text, metadata, distance in zip(ids[0], documents[0], metadatas[0], distances[0]):
        ordinals = [int(part) for part in str(metadata["ordinals"]).split(",") if part]
        hits.append(
            {
                "chunk_id": chunk_id,
                "document_id": metadata["document_id"],
                "document_name": metadata["document_name"],
                "publisher": metadata["publisher"],
                "year": int(metadata["year"]),
                "source_url": metadata["source_url"],
                "retrieval_date": metadata["retrieval_date"],
                "section_heading": metadata["section_heading"],
                "source": metadata["source"],
                "ordinals": ordinals,
                "text": text,
                "similarity": similarity_from_distance(distance),
            }
        )
    return hits


def main() -> None:
    question = " ".join(sys.argv[1:]).strip()
    if not question:
        print("usage: python -m src.retrieve \"question\"", file=sys.stderr)
        raise SystemExit(2)
    try:
        document_filter = resolve_document_filter(question)
        chunks = retrieve(question)
    except RetrieveError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print(f"filter={document_filter or 'all'}\tkept={len(chunks)}")
    for chunk in chunks:
        print(f"{chunk['similarity']:.3f}\t{chunk['chunk_id']}\t{chunk['section_heading']}")


if __name__ == "__main__":
    main()
