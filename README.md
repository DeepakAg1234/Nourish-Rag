# Dietary Guidance RAG Chatbot

https://nourish-rag.streamlit.app/

Prototype chatbot that answers food, nutrition, and food-safety questions from seven official guidance documents.

## Business value

Health authorities already publish the guidance for two questions people actually ask: whether a way of eating is reasonable, and how long food can be kept. That guidance sits in long public documents, and there is no API for it. This prototype closes that gap for a person who needs the published answer, and for the larger project that will use this service for those two question families.

A general chat model can sound sure when the documents are silent, or blend two authorities into one claim about what "the guidelines" say. Here every claim has to come from a retrieved chunk and carry that document's name, publisher, year, and official link. If the seven documents do not cover the question, the assistant says so and names what it searched. Medical advice, a personal calorie target, and a weight target are declined in code before any search or model call.

## What it does

Each question is independent. A previous answer is not sent back as a source for the next one.

An in-scope question is searched, then answered only from the chunks that search kept. The reply is one block per document: the claims that document's chunks support, then document name, publisher, year, and the official link. Nutrition and food-safety documents stay in separate blocks. Two storage charts that give different times stay two citations.

Two refusals are different replies. Out of scope is a fixed decline that points to a qualified professional, with no citation and no document list. Not in the corpus says the guidance does not cover the question and names the documents that were searched. "How much protein is in 100 g of chicken?" is the second kind: it is not medical advice, and this corpus has no per-food nutrient table.

## Tech stack

| Piece | What this repo uses |
| --- | --- |
| Language | Python 3.11 or newer |
| Embeddings | Local `all-MiniLM-L6-v2` via `sentence-transformers` (384 dimensions, cosine). `torch` is the CPU build pinned in `requirements.txt`. |
| Vector store | Persistent Chroma collection `guidance` under `data/index/`, with a `document_id` metadata filter |
| Answer model | One OpenAI-compatible chat model. Name, key, and base URL come from `CHAT_MODEL`, `CHAT_API_KEY`, and `CHAT_BASE_URL`. The scored run in `eval.md` used `openai/gpt-oss-120b`. |
| HTTP | `httpx`, to download the block file |
| Interfaces | CLI (`python -m src.app`), localhost page (`web/index.html` via `python -m src.app --serve`), and `streamlit_app.py` |
| Tests | `unittest` under `tests/`. Answer and CLI tests use a fake model and do not call the network. |

## Key architectural decisions

### Chunking follows document structure

`src/chunk.py` keeps consecutive paragraphs and list items under one `heading_path` as one chunk. A heading is not its own chunk. The cap is about 500 tokens (`TOKEN_LIMIT`, estimated at four characters per token). Only the long heading groups split, and a split falls between blocks. When a flush lands in the middle of a list, the next chunk repeats the section heading and the paragraph that introduced the list.

A table that has rows is one chunk per row. The row text is the table caption, when there is one, then each column as `header: cell`. An empty cell stays empty. The markdown chart is not the chunk body. FAO Table 1 was extracted as a heading plus one short paragraph per nutrient, not as a table, so each of those seven lines is its own chunk (`fao-who-healthy-diets:23:0` through `fao-who-healthy-diets:29:0`).

The corpus is 339 chunks. `kitchen-companion` is 174 of them. The cost is more chunks, headers and captions repeated on every row, and no chunk that shows a whole storage or roasting chart. List items in this file are often fragments, and the Cold Food Storage Chart is one table of every food, so a question about eggs has to be able to retrieve the egg row.

| Option | Why it was not chosen |
| --- | --- |
| Fixed-size character windows | They cut numbered recommendations and storage-time rows apart. |
| One chunk for the whole Cold Food Storage Chart | A question about eggs would also carry ham, fish, and leftovers. |
| One chunk per list item | Many list items only make sense beside the sentence that introduces them. |

### Retrieval uses a wide candidate pool, then hard caps

`src/retrieve.py` does not call the chat model. Similarity is `1` minus Chroma's cosine distance. `SIMILARITY_FLOOR` is `0.0`. The acceptance questions passed at that floor, so it was left unchanged. With the floor at `0.0`, a question such as smoke point still returns neighbours; the answer layer is what abstains.

All-document search walks the nearest 32 chunks, then keeps at most 8, and at most 3 from any one `document_id`. A question that names one catalog document keeps at most 5 chunks, all from that document. An explicit `document_id` passed into `retrieve` wins over name detection. `answer_question` does not take a document id; phrase detection is the only filter on the CLI and the page. Two named documents, or a bare "WHO", stay unfiltered.

The pool of 32 exists because `kitchen-companion` is 174 of 339 chunks. On a storage question the nearest hits can all be that handbook.

| Option | Why it was not chosen |
| --- | --- |
| Take 8 neighbours, then cap at 3 per document | The first 8 can all be `kitchen-companion`, so the cap would return only that document. |
| No per-document cap | `kitchen-companion` (469 blocks in the source file) would fill the prompt and hide a second authority. |
| A re-ranker or a query rewriter | The architecture leaves both out. Metadata filters, the per-document cap, and the similarity floor carry retrieval for this corpus. |

### The scope guard runs before retrieval

`src/scope.py` returns `out_of_scope`, `in_scope`, or `in_scope_population_guidance` from phrase lists in that file. Out of scope covers medical advice, a personal calorie target, deficit, or budget, and a weight target. The reply is a fixed template. Naming WHO or the Eatwell Guide does not let a personal target through, and retrieval is not called.

Published population figures stay searchable. That includes a share of energy from fat, salt under 5 g a day, and calorie figures a guide publishes for an age band. Storage questions are in scope. The protein-in-chicken question is in scope at this stage and is refused later, after retrieval, as not in the corpus.

| Option | Why it was not chosen |
| --- | --- |
| A prompt instruction that asks the model to refuse | Prompt wording is not the enforcement. The template lives in code so the model cannot soften it. |
| A learned scope classifier | The architecture leaves this out. A missed phrase is fixed by adding a case and a test, not by asking the model to refuse. |
| Retrieve first, then refuse | Medical, calorie, and weight questions must stop before any retrieval or model call. |

### One chat model runs only after chunks survive

`src/answer.py` calls the chat model only when at least one chunk remains. The prompt contains the question, the search scope, and those chunks, each labeled with its citation fields and full text. The model must use only those chunks, write one section per `document_id`, copy citation fields from the labels, and set `covered` to false when the chunks do not contain the answer. The client asks for a JSON object at temperature 0.

`src/validate.py` checks the JSON before anything is shown. A citation whose document, publisher, year, or URL does not match the catalog row is dropped. If no section remains, the user gets the not-in-corpus refusal. The model is not asked to repair the reply.

The model name is not hard-coded. `eval.md` records the scored run as `openai/gpt-oss-120b`. A comparison among other named chat models is not recorded in this repo.

| Option | Why it was not chosen |
| --- | --- |
| A hard-coded model name and API key | The implementation plan requires both in environment variables. |
| The whole document, or the model's general knowledge, in the prompt | The block file exists so the model sees retrieved chunks only. Nearby fat guidance is not a substitute for a smoke point the corpus does not state. |
| A hidden chain step for the citation check | Scope and citation checks have to stay visible Python. Plain modules are the pipeline. |

### Embeddings stay on a local model

`src/index_corpus.py` embeds `embed_text` with `all-MiniLM-L6-v2` and replaces the `guidance` collection. The stored document is the full chunk text. The model keeps the first 256 tokens of `embed_text`; 63 embed strings in this corpus are longer than that, and the answer prompt still receives the stored full text. There is no embedding API key. The first index build downloads the model (about 80 MB). Later runs use the local copy.

The architecture allows this model or another in the same size class, because the chunk count is small enough that indexing should not spend answer-model tokens. The code pins `all-MiniLM-L6-v2`. Which other same-size model was set aside is not recorded.

| Option | Why it was not chosen |
| --- | --- |
| Embeddings from the answer-model API | Indexing this corpus should not spend answer-model tokens. |
| Storing only the 256-token window the embedding model keeps | The vector is truncated. The answer layer still needs the full chunk, including table rows and repeated list lead-ins. |
| A re-ranker on top of the bi-encoder | Left out for the same reason as in retrieval: filters, the cap, and the floor carry the contract on this corpus. |

## How to run

### Requirements

Python 3.11 or newer.

### Install

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

`requirements.txt` installs `sentence-transformers`, the CPU `torch` wheel, `chromadb`, `httpx`, `openai`, and `streamlit`. The CPU index URL is the first line of that file, so a normal `pip install -r requirements.txt` does not pull a CUDA wheel.

### Answer-model environment

The chat model name and key are environment variables. They are not hard-coded. `src/answer.py` reads a gitignored `.env` when that file is present. Existing environment variables win. This repository does not include `.env.example`.

| Variable | Required | Purpose |
| --- | --- | --- |
| `CHAT_MODEL` | Yes, for the answer layer | Model name passed to the chat client |
| `CHAT_API_KEY` | Yes, for the answer layer | API key for that client |
| `CHAT_BASE_URL` | When the host is not the default OpenAI API | OpenAI-compatible base URL. The client sends it only when the variable is set. Groq uses `https://api.groq.com/openai/v1`. |

Example:

```bash
set CHAT_MODEL=openai/gpt-oss-120b
set CHAT_API_KEY=your-groq-key
set CHAT_BASE_URL=https://api.groq.com/openai/v1
```

On macOS and Linux, use `export` instead of `set`.

The answer layer reads these variables when a retrieved question is sent to the chat model. An out-of-scope question never calls the model. Streamlit copies the same three names from Streamlit secrets when they are not already in the environment.

### Ingest

From the project root, after `pip install -r requirements.txt` (or at least `httpx`):

```bash
python -m src.ingest
```

That downloads the block file, checks every `document_id` against `data/catalog.json`, drops page headers that only repeat a document title, and writes `data/blocks.jsonl`. An unknown document id exits with an error. The citation link for each document is `source_url` in the catalog. The retrieval date in the catalog is `2026-10-05`.

### Chunk

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

Per document, that file is: `kitchen-companion` 174 (101 prose, 73 table rows), `cold-food-storage` 54 (1 prose, 53 table rows), `eatwell-guide` 43 (23 prose, 20 table rows), `who-five-keys` 27 prose, `fao-who-healthy-diets` 24 (17 prose, 7 Table 1 lines), `who-healthy-diet` 12 prose, `fsa-chill` 5 prose.

### Index

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

### Scope

`src/scope.py` runs before retrieval. It returns `out_of_scope`, `in_scope`, or `in_scope_population_guidance` from phrase lists in that file.

Out of scope covers medical advice, a personal calorie target, deficit, or budget, and a weight target. The reply is a fixed decline that points to a qualified professional. It has no citation and no document list. Naming WHO or the Eatwell Guide does not let a personal target through, and retrieval is not called.

Published population figures stay searchable. That includes a share of energy from fat, salt under 5 g a day, and calorie figures a guide publishes. Storage questions and "how much protein is in 100 g of chicken?" are in scope. The protein question is not medical advice. After retrieval, the answer layer abstains, because the corpus has no per-food nutrient table.

### Ask

From the project root, after the index is built:

```bash
python -m src.app "How long can raw eggs stay in the refrigerator?"
```

The first line logs `stage`. When retrieval ran, it also logs `filter` (`all` or one `document_id`) and the chunk ids. An out-of-scope line has no chunk ids. An answered question then prints one block per document: the claims, then document name, publisher, year, and the official link. A refusal prints `message` only. An empty or whitespace question exits 2 and does not call `answer_question`.

### Local page

The CLI is the scored path. Two pages call the same `answer_question` function. Neither retrieves or calls the model on its own.

Localhost only, no build step. The process prints `http://127.0.0.1:8765`.

```bash
python -m src.app --serve
```

`web/index.html` shows the latest question and its result. It does not send earlier questions back. A `document_id` in the request body does not change the filter.

Streamlit, from the project root:

```bash
streamlit run streamlit_app.py
```

The sidebar can show up to five earlier questions. Opening one redisplays the stored result and does not send it with the next question. If `data/index/` is missing, the app builds it on first load.

### Check

From the project root:

```bash
python -c "import src.ingest, src.chunk, src.index_corpus, src.scope, src.retrieve, src.answer, src.validate, src.app"
```

The unittest modules:

```bash
python -m unittest discover -s tests -v
```

`tests/test_imports.py` is the import check above. `unittest` does not collect that module-level function. `tests/test_retrieve.py` includes a live search against `data/index/` when that index is present.

## Repository layout

```text
data/catalog.json       # seven documents, with publisher, year, source URL, retrieval date
data/blocks.jsonl       # downloaded and joined by src/ingest.py
data/chunks.jsonl       # written by src/chunk.py
data/index/             # vector index, built by src/index_corpus.py
src/                    # pipeline modules
src/validate.py         # citation check against retrieved chunks
web/index.html          # one question, latest result only
streamlit_app.py        # same entry point, with a local display history
tests/test_imports.py   # checks that the modules import
tests/test_ingest.py    # join rules, including an unknown document id
tests/test_chunk.py     # heading groups, table rows, and FAO Table 1 lines
tests/test_retrieve.py  # name detection, the per-document cap, and live search
tests/test_scope.py     # medical, calorie, and weight refusals; population figures pass
tests/test_answer.py    # coverage gate and citation check, with a fake model
tests/test_app.py       # CLI routing, with a fake model
```

## Where to read more

[problemStatement.md](problemStatement.md) is the behaviour contract: the seven documents, citations, cross-document answers, and the two refusals.

[architecture.md](architecture.md) is the build design: pipeline shape, chunk metadata, prompt contract, and what this prototype leaves out.

[implementation-plan.md](implementation-plan.md) is the phase-by-phase build, including the chunk counts, the reason the candidate pool is 32, and the acceptance questions.
