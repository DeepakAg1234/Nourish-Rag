"""Turn catalogued blocks into retrieval chunks.

Prose under one heading stays together until it would pass TOKEN_LIMIT
(about 500 tokens, estimated at four characters per token). Tables with
rows become one chunk per row. FAO Table 1 is stored as headings and
paragraphs, so those seven lines are chunked one-by-one instead.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from src.ingest import BLOCKS_PATH, CATALOG_PATH, load_catalog

ROOT = Path(__file__).resolve().parents[1]
CHUNKS_PATH = ROOT / "data" / "chunks.jsonl"

# About 500 tokens. English in this corpus is roughly four characters per token,
# so the cap sits near 2,000 characters and only the long heading groups split.
TOKEN_LIMIT = 500

FAO_DOCUMENT_ID = "fao-who-healthy-diets"
FAO_TABLE1_HEADING_ORDINAL = 22
FAO_TABLE1_ORDINALS = frozenset(range(23, 30))


class ChunkError(Exception):
    """Blocks could not be turned into chunks."""


def estimate_tokens(text: str) -> int:
    """Approximate a token count without loading the embedding tokenizer."""
    if not text:
        return 0
    return (len(text) + 3) // 4


def load_blocks(path: Path = BLOCKS_PATH) -> list[dict]:
    if not path.exists():
        raise ChunkError(f"block file not found: {path}")
    blocks = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            block = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ChunkError(f"invalid JSON on line {line_number}") from exc
        blocks.append(block)
    return blocks


def build_chunks(
    blocks: list[dict],
    catalog: list[dict],
    token_limit: int = TOKEN_LIMIT,
) -> list[dict]:
    catalog_by_id = {row["document_id"]: row for row in catalog}
    grouped: dict[str, list[dict]] = defaultdict(list)
    for block in blocks:
        document_id = block.get("document_id")
        if document_id not in catalog_by_id:
            raise ChunkError(f"unknown document_id: {document_id}")
        grouped[document_id].append(block)

    chunks: list[dict] = []
    for row in catalog:
        document_blocks = sorted(grouped.get(row["document_id"], []), key=lambda block: block["ordinal"])
        chunks.extend(_chunk_document(document_blocks, row, token_limit))

    ids = [chunk["chunk_id"] for chunk in chunks]
    if len(ids) != len(set(ids)):
        raise ChunkError("duplicate chunk_id")
    return chunks


def write_chunks(chunks: list[dict], path: Path = CHUNKS_PATH) -> None:
    lines = [json.dumps(chunk, ensure_ascii=False) for chunk in chunks]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def print_summary(chunks: list[dict], catalog: list[dict]) -> None:
    counts = Counter(chunk["document_id"] for chunk in chunks)
    for row in catalog:
        document_id = row["document_id"]
        doc_chunks = [chunk for chunk in chunks if chunk["document_id"] == document_id]
        table_rows = sum(1 for chunk in doc_chunks if chunk["source"] == "table_row")
        fao_lines = sum(1 for chunk in doc_chunks if chunk["source"] == "fao_table1")
        print(
            f"{document_id}\tchunks={counts[document_id]}"
            f"\ttable_rows={table_rows}\tfao_table1={fao_lines}"
        )
    table_rows = sum(1 for chunk in chunks if chunk["source"] == "table_row")
    fao_lines = sum(1 for chunk in chunks if chunk["source"] == "fao_table1")
    print(f"total={len(chunks)}\ttable_rows={table_rows}\tfao_table1={fao_lines}")


def _chunk_document(blocks: list[dict], catalog_row: dict, token_limit: int) -> list[dict]:
    chunks: list[dict] = []
    buffer: list[dict] = []
    prefix: str | None = None
    lead_in: str | None = None
    current_heading: str | None = None
    fao_table1_heading: str | None = None
    document_id = catalog_row["document_id"]

    def flush() -> None:
        nonlocal buffer, prefix
        if not buffer:
            prefix = None
            return
        if not current_heading:
            raise ChunkError(f"{document_id}: prose block with an empty section heading")
        text = _join(buffer, prefix)
        chunks.append(
            _make_chunk(
                catalog_row,
                section_heading=current_heading,
                first_ordinal=buffer[0]["ordinal"],
                row_index=0,
                ordinals=[block["ordinal"] for block in buffer],
                text=text,
                source="prose",
            )
        )
        buffer = []
        prefix = None

    for block in blocks:
        block_type = block.get("type")
        heading = _section_heading(block)

        if block_type == "heading":
            flush()
            lead_in = None
            current_heading = heading
            if (
                document_id == FAO_DOCUMENT_ID
                and block.get("ordinal") == FAO_TABLE1_HEADING_ORDINAL
            ):
                fao_table1_heading = (block.get("text") or "").strip()
            continue

        if block_type == "table" and block.get("rows") is not None:
            flush()
            if heading != current_heading:
                lead_in = None
            current_heading = heading
            chunks.extend(_table_chunks(block, catalog_row, heading))
            continue

        if block_type not in ("paragraph", "list_item"):
            continue

        text = (block.get("text") or "").strip()
        if not text:
            continue

        if document_id == FAO_DOCUMENT_ID and block.get("ordinal") in FAO_TABLE1_ORDINALS:
            flush()
            lead_in = None
            if not fao_table1_heading:
                raise ChunkError("FAO Table 1 heading was not seen before its nutrient lines")
            if not heading:
                raise ChunkError("FAO Table 1 line has an empty section heading")
            chunks.append(
                _make_chunk(
                    catalog_row,
                    section_heading=heading,
                    first_ordinal=block["ordinal"],
                    row_index=0,
                    ordinals=[block["ordinal"]],
                    text=f"{fao_table1_heading}\n{text}",
                    source="fao_table1",
                )
            )
            current_heading = heading
            continue

        if heading != current_heading:
            flush()
            lead_in = None
            current_heading = heading

        if buffer and estimate_tokens(_join(buffer + [block], prefix)) > token_limit:
            repeat_lead_in = block_type == "list_item" and bool(lead_in)
            saved_lead_in = lead_in
            flush()
            if repeat_lead_in:
                prefix = saved_lead_in
            buffer = [block]
        else:
            buffer.append(block)

        if block_type == "paragraph":
            lead_in = text

    flush()
    return chunks


def _table_chunks(block: dict, catalog_row: dict, heading: str) -> list[dict]:
    if not heading:
        raise ChunkError(
            f"{catalog_row['document_id']}: table ordinal {block.get('ordinal')} has an empty section heading"
        )
    headers = block.get("header") or []
    caption = block.get("caption")
    chunks = []
    for row_index, cells in enumerate(block.get("rows") or []):
        chunks.append(
            _make_chunk(
                catalog_row,
                section_heading=heading,
                first_ordinal=block["ordinal"],
                row_index=row_index,
                ordinals=[block["ordinal"]],
                text=_row_text(caption, headers, cells),
                source="table_row",
            )
        )
    return chunks


def _make_chunk(
    catalog_row: dict,
    section_heading: str,
    first_ordinal: int,
    row_index: int,
    ordinals: list[int],
    text: str,
    source: str,
) -> dict:
    if not section_heading.strip():
        raise ChunkError(f"{catalog_row['document_id']}: empty section heading")
    if not text.strip():
        raise ChunkError(f"{catalog_row['document_id']}: empty chunk text at ordinal {first_ordinal}")
    for field in ("document_name", "publisher", "source_url", "retrieval_date"):
        if not catalog_row.get(field):
            raise ChunkError(f"{catalog_row['document_id']}: catalog is missing {field}")
    if catalog_row.get("year") in (None, ""):
        raise ChunkError(f"{catalog_row['document_id']}: catalog is missing year")
    chunk_text = text.strip()
    return {
        "chunk_id": f"{catalog_row['document_id']}:{first_ordinal}:{row_index}",
        "document_id": catalog_row["document_id"],
        "document_name": catalog_row["document_name"],
        "publisher": catalog_row["publisher"],
        "year": catalog_row["year"],
        "source_url": catalog_row["source_url"],
        "retrieval_date": catalog_row["retrieval_date"],
        "section_heading": section_heading,
        "ordinals": ordinals,
        "text": chunk_text,
        "embed_text": f"{section_heading}\n{chunk_text}",
        "source": source,
    }


def _section_heading(block: dict) -> str:
    return " > ".join(part.strip() for part in (block.get("heading_path") or []) if str(part).strip())


def _join(blocks: list[dict], prefix: str | None) -> str:
    parts: list[str] = []
    if prefix and prefix.strip():
        parts.append(prefix.strip())
    for block in blocks:
        text = (block.get("text") or "").strip()
        if text:
            parts.append(text)
    return "\n".join(parts)


def _row_text(caption: str | None, headers: list, cells: list) -> str:
    lines: list[str] = []
    if caption and str(caption).strip():
        lines.append(str(caption).strip())
    header_values = [str(header).strip() for header in headers]
    cell_values = [_cell_text(cell) for cell in cells]
    width = max(len(header_values), len(cell_values))
    for index in range(width):
        header = header_values[index] if index < len(header_values) else ""
        cell = cell_values[index] if index < len(cell_values) else ""
        if header:
            # An empty source cell stays empty. Do not copy the cell above.
            lines.append(f"{header}: {cell}".rstrip())
        elif cell:
            lines.append(cell)
    return "\n".join(lines)


def _cell_text(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def main() -> None:
    try:
        catalog = load_catalog(CATALOG_PATH)
        blocks = load_blocks()
        chunks = build_chunks(blocks, catalog)
    except ChunkError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    write_chunks(chunks)
    print_summary(chunks, catalog)


if __name__ == "__main__":
    main()
