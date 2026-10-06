# Dietary Guidance RAG Chatbot

Prototype chatbot that answers food, nutrition, and food-safety questions from seven official guidance documents. Catalog, ingest, chunking, retrieval, the scope guard, and the answer layer are implemented. Each question is independent.

The design is in [problemStatement.md](problemStatement.md), [architecture.md](architecture.md), and [implementation-plan.md](implementation-plan.md).

## Requirements

Python 3.11 or newer.

## Install

From the project root:

```bash
python -m venv .venv
```

Windows:

```bash
.venv\Scripts\activate
pip install -r requirements.txt
```

macOS and Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt
```

`requirements.txt` installs:

- `sentence-transformers` for the local `all-MiniLM-L6-v2` embedding model
- `chromadb` as the persistent vector store with metadata filters
- `httpx` to download the block file
- `openai` as the chat-model client for the answer layer

## Answer-model environment

The chat model name and key are environment variables. They are not hard-coded.

| Variable | Required | Purpose |
| --- | --- | --- |
| `CHAT_MODEL` | Yes, for the answer layer | Model name passed to the chat client |
| `CHAT_API_KEY` | Yes, for the answer layer | API key for that client |
| `CHAT_BASE_URL` | Yes, for Groq | OpenAI-compatible base URL. Groq uses `https://api.groq.com/openai/v1`. |

The checked-in template is `.env.example`. Copy it to `.env`, which is gitignored, and paste the Groq key on `CHAT_API_KEY`. The answer client reads `.env` when it runs.

Example:

```bash
set CHAT_MODEL=openai/gpt-oss-120b
set CHAT_API_KEY=your-groq-key
set CHAT_BASE_URL=https://api.groq.com/openai/v1
```

On macOS and Linux, use `export` instead of `set`.

The answer layer reads these variables when a retrieved question is sent to the chat model. An out-of-scope question never calls the model.

## Layout

```text
data/catalog.json       # seven documents, with publisher, year, source URL, retrieval date
data/blocks.jsonl       # downloaded and joined by src/ingest.py
data/chunks.jsonl       # written by src/chunk.py
data/index/             # vector index, built in Phase 3
src/                    # pipeline modules
tests/test_imports.py   # checks that the modules import
tests/test_ingest.py    # join rules, including an unknown document id
tests/test_chunk.py     # heading groups, table rows, and FAO Table 1 lines
tests/test_retrieve.py  # name detection, the per-document cap, and live search
tests/test_scope.py     # medical, calorie, and weight refusals; population figures pass
tests/test_answer.py    # coverage gate and citation check, with a fake model
tests/test_app.py       # CLI routing, with a fake model
```

## Ingest

From the project root, after `pip install -r requirements.txt` (or at least `httpx`):

```bash
python -m src.ingest
```

That downloads the block file, checks every `document_id` against `data/catalog.json`, drops page headers that only repeat a document title, and writes `data/blocks.jsonl`. An unknown document id exits with an error. The citation link for each document is `source_url` in the catalog.

## Chunk

From the project root, after ingest:

```bash
python -m src.chunk
```

That reads `data/blocks.jsonl`, joins each block to `data/catalog.json`, writes `data/chunks.jsonl`, and prints the chunk count per document.

Fixed-size character windows are the wrong tool for this file. List items are often fragments that only make sense beside the sentence that introduces them, and a storage chart is thousands of characters that should not be one vector. Chunking follows the document structure instead, and the cost is more chunks: 339, with no whole-chart chunk.

- Consecutive paragraphs and list items under one heading stay one chunk. A heading is not its own chunk.
- The cap is about 500 tokens (`TOKEN_LIMIT` in `src/chunk.py`, estimated at four characters per token). Most heading groups are already under it, including the WHO fats section and the Eatwell oils section. Only the long groups split, and a split falls between blocks, never inside a paragraph or list item. When a flush lands in the middle of a list, the next chunk repeats the section heading and the paragraph that introduced the list.
- A table that has rows is one chunk per row. The row text is the table caption, when there is one, then each column as `header: cell`. An empty cell stays empty. The markdown chart is not the chunk body.
- FAO Table 1 was extracted as a heading plus one short paragraph per nutrient, not as a table. Each of those seven lines is its own chunk (`fao-who-healthy-diets:23:0` through `fao-who-healthy-diets:29:0`).

## Index

From the project root, after chunking. The first run downloads `all-MiniLM-L6-v2` (about 80 MB). Later runs use the local copy. There is no embedding API key.

```bash
python -m src.index_corpus
```

That embeds `embed_text` from `data/chunks.jsonl` and replaces the `guidance` collection under `data/index/`. The stored text is the full chunk. Search reads that index:

```bash
python -m src.retrieve "How long can raw eggs stay in the refrigerator?"
```

Retrieval does not call the chat model. `SIMILARITY_FLOOR` in `src/retrieve.py` is `0.0`. Similarity is `1` minus cosine distance. The acceptance questions passed at this floor, so it was left unchanged.

Search takes a candidate pool of 32, then keeps at most 8 chunks and at most 3 from any one document. A question that names one document keeps at most 5 chunks, all from that document.

## Scope

`src/scope.py` runs before retrieval. It returns `out_of_scope`, `in_scope`, or `in_scope_population_guidance` from phrase lists in that file.

Out of scope covers medical advice, a personal calorie target, deficit, or budget, and a weight target. The reply is a fixed decline that points to a qualified professional. It has no citation and no document list. Naming WHO or the Eatwell Guide does not let a personal target through, and retrieval is not called.

Published population figures stay searchable. That includes a share of energy from fat, salt under 5 g a day, and calorie figures a guide publishes. Storage questions and "how much protein is in 100 g of chicken?" are in scope. The protein question is not medical advice. After retrieval, the answer layer abstains, because the corpus has no per-food nutrient table.

## Ask

From the project root, after the index is built:

```bash
python -m src.app "How long can raw eggs stay in the refrigerator?"
```

The first line logs `stage`. When retrieval ran, it also logs `filter` (`all` or one `document_id`) and the chunk ids. An out-of-scope line has no chunk ids. An answered question then prints one block per document: the claims, then document name, publisher, year, and the official link. A refusal prints `message` only. An empty or whitespace question exits 2 and does not call `answer_question`.

## Check

From the project root:

```bash
python -c "import src.ingest, src.chunk, src.index_corpus, src.scope, src.retrieve, src.answer, src.validate, src.app"
```
