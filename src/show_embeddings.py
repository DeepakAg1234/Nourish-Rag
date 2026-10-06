"""Print a few stored embeddings from the local Chroma index.

Reads the guidance collection under data/index. Does not re-embed
chunks or load the sentence-transformers model.
"""

from __future__ import annotations

import argparse
import sys

from src.index_corpus import COLLECTION_NAME, EMBEDDING_DIMENSIONS, INDEX_DIR, get_client

DEFAULT_LIMIT = 3
PREVIEW_VALUES = 8


def format_vector(values: list[float]) -> str:
    head = ", ".join(f"{value:.4f}" for value in values[:PREVIEW_VALUES])
    if len(values) > PREVIEW_VALUES:
        return f"[{head}, ...]  dim={len(values)}"
    return f"[{head}]  dim={len(values)}"


def show_embeddings(limit: int) -> int:
    if not INDEX_DIR.exists():
        print(f"error: index directory not found: {INDEX_DIR}", file=sys.stderr)
        return 1

    client = get_client()
    names = {collection.name for collection in client.list_collections()}
    if COLLECTION_NAME not in names:
        print(f"error: collection not found: {COLLECTION_NAME}", file=sys.stderr)
        return 1

    collection = client.get_collection(COLLECTION_NAME)
    total = collection.count()
    if total == 0:
        print(f"collection={COLLECTION_NAME}\tstored=0")
        return 0

    limit = min(limit, total)
    result = collection.get(
        limit=limit,
        include=["embeddings", "documents", "metadatas"],
    )
    documents = result.get("documents") or []
    metadatas = result.get("metadatas") or []
    embeddings = result.get("embeddings")
    if embeddings is None:
        embeddings = []

    print(
        f"collection={COLLECTION_NAME}\tstored={total}\t"
        f"showing={limit}\texpected_dim={EMBEDDING_DIMENSIONS}"
    )
    for chunk_id, document, metadata, embedding in zip(
        result["ids"],
        documents,
        metadatas,
        embeddings,
    ):
        text = (document or "").replace("\n", " ")
        if len(text) > 120:
            text = text[:117] + "..."
        document_id = (metadata or {}).get("document_id", "")
        heading = (metadata or {}).get("section_heading", "")
        print()
        print(f"chunk_id={chunk_id}")
        print(f"document_id={document_id}\tsection={heading}")
        print(f"text={text}")
        print(f"embedding={format_vector(list(embedding))}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Show a few embeddings stored in ChromaDB.")
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"how many chunks to print (default {DEFAULT_LIMIT})",
    )
    args = parser.parse_args()
    if args.limit < 1:
        print("error: --limit must be at least 1", file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(show_embeddings(args.limit))


if __name__ == "__main__":
    main()
