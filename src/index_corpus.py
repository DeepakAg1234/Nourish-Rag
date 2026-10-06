"""Embed data/chunks.jsonl and rebuild the local vector index.

The embedding is all-MiniLM-L6-v2. Vectors use the embed_text field.
The stored document is the full chunk text, including the tail the
embedding model truncates after 256 tokens.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

from src.chunk import CHUNKS_PATH

ROOT = Path(__file__).resolve().parents[1]
INDEX_DIR = ROOT / "data" / "index"
COLLECTION_NAME = "guidance"
MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSIONS = 384

METADATA_FIELDS = (
    "document_id",
    "document_name",
    "publisher",
    "year",
    "source_url",
    "retrieval_date",
    "section_heading",
    "source",
)

_model: SentenceTransformer | None = None


class IndexBuildError(Exception):
    """The chunk file could not be indexed."""


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def get_client() -> chromadb.PersistentClient:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(
        path=str(INDEX_DIR),
        settings=Settings(anonymized_telemetry=False),
    )


def load_chunk_rows(path: Path = CHUNKS_PATH) -> list[dict]:
    if not path.exists():
        raise IndexBuildError(f"chunk file not found: {path}")
    rows = []
    seen: set[str] = set()
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise IndexBuildError(f"invalid JSON on line {line_number}") from exc
        chunk_id = row.get("chunk_id")
        embed_text = row.get("embed_text")
        text = row.get("text")
        if not chunk_id or not str(embed_text).strip() or not str(text).strip():
            raise IndexBuildError(f"line {line_number} is missing chunk_id, embed_text, or text")
        if chunk_id in seen:
            raise IndexBuildError(f"duplicate chunk_id: {chunk_id}")
        seen.add(chunk_id)
        rows.append(row)
    if not rows:
        raise IndexBuildError(f"chunk file is empty: {path}")
    return rows


def embed_texts(texts: list[str]) -> list[list[float]]:
    vectors = get_model().encode(texts, normalize_embeddings=True, show_progress_bar=False)
    if len(vectors) != len(texts):
        raise IndexBuildError("embedding count does not match the chunk count")
    if len(vectors[0]) != EMBEDDING_DIMENSIONS:
        raise IndexBuildError(f"expected {EMBEDDING_DIMENSIONS} dimensions, got {len(vectors[0])}")
    return vectors.tolist()


def metadata_for(row: dict) -> dict:
    metadata = {}
    for field in METADATA_FIELDS:
        value = row.get(field)
        if value is None or value == "":
            raise IndexBuildError(f"{row['chunk_id']} is missing {field}")
        metadata[field] = int(value) if field == "year" else str(value)
    ordinals = row.get("ordinals")
    if not isinstance(ordinals, list) or not ordinals:
        raise IndexBuildError(f"{row['chunk_id']} is missing ordinals")
    metadata["ordinals"] = ",".join(str(int(ordinal)) for ordinal in ordinals)
    return metadata


def build_index(rows: list[dict] | None = None, client: chromadb.PersistentClient | None = None) -> int:
    rows = load_chunk_rows() if rows is None else rows
    client = client or get_client()
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        # A missing collection is the first build, not a failed rebuild.
        pass
    collection = client.create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )
    collection.add(
        ids=[row["chunk_id"] for row in rows],
        embeddings=embed_texts([row["embed_text"] for row in rows]),
        documents=[row["text"] for row in rows],
        metadatas=[metadata_for(row) for row in rows],
    )
    return collection.count()


def print_summary(rows: list[dict], count: int) -> None:
    counts = Counter(row["document_id"] for row in rows)
    print(f"model={MODEL_NAME}\tdimensions={EMBEDDING_DIMENSIONS}\tspace=cosine")
    for document_id in sorted(counts):
        print(f"{document_id}\tchunks={counts[document_id]}")
    print(f"indexed={count}")


def main() -> None:
    try:
        rows = load_chunk_rows()
        count = build_index(rows)
    except IndexBuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print_summary(rows, count)


if __name__ == "__main__":
    main()
