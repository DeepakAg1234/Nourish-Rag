"""Check a model answer against the retrieved chunks and the catalog.

The model is not asked to repair a failed check. A refusal names the search
scope from the catalog. It does not cite a document.
"""

from __future__ import annotations

from src.ingest import load_catalog

NOT_IN_CORPUS = "not_in_corpus"
ANSWERED = "answered"

NOT_IN_CORPUS_LEAD = "The guidance does not cover this question."

_CITATION_FIELDS = ("document_name", "publisher", "year", "source_url")


def search_scope_names(document_filter: str | None) -> list[str]:
    """Catalog document names in catalog order.

    A filter names that one document. No filter names all seven.
    """
    rows = load_catalog()
    if document_filter is None:
        return [row["document_name"] for row in rows]
    for row in rows:
        if row["document_id"] == document_filter:
            return [row["document_name"]]
    raise ValueError(f"unknown document_id: {document_filter}")


def not_in_corpus_message(document_filter: str | None) -> str:
    """Fixed refusal. The model does not write the document list."""
    names = "; ".join(search_scope_names(document_filter))
    return f"{NOT_IN_CORPUS_LEAD} Documents searched: {names}."


def validate(payload: dict, chunks: list[dict], document_filter: str | None = None) -> dict:
    """Return answered sections in catalog order, or the not-in-corpus refusal.

    `covered: false` discards every section, including a non-empty array.
    A section is kept only when its document was retrieved and its citation
    equals that id's catalog row. A later section for an id already kept is
    dropped and is not concatenated onto the first.
    """
    if not isinstance(payload, dict) or payload.get("covered") is not True:
        return _refusal(document_filter)

    retrieved = {chunk["document_id"] for chunk in chunks}
    catalog = {row["document_id"]: row for row in load_catalog()}
    kept: dict[str, dict] = {}
    for section in _sections(payload):
        document_id = section.get("document_id")
        if document_id not in retrieved or document_id in kept:
            continue
        if document_id not in catalog or not _citation_matches(section.get("citation"), catalog[document_id]):
            continue
        claims = _claims(section.get("claims"))
        if not claims:
            continue
        row = catalog[document_id]
        kept[document_id] = {
            "document_id": document_id,
            "claims": claims,
            "citation": {
                "document_name": row["document_name"],
                "publisher": row["publisher"],
                "year": int(row["year"]),
                "source_url": row["source_url"],
            },
        }

    if not kept:
        return _refusal(document_filter)

    order = [row["document_id"] for row in load_catalog()]
    return {
        "stage": ANSWERED,
        "message": "",
        "sections": [kept[document_id] for document_id in order if document_id in kept],
    }


def format_sections(sections: list[dict]) -> str:
    """Prose plus one citation line per section, already in catalog order."""
    blocks = []
    for section in sections:
        citation = section["citation"]
        blocks.append(
            f"{' '.join(section['claims'])}\n"
            f"{citation['document_name']}, {citation['publisher']}, "
            f"{citation['year']}, {citation['source_url']}"
        )
    return "\n\n".join(blocks)


def _refusal(document_filter: str | None) -> dict:
    return {
        "stage": NOT_IN_CORPUS,
        "message": not_in_corpus_message(document_filter),
        "sections": [],
    }


def _sections(payload: dict) -> list:
    sections = payload.get("sections")
    if not isinstance(sections, list):
        return []
    return [section for section in sections if isinstance(section, dict)]


def _claims(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [claim.strip() for claim in value if isinstance(claim, str) and claim.strip()]


def _citation_matches(citation, row: dict) -> bool:
    if not isinstance(citation, dict):
        return False
    if any(field not in citation for field in _CITATION_FIELDS):
        return False
    return (
        citation["document_name"] == row["document_name"]
        and citation["publisher"] == row["publisher"]
        and _year_matches(citation["year"], int(row["year"]))
        and citation["source_url"] == row["source_url"]
    )


def _year_matches(value, expected: int) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return value == expected
    if isinstance(value, float):
        return value.is_integer() and int(value) == expected
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip()) == expected
    return False
