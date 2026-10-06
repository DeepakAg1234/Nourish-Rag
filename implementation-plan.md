# Dietary Guidance RAG Chatbot — Implementation Plan

Build the prototype described in [problemStatement.md](problemStatement.md) by following [architecture.md](architecture.md). Each phase ends with a check you can run before the next phase starts. Do not call the answer model until the corpus, chunks, index, and scope guard are already correct.

The text source is the extracted block file:

https://raw.githubusercontent.com/saksham20189575/health-data/main/blocks.jsonl

Citations use the seven official source URLs in the problem statement, not that file's URL.

## How the phases map to the deliverables

| Phase | What it finishes | Problem-statement deliverable |
| --- | --- | --- |
| 0 | Project skeleton | — |
| 1 | Catalog and ingest | Corpus |
| 2 | Chunks | Chunking |
| 3 | Vector index and both search modes | Retrieval |
| 4 | Scope guard | Refusal — out of scope |
| 5 | Answer model, coverage gate, citation check | Answer layer, cross-document handling, refusal — not in corpus |
| 6 | One entry point that runs the stages in order | The prototype chatbot |
| 7 | Acceptance questions, README trade-off, and an updated eval | All of the above, demonstrated |
| 8 | A local page over that same entry point | The same chatbot, in a browser |

Phases 0–4 are implemented. [edge-case.md](edge-case.md) records that behavior. [eval.md](eval.md) scores it, including the scope decisions. Phases 5–8 leave ingest, chunking, name detection, the candidate pool of 32, and the caps of 8, 3, and 5 as they are. Phase 7 may change `SIMILARITY_FLOOR` only when the retrieval probes already in `eval.md` still pass. Phase 8 does not change that floor, and it is not a second scoring path.

## Phase 0 — Skeleton

Create the layout from the architecture, with no behaviour yet.

```text
data/catalog.json
data/blocks.jsonl          # filled in Phase 1
data/index/                # filled in Phase 3
src/ingest.py
src/chunk.py
src/index_corpus.py
src/scope.py
src/retrieve.py
src/answer.py
src/validate.py
src/app.py
tests/
README.md
requirements.txt
```

Dependencies: a local embedding model in the `all-MiniLM-L6-v2` size class, a persistent vector store with metadata filters (Chroma or equivalent), an HTTP client to download the block file, and one chat-model client used only in Phase 5. Put the chat-model name and key in environment variables. Do not hard-code them.

**Done when:** the modules import, and `README.md` lists how to install dependencies and which environment variables the answer model needs. Later phases fill the README trade-off. Do not describe chunking there yet.

## Phase 1 — Catalog and ingest

### 1.1 Write `data/catalog.json`

One row per document. Fields: `document_id`, `document_name`, `publisher`, `year`, `source_url`, `retrieval_date`, `kind`.

| `document_id` | `kind` | Year | Publisher |
| --- | --- | --- | --- |
| `cold-food-storage` | `food_safety` | 2023 | FoodSafety.gov (U.S. Department of Health and Human Services / FDA / USDA) |
| `who-healthy-diet` | `nutrition` | 2018 | World Health Organization |
| `fao-who-healthy-diets` | `nutrition` | 2024 | Food and Agriculture Organization of the United Nations and World Health Organization |
| `who-five-keys` | `food_safety` | 2006 | World Health Organization |
| `eatwell-guide` | `nutrition` | 2018 | Public Health England (now Office for Health Improvement and Disparities) |
| `fsa-chill` | `food_safety` | 2017 | Food Standards Agency (UK) |
| `kitchen-companion` | `food_safety` | 2008 | USDA Food Safety and Inspection Service |

Copy each `source_url` from §3.1 of the problem statement. Set `retrieval_date` to the date `blocks.jsonl` is downloaded. The citation link is `source_url`.

### 1.2 Download and join

`src/ingest.py` downloads the block file into `data/blocks.jsonl` and checks the join:

- Every block `document_id` exists in the catalog.
- Every catalog `document_id` appears at least once.
- Expected block counts are about: `cold-food-storage` 3, `who-healthy-diet` 92, `fao-who-healthy-diets` 98, `who-five-keys` 174, `eatwell-guide` 120, `fsa-chill` 45, `kitchen-companion` 469. Fail if the set of ids changes. A small count drift is a warning, not a silent accept.
- Drop page-furniture lines that only repeat the document title. Keep real guidance.

Sort blocks by `document_id`, then `ordinal`.

**Done when:** ingest prints seven ids, the retrieval date, and the block count per document, and it exits with an error on an unknown id. No embeddings yet.

## Phase 2 — Chunking

Implement `src/chunk.py` from the downloaded `data/blocks.jsonl`, using [architecture.md](architecture.md) §5 where the snapshot matches it. The snapshot does not match one rule for every grid.

After ingest the file has 997 blocks: headings, paragraphs, list items, and 12 `type: table` blocks (146 data rows). Six of those tables also have a `caption`. List items are often fragments (`reducing saturated fats to less than 10% of total energy intake`, `Faeces;`, `nuts`) that only make sense beside the sentence that introduces them. One nutrient grid was not extracted as a table: in `fao-who-healthy-diets`, Table 1 is a heading plus one short paragraph per nutrient. Fixed-size character windows are still the wrong tool.

Walk each document in `ordinal` order. A `heading` sets the section and is never its own chunk. Do not emit a chunk for an empty heading.

### 2.1 Prose

Consecutive `paragraph` and `list_item` blocks with the same `heading_path` accumulate into one chunk. Flush when the heading changes, or when adding the next block would pass about 500 tokens. Split only between blocks, never inside a paragraph or list item.

Most heading groups are already under that cap, including the WHO `Fats` section (the "less than 30% of total energy" paragraph and the saturated-fat and trans-fat list items that follow it) and the Eatwell section `A closer look at Oils and spreads`. Keep those as one chunk each so a fragment is not embedded on its own.

The cap exists for the long groups in this file, about 1,800–3,800 characters: the Five Keys glossary, WHO `HOW TO PROMOTE HEALTHY DIETS` and `WHO RESPONSE`, the FAO sections `1.1 Adequate`, `1.3 Moderate`, `1.4 Diverse`, the conclusion, and Annex 2 `Carbohydrate`, plus the kitchen-companion sections on pathogenic bacteria, microwave cooking, grilling, slow cooking, and power outages. When a flush lands in the middle of a list, start the next chunk with the same section heading and repeat the latest paragraph that introduced the list, so a later bullet is not indexed without its lead-in.

### 2.2 Tables that have `rows`

If `type` is `table` and `rows` is present, ignore the markdown `text` field. That field is the whole chart (about 4,600 characters for cold storage, about 5,100 for the Eatwell food-group table). Emit one chunk per row.

Build the row text in this order:

1. The table `caption`, when the block has one.
2. Each column as `header: cell`. The headers in this file are the units (`Refrigerator [40°F (4°C) or below]`, `Freezer`, `°F (°C)`, `Unstuffed`, `Stuffed`). The section heading often does not name them.
3. Leave a cell empty when the source cell is empty. Do not fill it from the row above. The only empty cells are the last row of the kitchen-companion poultry and ham roasting table (`ordinal` 216, country ham): the method is already in the meat cell.

Copy the caption onto every row of that table. Six captions carry facts that are not in the cells. The turkey roasting caption says to set the oven at 325°F and cook to 165°F. The alternate-methods caption says where to measure 165°F. `Cold Storage Chart`, `Roasting Chart`, `Turkey Thawing Chart`, and `Egg Storage Chart` name the chart the row came from.

`chunk_id` uses the table block's `ordinal`, not only the heading. Two kitchen-companion roasting tables (`ordinal` 214, caption `Roasting Chart`, 8 rows; `ordinal` 216, no caption, 11 rows) share the heading path `Special Guidelines for Certain Food > Roasts > Watch Temperatures Closely`.

The 12 tables:

| Document | `ordinal` | Rows | What a row must keep |
| --- | --- | --- | --- |
| `cold-food-storage` | 2 | 53 | `Food`, `Type`, refrigerator time, freezer time. Raw eggs in shell are `Eggs` / `Raw eggs in shell` / `3 to 5 weeks`. No other food from the chart is in that chunk. |
| `eatwell-guide` | 71 | 3 | Age band and maximum free sugars. |
| `eatwell-guide` | 81 | 11 | One age, with male and female kcal and kJ headers. These are published population figures. Index them. The scope guard in Phase 4 is what refuses a personal calorie target. |
| `eatwell-guide` | 105 | 6 | One food group. `Oils and spreads` is its own row. Cells are long (up to about 500 characters) and are still one chunk. |
| `kitchen-companion` | 92 | 17 | Caption `Cold Storage Chart`, product, refrigerator, freezer. Times differ from `cold-food-storage` (salads are 3 to 5 days here). |
| `kitchen-companion` | 178 | 6 | Food and safe minimum internal temperature. |
| `kitchen-companion` | 214 | 8 | Caption `Roasting Chart`, meat, oven temperature, timing, safe internal temperature. |
| `kitchen-companion` | 216 | 11 | Same columns as 214, no caption. Beef is not in this table. |
| `kitchen-companion` | 232 | 4 | Caption with the thawing rates, turkey size, refrigerator time, cold-water time. |
| `kitchen-companion` | 252 | 7 | Caption with 325°F and 165°F, size, unstuffed time, stuffed time. |
| `kitchen-companion` | 254 | 5 | Caption with the 165°F measurement sites, method, size, time, notes. |
| `kitchen-companion` | 285 | 15 | Caption `Egg Storage Chart`, product, refrigerator, freezer. The heading path ends at `Eggs and Egg-Rich Food` under a cooking-methods section, so the header and caption are what make the row a storage answer. |

### 2.3 The FAO table that is not a table

`fao-who-healthy-diets` ordinal 22 is a heading, not `type: table`. Its text is `Table 1. Recommended intakes of protein, fat and carbohydrates as a proportion of dietary energy intake`, with the column sense `Nutrient` / `Adults` concatenated onto that heading. The next paragraphs are the cells, still on that same `heading_path`:

| `ordinal` | Text |
| --- | --- |
| 23 | Saturated 10% or less |
| 24 | Trans 1% or less |
| 25 | Polyunsaturated 6-10% |
| 26 | Monounsaturated — the cell says the amount varies |
| 27 | Carbohydrates 45-75% |
| 28 | Free sugars 10% or less, plus footnote a |
| 29 | Footnote b |

Emit one chunk per ordinal from 23 through 29. Each chunk's text is the Table 1 heading plus that paragraph, so "10% or less" stays tied to "proportion of dietary energy intake" and "Adults". Do not merge these lines into the essay that follows.

From ordinal 30 under that same heading (the figure note, the short figure labels, then the protein, fat, and carbohydrate paragraphs of about 900, 1,100, and 700 characters), use the prose rule in §2.1, including the 500-token cap. Do not turn every short paragraph in the corpus into its own chunk. This exception is only the Table 1 cell run.

The same fat figures also appear as normal prose and should stay with their own heading groups: WHO `Fats`, FAO `1.3 Moderate` ("no more than 10% of daily energy" from saturated fat and "no more than 1%" from trans-fat), and Annex 2 `Fat` (seven numbered recommendations, one list item each, short enough to stay one chunk).

### 2.4 Chunk fields

`chunk_id` (`{document_id}:{first_ordinal}:{row_index}`). For a prose chunk and for an FAO Table 1 line, `row_index` is `0`. For a table row it is the row offset inside that table block. Also store `document_id`, `document_name`, `publisher`, `year`, `source_url`, `retrieval_date`, `section_heading` (`heading_path` joined with ` > `), `ordinals`, and `text`.

The string embedded in Phase 3 is the section heading plus `text`. Build it here.

**Done when:**

- The raw-egg refrigerator row is its own `cold-food-storage` chunk. Its text contains `3 to 5 weeks` and the refrigerator column header, and it does not contain ham, fish, or leftovers.
- The FAO line `Saturated 10% or less` is its own chunk, with the Table 1 heading, and that chunk does not contain the protein essay.
- The Eatwell `Oils and spreads` table row and the prose section `A closer look at Oils and spreads` are different chunks.
- A turkey size row from `ordinal` 252 includes the caption's 325°F and 165°F.
- Every chunk has a non-empty section heading and the catalog's publisher, year, and source URL.
- No chunk is a fixed-size character window, and no chunk is a single short list fragment that had an introducing paragraph under the same heading.
- The script prints chunk counts per document. Table rows account for 146 of them, plus the seven FAO Table 1 lines. Those counts go into the README in Phase 7, with the cost: more chunks, headers and captions repeated on every row, the flattened FAO lines indexed separately from the essay under the same heading, and no chunk that shows a whole storage or roasting chart.

## Phase 3 — Index and retrieval

The snapshot is `data/chunks.jsonl`: 339 chunks from Phase 2. Index that file. The indexer embeds `embed_text` and does not run a second splitter.

| `document_id` | Chunks | Of which |
| --- | --- | --- |
| `kitchen-companion` | 174 | 101 prose, 73 table rows |
| `cold-food-storage` | 54 | 1 prose, 53 table rows |
| `eatwell-guide` | 43 | 23 prose, 20 table rows |
| `who-five-keys` | 27 | prose |
| `fao-who-healthy-diets` | 24 | 17 prose, 7 Table 1 lines |
| `who-healthy-diet` | 12 | prose |
| `fsa-chill` | 5 | prose |

`kitchen-companion` is 174 of the 339 chunks. That share is why the per-document cap exists.

### 3.1 Build

`src/index_corpus.py` embeds each `embed_text` with the local `all-MiniLM-L6-v2` model (384 dimensions) and writes one collection under `data/index/`. Use cosine space, so a later similarity floor is a cosine similarity. Rebuild the collection from this file. Replace the previous collection rather than upserting into an old one.

The vector id is `chunk_id`. Metadata has to be scalar, so store `ordinals` as a comma-joined string. Store `document_id`, `document_name`, `publisher`, `year`, `source_url`, `retrieval_date`, `section_heading`, and `source` (`prose`, `table_row`, or `fao_table1`). Keep the full `text` on the record the answer layer will see. `year` is an int. Every row's `retrieval_date` is `2026-10-05`.

The embedding model keeps the first 256 tokens. On the same four-characters-per-token estimate Phase 2 used, 63 `embed_text` values are longer than that: 61 prose chunks, plus the Eatwell food-group rows `eatwell-guide:105:0` (fruit and vegetables) and `eatwell-guide:105:3` (beans, pulses, fish, eggs, meat and other proteins). Eight prose chunks are also past about 500 tokens, because a repeated list lead-in was added to an already long block. The longest is `fao-who-healthy-diets:77:0` (Annex 2 `Carbohydrate`). Store the full text anyway. The vector is the model's truncated embedding of `embed_text`. Leave those chunks whole.

`kitchen-companion:215:0` and `kitchen-companion:217:0` have the same `embed_text` (the sentence about cooking meats and poultry to higher temperatures, once before the roasting tables and once after). Upsert both ids. Two kitchen-companion roasting tables still share the heading `Special Guidelines for Certain Food > Roasts > Watch Temperatures Closely`; `chunk_id` keeps `214` and `216` apart.

### 3.2 Search

`src/retrieve.py` supports both required modes. Drop chunks under the similarity floor in both. If the store returns cosine distance, similarity is `1 - distance`. Leave `SIMILARITY_FLOOR` as a named constant. Tune it in Phase 7 against the acceptance questions, and record the value you keep.

| Mode | Behaviour |
| --- | --- |
| All documents | Walk a candidate pool of the nearest 32 chunks in rank order. Keep a chunk while that `document_id` has fewer than 3 kept chunks. Stop at 8 kept chunks. |
| One document | An explicit `document_id` argument wins. Otherwise the dictionary below maps a question onto one id. Nearest 5 chunks from that document only. |

A fetch of 8, then a cap of 3, cannot do what the cap is for. On a storage or cooking question the first 8 neighbours can all be `kitchen-companion`, and the cap would then return 3 chunks from that document and nothing else. The pool of 32 is what lets a second document in that neighbourhood survive. The prompt still receives at most 8 chunks, and at most 3 from one document. `fsa-chill` has only 5 chunks and `who-healthy-diet` has 12, so the single-document cap of 5 drops nothing from `fsa-chill` unless a chunk is under the floor.

Name detection matches one catalog document, using the names on the chunks:

| Phrase in the question | `document_id` |
| --- | --- |
| `Eatwell` | `eatwell-guide` |
| `Five Keys` | `who-five-keys` |
| `Kitchen Companion` | `kitchen-companion` |
| `Cold Food Storage` or `FoodSafety.gov` | `cold-food-storage` |
| `Food Standards Agency` | `fsa-chill` |
| `healthy diet` fact sheet, or `fact sheet` | `who-healthy-diet` |
| `What are healthy diets` or `joint statement` | `fao-who-healthy-diets` |

Leave the question unfiltered when the phrases above match two ids, or when the only hit would be a bare `WHO`. Three rows involve the World Health Organization: `who-healthy-diet`, `who-five-keys`, and `fao-who-healthy-diets`. `healthy diet` on its own also matches both the fact sheet and `What are healthy diets? Joint statement`. The answer layer separates whatever comes back.

Two storage rows will both neighbour an egg question. Keep them as separate hits:

| `chunk_id` | What the row says |
| --- | --- |
| `cold-food-storage:2:35` | `Eggs` / `Raw eggs in shell` / refrigerator `3 to 5 weeks` |
| `kitchen-companion:285:0` | Caption `Egg Storage Chart`, `Raw eggs in shell`, refrigerator `3 to 5 weeks` |

The same chart shape is not the same fact for every food. Salads are `3 to 4 days` on `cold-food-storage:2:0` and `3 to 5 days` on `kitchen-companion:92:0`. Retrieval returns row chunks, so those times stay on their own ids.

**Done when:**

- A query about how long raw eggs stay in the refrigerator returns `cold-food-storage:2:35` among the kept chunks. `kitchen-companion:285:0` may appear as well. The FoodSafety.gov row is a complete hit on its own.
- Filtered search for `eatwell-guide` returns only that `document_id`, drawn from its 43 chunks. An oils question in that mode can return both the prose section `A closer look at Oils and spreads` and the table row `eatwell-guide:105:4`.
- A question that names Eatwell and Kitchen Companion is unfiltered. A question that only says `WHO` is unfiltered.
- This phase does not call the chat model.

## Phase 4 — Scope guard

Implemented. `src/scope.py` and `tests/test_scope.py` are in place, and `eval.md` scores the scope decisions below. The CLI log that proves retrieval was skipped is still Phase 6, because `app.py` writes that log.

Implement `src/scope.py` before any answer-model code. It returns `out_of_scope`, `in_scope`, or `in_scope_population_guidance`. Rules and phrase lists live in this file. There is no earlier milestone to copy, and the model is not asked to refuse.

This phase scores the scope half of the acceptance questions. The cited answers and the not-in-corpus refusals stay under "Not scored yet" until Phase 7. Retrieval behavior from Phases 0–3 stays as `edge-case.md` describes it.

**Refuse in code, with a fixed template, and do not retrieve:**

- Medical advice: diagnosis, treatment, medication, or what to do about a disease or symptom. "I have diabetes. What diet should I follow?" refuses.
- A personal calorie target, deficit, or budget. "How many calories should I eat to lose 5 kg?" refuses.
- What anyone should weigh, a goal weight, or how much weight to lose or gain. "What should I weigh?" refuses.

The template declines and points the person to a qualified professional. It includes no citation and no document list.

A question that asks for a personal target and also names a guideline or a document still refuses. Naming WHO or Eatwell is not a reason to retrieve.

- "Using the WHO fat limit, how many calories should I eat?" is `out_of_scope`.
- "According to the Eatwell Guide, how many calories should I eat?" is `out_of_scope`.

**Let through to retrieval:**

- Published population figures, such as the share of energy from fat, or salt under 5 g a day. "What share of energy intake does WHO recommend from fat?" is `in_scope_population_guidance`. Phase 3 leaves that question unfiltered, because a bare WHO matches no `document_id`.
- "What calorie figures does the Eatwell Guide publish?" is `in_scope_population_guidance`. The Eatwell age-band rows (`eatwell-guide:81`) are published population figures. The guard refuses a personal budget, not those rows.
- Storage and handling questions, including "How long can raw eggs stay in the refrigerator?" These are `in_scope`.
- "How much protein is in 100 g of chicken?" is `in_scope`. It is not medical advice and not a weight target. Phase 5 abstains after retrieval, because the corpus has no per-food nutrient table.

Put the cases in `tests/test_scope.py`. Each `out_of_scope` test asserts that `retrieve` is not called.

**Done when:** those tests pass, including the mixed guideline-plus-personal-target questions, and a population-guidance question is allowed through.

## Phase 5 — Answer, coverage gate, and citation check

### 5.1 Coverage gate

`retrieve` already drops chunks under `SIMILARITY_FLOOR` (currently `0.0`). The gate does not apply a second floor.

If the kept list is empty, do not call the model. Return the not-in-corpus template. Name the search scope from the catalog, in catalog order: the one filtered document's `document_name`, or all seven names. The model does not write that list.

With the floor at `0.0`, the egg, oils, fats, smoke-point, and protein questions return chunks. Smoke point and grams of protein abstain on the path in §5.2, after retrieval. An empty list is the path for a filter that matches nothing. The app does not pass a `document_id` outside the catalog. Phrase detection is the only filter, the same rule as the `src.retrieve` CLI.

### 5.2 Answer

`src/answer.py` calls the chat model only when at least one chunk survived the gate. The prompt contains the question, the search scope from §5.1, and those chunks. Label each chunk with `chunk_id`, `document_id`, `document_name`, `publisher`, `year`, `source_url`, `section_heading`, and the full `text`. The embedding model keeps 256 tokens of `embed_text`. The prompt still gets the stored full text.

Instruct the model to:

- Use only those chunks.
- Write one section per `document_id`. Several chunks from one document are one section. `kitchen-companion:215:0` and `kitchen-companion:217:0` share their text and still belong to one Kitchen Companion section.
- Never write a combined claim about what "the guidelines" say.
- Copy citation fields from the chunk labels.
- Leave an empty table cell empty. `kitchen-companion:216:10` does not inherit a time from the row above.
- Set `covered` to false and leave `sections` empty when the chunks do not contain the answer.

Nearby chunks are not a substitute answer:

- Fat and oil guidance does not answer "What is the smoke point of olive oil?"
- A protein share of dietary energy does not answer "How much protein is in 100 g of chicken?"
- The WHO fat share and the Eatwell age-band table are population figures. The model does not turn them into a personal calorie target.

The same chart shape in two documents stays two sections when both chunks were retrieved:

| Chunks | What stays apart |
| --- | --- |
| `cold-food-storage:2:35` and `kitchen-companion:285:0` | Raw eggs in shell, refrigerator `3 to 5 weeks`, two publishers |
| `cold-food-storage:2:0` and `kitchen-companion:92:0` | Salads, `3 to 4 days` and `3 to 5 days` |

An Eatwell oils question is filtered to `eatwell-guide`, so the prompt contains only that document's chunks. The model has no other document's text from which to cite.

Response JSON:

```json
{
  "covered": true,
  "sections": [
    {
      "document_id": "who-healthy-diet",
      "claims": ["..."],
      "citation": {
        "document_name": "Healthy diet (Fact sheet)",
        "publisher": "World Health Organization",
        "year": 2018,
        "source_url": "https://www.who.int/docs/default-source/healthy-diet/healthy-diet-fact-sheet-394.pdf"
      }
    }
  ]
}
```

### 5.3 Validate

`src/validate.py` runs before anything is shown. Fixtures stand in for the model. These tests do not call the network.

- `covered: false` becomes the not-in-corpus refusal. Discard sections, including a non-empty `sections` array. Name the search scope from §5.1.
- Every `document_id` must be in the retrieved set. Drop any other section.
- Name, publisher, year, and URL must equal that id's catalog row. A URL that is not the catalog URL drops that section.
- Drop a section with no claims.
- Two sections with the same `document_id`: keep the first whose citation matches the catalog, and drop the later one. Do not concatenate them into a new claim.
- If no section remains, return not-in-corpus. Do not ask the model to repair the answer.

Render surviving sections in catalog order. Each claim group shows document name, publisher, year, and the official link.

Fixture checks:

- Two retrieved documents render two sections, in catalog order, with no claim that attributes one fact to both publishers.
- The egg pair renders two sections when both chunks are in the fixture. The salad pair keeps `3 to 4 days` and `3 to 5 days` on their own sections.
- A citation URL that is not the catalog URL is rejected.
- An empty retrieval names all seven catalog names, or the one filtered name, and does not call the model.

**Done when:** those fixtures pass.

## Phase 6 — Entry point

`src/app.py` is a stateless CLI. Each question is independent. There is no chat history. The CLI is the path `eval.md` will score. Phase 8's page calls the same function. It does not grow a second pipeline.

`answer_question(question)` runs the stages below and returns one result. The CLI prints that result. The page in Phase 8 displays that result. Fields:

| Field | Contents |
| --- | --- |
| `stage` | `out_of_scope`, `not_in_corpus`, or `answered` |
| `filter` | A `document_id`, or `all`. Omitted on `out_of_scope`, because retrieval did not run. |
| `chunk_ids` | Retrieved ids. Empty on `out_of_scope`. May be non-empty on `not_in_corpus` while the floor is `0.0`. |
| `message` | The refusal text. Empty when `stage` is `answered`. |
| `sections` | Validated sections in catalog order. Empty unless `stage` is `answered`. Each section has `document_id`, `claims`, and the catalog citation: `document_name`, `publisher`, `year`, `source_url`. |

An empty or whitespace question never calls `answer_question`. The CLI exits 2. That matches the `src.retrieve` CLI.

Then, with nothing allowed to skip a step:

1. `scope.py`. On `out_of_scope`, return the template and stop.
2. `retrieve.py`. Phrase detection only. There is no `document_id` argument on `answer_question`. Tests may still pass `document_id` into `retrieve()`.
3. Coverage gate.
4. `answer.py`, then `validate.py`.
5. Render either per-document sections or the not-in-corpus refusal.

The CLI prints each answered section as prose plus one citation line: document name, publisher, year, and the official link. It logs `stage`, the filter or `all`, and the chunk ids. An out-of-scope line has no chunk ids. That log is how you prove a weight question never retrieved, and a smoke-point question retrieved and then abstained.

`tests/test_app.py` uses a fake answer client for routing. It does not rebuild `data/index/`. It asserts the result fields above, not only the printed lines.

**Done when:** the eight questions in Phase 7 can be sent through this CLI, and the routing tests show `out_of_scope` with no chunk ids for the weight and calorie questions.

## Phase 7 — Acceptance and README

Run these through `app.py` and keep the outputs. Retrieval probes already scored in `eval.md` must still pass. A nearby chunk is not a pass when the required id or the required refusal is missing.

| Question | Pass |
| --- | --- |
| How long can raw eggs stay in the refrigerator? | `answered`, filter `all`, retrieved ids include `cold-food-storage:2:35`. That section cites FoodSafety.gov and gives the refrigerator time from that row (`3 to 5 weeks`). If `kitchen-companion:285:0` was also retrieved, a second section with the USDA citation is allowed. The two sections stay separate. The egg claim does not bring in ham, fish, or leftovers. |
| According to the Eatwell Guide, what does it say about oils? | Filter `eatwell-guide`. Every retrieved chunk is that document, at most 5. Only `eatwell-guide` is cited. |
| What do the guidelines say about fats and oils? | Filter `all`. The question names no single document. One section per nutrition document the chunks actually support. No merged "the guidelines say" claim. A food-safety section appears only when a retrieved chunk supports a storage or handling claim, and it stays its own section. |
| What is the smoke point of olive oil? | `not_in_corpus`. Names the seven documents searched. No smoke-point number. Retrieved ids may be non-empty while the floor is `0.0`. |
| How much protein is in 100 g of chicken? | `not_in_corpus`. Names the seven documents searched. The reply is not the medical, calorie, or weight template. |
| What should I weigh? | Out-of-scope template. The log shows no retrieval. |
| How many calories should I eat to lose 5 kg? | Out-of-scope template. The log shows no retrieval. |
| What share of energy intake does WHO recommend from fat? | `answered`, filter `all`. A cited population figure from a nutrition document, such as less than 30% of total energy or the Table 1 saturated-fat line when that chunk was retrieved. No personal calorie target. Two nutrition documents stay two sections. |

Then finish `README.md` with the chunking decision and what it cost: heading groups, a 500-token cap on the long sections only, one chunk per table row with headers and captions copied onto the row, one chunk per FAO Table 1 nutrient line, more chunks, and no whole-chart chunk. Record the similarity floor, the candidate pool of 32, and the caps of 8 kept chunks, at most 3 per document, and 5 in single-document search.

Update `eval.md` so the eight questions move out of "Not scored yet" and into the scored answer section, with the stage, filter, and citation checks from the table above. If `SIMILARITY_FLOOR` changes, update that constant in `eval.md` and the retrieval section of `edge-case.md`.

**Done when:** every row above passes, the README states the trade-off in enough detail that a reader can see why fixed-size chunking was not used, and `eval.md` scores these eight questions.

## Phase 8 — Local page

Add a browser page that asks one question and shows the `answer_question` result from Phase 6. The page is not scored by `eval.md`. Acceptance stays on the CLI.

`python -m src.app --serve` listens on localhost only. It serves `web/index.html` and accepts one question. The handler calls `answer_question` and returns that result as JSON. No other route retrieves, embeds, or calls the model. A request body that includes `document_id` does not change the filter. Phrase detection stays inside `answer_question`, the same rule as the CLI.

`web/index.html` is one file, with no build step and no extra framework. The page shows the latest question and its result, and it does not send earlier questions back.

| `stage` | What the page shows |
| --- | --- |
| `answered` | One block per section, in the order received. Claims, then document name, publisher, year, and a link whose href is that section's `source_url`. |
| `not_in_corpus` | `message` only. The catalog names inside it are text. They are not citation links, and `chunk_ids` are not shown as sources. |
| `out_of_scope` | `message` only. No link and no document name. |

An empty or whitespace question is rejected in the browser before the request, and the server returns an error without calling `answer_question` when one arrives anyway.

**Done when:** the eight Phase 7 questions can be submitted on the page, each result's `stage` matches the CLI for that question, an out-of-scope result has no link, and a second question does not include the first question in the request.

## Leave out of this plan

- Multi-turn memory and user profiles. The page in Phase 8 does not add them.
- PDF parsing, live browsing, and any document beyond the seven.
- A nutrient database. That is Milestone 3.
- A learned scope classifier, re-ranker, or query rewriter.
- Changes to ingest, chunking, or the name-detection phrases. Those are locked by `edge-case.md` and `eval.md`.
- A document picker, an account, or a chat transcript that is sent back to the server.

If a scope rule misses a phrase, add a case and a test in `scope.py`. Do not move that refusal into the prompt.
