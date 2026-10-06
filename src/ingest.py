"""Download the block file and join it to the citation catalog."""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data" / "catalog.json"
BLOCKS_PATH = ROOT / "data" / "blocks.jsonl"
BLOCKS_URL = "https://raw.githubusercontent.com/saksham20189575/health-data/main/blocks.jsonl"

EXPECTED_COUNTS = {
    "cold-food-storage": 3,
    "who-healthy-diet": 92,
    "fao-who-healthy-diets": 98,
    "who-five-keys": 174,
    "eatwell-guide": 120,
    "fsa-chill": 45,
    "kitchen-companion": 469,
}

# Running headers that repeat the FAO/WHO title and a page number, with no guidance after them.
_PAGE_FURNITURE = re.compile(
    r"^\d+\s+What are healthy diets\? Joint statement by the Food and Agriculture "
    r"Organization of the United Nations and the World Health Organization$"
)


class IngestError(Exception):
    """The block file does not match the catalog."""


def load_catalog(path: Path = CATALOG_PATH) -> list[dict]:
    catalog = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(catalog, list) or not catalog:
        raise IngestError(f"catalog is empty: {path}")
    return catalog


def download_blocks(url: str = BLOCKS_URL) -> str:
    response = httpx.get(url, follow_redirects=True, timeout=60.0)
    response.raise_for_status()
    return response.text


def parse_blocks(raw: str) -> list[dict]:
    blocks = []
    for line_number, line in enumerate(raw.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            block = json.loads(line)
        except json.JSONDecodeError as exc:
            raise IngestError(f"invalid JSON on line {line_number}") from exc
        if "document_id" not in block or "ordinal" not in block:
            raise IngestError(f"line {line_number} is missing document_id or ordinal")
        blocks.append(block)
    return blocks


def validate_ids(blocks: list[dict], catalog: list[dict]) -> None:
    catalog_ids = {row["document_id"] for row in catalog}
    block_ids = {block["document_id"] for block in blocks}
    unknown = sorted(block_ids - catalog_ids)
    missing = sorted(catalog_ids - block_ids)
    if unknown:
        raise IngestError("unknown document_id: " + ", ".join(unknown))
    if missing:
        raise IngestError("catalog document_id missing from blocks: " + ", ".join(missing))


def is_page_furniture(block: dict) -> bool:
    if block.get("type") != "paragraph":
        return False
    text = (block.get("text") or "").strip()
    return _PAGE_FURNITURE.fullmatch(text) is not None


def drop_page_furniture(blocks: list[dict]) -> tuple[list[dict], int]:
    kept = [block for block in blocks if not is_page_furniture(block)]
    return kept, len(blocks) - len(kept)


def sort_blocks(blocks: list[dict]) -> list[dict]:
    return sorted(blocks, key=lambda block: (block["document_id"], block["ordinal"]))


def count_by_document(blocks: list[dict]) -> Counter:
    return Counter(block["document_id"] for block in blocks)


def count_warnings(raw_counts: Counter) -> list[str]:
    warnings = []
    for document_id, expected in EXPECTED_COUNTS.items():
        actual = raw_counts.get(document_id, 0)
        if actual != expected:
            warnings.append(
                f"warning: {document_id} raw block count is {actual}, expected about {expected}"
            )
    return warnings


def write_blocks(blocks: list[dict], path: Path = BLOCKS_PATH) -> None:
    lines = [json.dumps(block, ensure_ascii=False) for block in blocks]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ingest(raw: str, catalog: list[dict]) -> tuple[list[dict], Counter, int, list[str]]:
    blocks = parse_blocks(raw)
    validate_ids(blocks, catalog)
    raw_counts = count_by_document(blocks)
    warnings = count_warnings(raw_counts)
    kept, dropped = drop_page_furniture(blocks)
    return sort_blocks(kept), raw_counts, dropped, warnings


def print_summary(
    catalog: list[dict],
    kept: list[dict],
    raw_counts: Counter,
    dropped: int,
    warnings: list[str],
) -> None:
    retrieval_dates = sorted({row["retrieval_date"] for row in catalog})
    print("retrieval_date: " + ", ".join(retrieval_dates))
    kept_counts = count_by_document(kept)
    for row in catalog:
        document_id = row["document_id"]
        print(
            f"{document_id}\tblocks={kept_counts[document_id]}"
            f"\traw={raw_counts[document_id]}"
        )
    if dropped:
        print(f"dropped {dropped} page-furniture lines")
    for warning in warnings:
        print(warning)


def main() -> None:
    try:
        catalog = load_catalog()
        raw = download_blocks()
        kept, raw_counts, dropped, warnings = ingest(raw, catalog)
    except IngestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    except httpx.HTTPError as exc:
        print(f"error: download failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    write_blocks(kept)
    print_summary(catalog, kept, raw_counts, dropped, warnings)


if __name__ == "__main__":
    main()
