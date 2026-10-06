# Edge cases

Corner cases in the code that is implemented today: catalog join (`src/ingest.py`), chunking (`src/chunk.py`), the vector index (`src/index_corpus.py`), search (`src/retrieve.py`), the embedding viewer (`src/show_embeddings.py`), and the scope guard (`src/scope.py`).

`src/answer.py`, `src/validate.py`, and `src/app.py` import and do nothing else. Citations and the chatbot entry point are not in this list.

## Ingest

`python -m src.ingest` downloads the block file, joins it to `data/catalog.json`, and writes `data/blocks.jsonl`.

| Case | What the code does |
| --- | --- |
| Catalog file is missing, not a JSON list, or an empty list | `IngestError`. Exit code 1. Nothing is written. |
| A line is not valid JSON | `IngestError` naming that line number. Exit code 1. |
| A line has no `document_id` or no `ordinal` | `IngestError` naming that line number. Exit code 1. |
| Blank or whitespace-only lines | Skipped. They are not blocks and not errors. |
| A block `document_id` is not in the catalog | `IngestError`: `unknown document_id: ...`. Exit code 1. The set of ids changing is a hard failure. |
| A catalog `document_id` never appears in the block file | `IngestError`: `catalog document_id missing from blocks: ...`. Exit code 1. |
| Download fails (timeout, HTTP error, connection error) | `error: download failed: ...` on stderr. Exit code 1. The previous `data/blocks.jsonl` is left as it was, because the file is written only after a successful join. |
| Raw block count differs from the expected snapshot (`cold-food-storage` 3, `who-healthy-diet` 92, `fao-who-healthy-diets` 98, `who-five-keys` 174, `eatwell-guide` 120, `fsa-chill` 45, `kitchen-companion` 469) | Warning printed. Ingest still writes the file. The warning uses the raw count, before page-furniture lines are dropped. |
| Page-furniture paragraph | Dropped only when `type` is `paragraph` and the text is exactly `N What are healthy diets? Joint statement by the Food and Agriculture Organization of the United Nations and the World Health Organization`. |
| Same title string with extra guidance after it | Kept. The match is a full-string match, not a prefix match. |
| A heading or list item that repeats the document title | Kept. The furniture rule applies only to paragraphs. |
| Furniture is the only block for a catalog id | The id check runs before the drop, so ingest can succeed and then write a file that no longer contains that id. |
| Blocks arrive out of order | Written sorted by `document_id`, then `ordinal`. Equal keys keep their incoming order. |
| Catalog rows carry more than one `retrieval_date` | The summary prints every distinct date, comma-separated. The code does not overwrite the date with the download day. |

## Chunking

`python -m src.chunk` reads `data/blocks.jsonl` and writes `data/chunks.jsonl`. A heading is never its own chunk. Prose splits only between blocks. A table with `rows` becomes one chunk per row. FAO Table 1 lines (ordinals 23–29) become one chunk each.

| Case | What the code does |
| --- | --- |
| `data/blocks.jsonl` is missing | `ChunkError`. Exit code 1. |
| A chunk line is not valid JSON | `ChunkError` naming that line number. Exit code 1. |
| Blank lines in the block file | Skipped. |
| Block `document_id` is not in the catalog | `ChunkError`: `unknown document_id`. |
| Catalog document has no blocks | No chunks for that id. Chunking does not repeat the ingest check that every catalog id must appear. |
| Two chunks would share a `chunk_id` | `ChunkError`: `duplicate chunk_id`. |
| Heading block | Flushes the open prose buffer, updates the section, and emits nothing. `lead_in` is cleared, so a list in the next section does not inherit the previous section's paragraph. |
| Prose appears before any heading, or `heading_path` is empty | `ChunkError`: prose block with an empty section heading. |
| Empty or whitespace-only paragraph or list item | Skipped. It does not open a chunk and does not change `lead_in`. |
| Block type other than `heading`, `paragraph`, `list_item`, or `table` | Skipped. |
| `type` is `table` but `rows` is missing | Skipped. The markdown `text` is not indexed. |
| `rows` is an empty list | The table emits no chunks. |
| Table with an empty section heading | `ChunkError` naming the table ordinal. |
| One paragraph longer than `TOKEN_LIMIT` (500) | Kept whole. The splitter never cuts inside a paragraph or list item, even when `token_limit` is set far below that block. |
| Adding the next block would pass the limit | Flush first, then start a new chunk with the next block. The check is `(len(text) + 3) // 4`. |
| The flush lands on a list item, and a paragraph already introduced that list | The next chunk's text starts with that paragraph again. The repeated paragraph's ordinal is not added to the new chunk's `ordinals`. |
| The flush lands on a paragraph | No lead-in is copied. The new chunk starts with that paragraph. |
| Several paragraphs, then a list | The repeated lead-in is the latest paragraph, not the first one under the heading. |
| List item with no paragraph yet under that heading | Indexed on its own. There is no lead-in to copy. |
| Lead-in plus the next list item still exceeds 500 tokens | The chunk is still emitted. The cap stops a chunk from growing; it does not split a block that is already over the cap. That is why some prose chunks in this corpus are longer than 500 tokens. |
| Consecutive paragraphs and list items under the same `heading_path` that stay under the cap | One chunk. Short list fragments stay with the sentence that introduces them. |
| Heading path changes | Flush. Sections are not merged. |
| Table row | `chunk_id` is `{document_id}:{table ordinal}:{row index}`. Two tables under one heading stay distinct because the ordinal differs. |
| Table `text` (the markdown chart) when `rows` is present | Ignored. Row text is built from `caption`, `header`, and `rows`. |
| Caption present | Copied onto every row of that table only. The next table under the same heading does not inherit it. |
| Caption missing or blank | Row text starts at the cells. |
| Empty source cell | Stored as `Header:` with nothing after it. The cell above is not copied down. |
| More cells than headers | Extra cells are appended as bare text. |
| More headers than cells | Extra headers are written with an empty cell. |
| Cell value is `null` | Treated as an empty cell. |
| FAO ordinal 22 | Heading only. Its text is stored and later prefixed onto each Table 1 line. It is not a chunk. |
| FAO ordinals 23–29 | One `fao_table1` chunk each. Text is the Table 1 heading plus that line. These lines are not merged into the essay that follows under the same heading. |
| FAO Table 1 line appears before ordinal 22 was seen | `ChunkError`: FAO Table 1 heading was not seen before its nutrient lines. |
| FAO ordinals 30 and later under that same heading | Normal prose rule, including the 500-token cap. |
| Catalog row missing `document_name`, `publisher`, `source_url`, `retrieval_date`, or `year` | `ChunkError` naming the missing field. `year` of `0` is allowed. |
| Chunk text empty after stripping | `ChunkError`. |
| Chunk order | Catalog order, then `ordinal` inside each document. |

Corpus facts these rules are there to protect:

- `cold-food-storage:2:35` is only the raw-eggs-in-shell row (`3 to 5 weeks`, refrigerator header). Ham, fish, and leftovers are other rows.
- `fao-who-healthy-diets:23:0` is `Saturated 10% or less` plus the Table 1 heading. The protein essay is a different chunk.
- `eatwell-guide:105:4` (Oils and spreads table row) and the prose section `A closer look at Oils and spreads` are different chunks.
- `kitchen-companion:252` rows repeat the caption temperatures `325 °F` and `165 °F`.
- `kitchen-companion:216:10` (country ham) keeps empty timing and temperature cells. Beef is not in that table.
- `kitchen-companion:215:0` and `kitchen-companion:217:0` can carry the same sentence. They stay two chunks.

The current snapshot is 339 chunks: 146 table rows and 7 FAO Table 1 lines.

## Index

`python -m src.index_corpus` embeds `embed_text` with `all-MiniLM-L6-v2` (384 dimensions, normalized) and replaces the `guidance` collection in `data/index/`. The space is cosine. The stored document is the full `text`, not `embed_text`.

| Case | What the code does |
| --- | --- |
| `data/chunks.jsonl` is missing or has no chunk rows | `IndexBuildError`. Exit code 1. |
| A line is not valid JSON | `IndexBuildError` naming that line number. |
| Blank lines | Skipped. |
| Missing `chunk_id`, or `embed_text` / `text` blank after stripping | `IndexBuildError` naming that line. |
| Duplicate `chunk_id` | `IndexBuildError`. Both ids are required when two chunks share the same `embed_text` (`kitchen-companion:215:0` and `kitchen-companion:217:0`). |
| A metadata field in `document_id`, `document_name`, `publisher`, `year`, `source_url`, `retrieval_date`, `section_heading`, `source` is missing or `""` | `IndexBuildError` naming the chunk and field. |
| `year` | Stored as an int. A numeric string is coerced. A non-numeric year fails at `int(...)`. |
| `ordinals` missing, not a list, or empty | `IndexBuildError`. |
| `ordinals` present | Stored as a comma-joined string, because Chroma metadata values are scalars. |
| `embed_text` longer than the model's 256-token window | The vector is the truncated embedding. The collection document stays the full chunk text. |
| Rebuild | `delete_collection("guidance")` then `create_collection`. An old collection is not upserted into. |
| First build, collection does not exist yet | The delete error is ignored and the collection is created. |
| Delete fails for a reason other than a missing collection | That error is also ignored, and create then runs. |
| Embedding batch length or width is not 339 × 384 | `IndexBuildError`. |
| Model already loaded in this process | Reused. A new process loads it again. |

## Retrieval

`python -m src.retrieve` embeds the question with the same local model. It does not call a chat model. `SIMILARITY_FLOOR` is `0.0`. Cosine similarity is `1 - distance`.

All-document search takes the nearest 32 chunks, keeps at most 3 per `document_id`, and stops at 8 kept chunks. Single-document search takes the nearest 5 from that document only.

| Case | What the code does |
| --- | --- |
| Question missing or only whitespace | `RetrieveError`: `question is empty`. The CLI exits 2 when no argument is given. |
| `guidance` collection missing | `RetrieveError` telling you to run `python -m src.index_corpus`. |
| Similarity below `0.0` | Dropped before the cap. A similarity of exactly `0.0` is kept. |
| First neighbours are all one document | The walk continues through the pool of 32, so a later document can still take a slot. A fetch of 8 would have filled the cap with that one document. |
| More than 8 chunks survive the per-document cap | Stop at 8, in rank order. |
| One document already has 3 kept chunks | Further hits from that document are skipped. Other documents in the pool can still be added. |
| Explicit `document_id` argument | Wins over phrases in the question. Search is limited to that id, nearest 5. |
| `document_id` argument is `""` or `None` | Phrase detection runs. |
| Filtered id has no rows in the index | Return `[]`. This includes an id that is not one of the seven documents. |
| Fewer rows than the requested `n_results` | Query size is `min(limit, available)`, so Chroma is not asked for more rows than the filter contains. |
| `fsa-chill` (5 chunks) or any document with 5 or fewer chunks above the floor | Single-document search can return all of them. The cap of 3 applies only to all-document search. |
| CLI | Filter comes only from the question text. There is no CLI flag for `document_id`. |

Name detection is a case-insensitive substring match. One matched id filters search. Zero or two or more matched ids leave search unfiltered.

| Phrase in the question | Filter |
| --- | --- |
| `Eatwell` | `eatwell-guide` |
| `Five Keys` | `who-five-keys` |
| `Kitchen Companion` | `kitchen-companion` |
| `Cold Food Storage` or `FoodSafety.gov` | `cold-food-storage` |
| `Food Standards Agency` | `fsa-chill` |
| `fact sheet` | `who-healthy-diet` |
| `What are healthy diets` or `joint statement` | `fao-who-healthy-diets` |
| `healthy diet` or `healthy diets`, and neither nutrition id is already matched | Both nutrition ids, so the search stays unfiltered |
| `WHO` alone | No id. Unfiltered. Three catalog rows involve WHO. |
| Two of the phrases above | Unfiltered. Example: Eatwell and Kitchen Companion in one question. |
| `What are healthy diets?` | `fao-who-healthy-diets` only. The broader `healthy diets` phrase does not add the fact sheet once the joint-statement id is already matched. |
| `the healthy diet fact sheet` | `who-healthy-diet` only. `fact sheet` is the specific match. |

Same shape of chart, different documents, stay separate hits:

| Chunk | Fact that must not be merged |
| --- | --- |
| `cold-food-storage:2:35` | Raw eggs in shell, refrigerator `3 to 5 weeks` (FoodSafety.gov) |
| `kitchen-companion:285:0` | Egg Storage Chart, raw eggs in shell, refrigerator `3 to 5 weeks` (USDA) |
| `cold-food-storage:2:0` | Salads, `3 to 4 days` |
| `kitchen-companion:92:0` | Salads, `3 to 5 days` |

## Embedding viewer

`python -m src.show_embeddings` reads vectors already stored in Chroma. It does not load the embedding model and does not re-embed.

| Case | What the code does |
| --- | --- |
| `data/index/` does not exist | Error on stderr. Exit code 1. |
| `guidance` collection is not in the index | Error on stderr. Exit code 1. |
| Collection exists and has 0 rows | Prints `stored=0`. Exit code 0. |
| `--limit` less than 1 | Error on stderr. Exit code 1. |
| `--limit` greater than the number of stored chunks | Clamped to the collection size. |
| Chunk text | Newlines become spaces. Longer than 120 characters is cut to 117 characters plus `...`. |
| Metadata missing `document_id` or `section_heading` | Those fields print as empty. The chunk is still shown. |
| Embedding longer than 8 values | First 8 values are printed, then `...` and the real dimension. |

## Scope guard

`classify` returns `out_of_scope`, `in_scope`, or `in_scope_population_guidance`. `screen` calls the retrieve function only for the last two. Phrase lists live in `src/scope.py`. The answer model is not asked to refuse.

| Case | What the code does |
| --- | --- |
| Medical advice: a disease, symptom, diagnosis, medication, or "what diet should I follow" | `out_of_scope`. Fixed template. Retrieve is not called. |
| Personal calorie target, deficit, or budget, including "how many calories should I eat" | `out_of_scope`. The same template. Retrieve is not called. |
| What someone should weigh, a goal weight, or how much weight to lose or gain, including "lose 5 kg" | `out_of_scope`. The same template. Retrieve is not called. |
| A personal calorie or weight target that also names WHO, Eatwell, or a fat limit | Still `out_of_scope`. The document name does not start retrieval. |
| Published population figure: energy share, salt under 5 g a day, or calorie figures a guide publishes | `in_scope_population_guidance`. Retrieve may run. |
| Storage, handling, oils, or "how much protein is in 100 g of chicken?" | `in_scope`. Retrieve may run. Protein grams are not medical advice. |
| Template | Declines medical advice, personal calorie targets, and weight targets, and points to a qualified professional. No URL and no document list. |

## Not implemented yet

These behaviors are specified in the problem statement and the implementation plan. No code path enforces them today.

- Not-in-corpus refusal when nothing is retrieved, or when the model marks the chunks as not covering the question.
- Answers restricted to retrieved chunks, one section per document, citations checked against the catalog.
- A single entry point that runs scope, retrieve, answer, and validate, with no chat history.
