# Evaluation

What is scored: catalog join, chunking, the vector index, retrieval, the scope guard, and the eight acceptance questions run through `src/app.py`.

Pass means every row in the automated suite passes, the retrieval probes below return the required chunk or filter, and each acceptance question matches the stage, filter, and citation check in Answers. A plausible nearby chunk is not a pass when the required id or the required refusal is missing.

## How to run

From the project root, with dependencies installed:

```bash
python -c "import src.ingest, src.chunk, src.index_corpus, src.scope, src.retrieve, src.answer, src.validate, src.app"
python -m unittest discover -s tests -v
```

`tests/test_imports.py` is the import check above. `unittest` does not collect that module-level function.

`tests/test_retrieve.py` rebuilds the `guidance` collection from `data/chunks.jsonl` before the live searches. Run it only when replacing `data/index/` is acceptable.

Ingest and chunk unit tests do not download the block file and do not load the embedding model. Corpus chunk tests read `data/blocks.jsonl` and `data/catalog.json` already on disk.

## Snapshot the suite locks

| Check | Pass |
| --- | --- |
| Catalog | Seven documents. Each row has `document_id`, `document_name`, `publisher`, `year`, `source_url`, `retrieval_date` `2026-10-05`, and `kind`. |
| Blocks | Every block id is in the catalog, and every catalog id appears at least once. |
| Chunks | 339 lines in `data/chunks.jsonl`. |
| Index | Collection `guidance`, cosine space, 339 vectors, 384 dimensions, model `all-MiniLM-L6-v2`. |
| Similarity floor | `SIMILARITY_FLOOR` is `0.0`. Similarity is `1 - cosine distance`. |

Chunk counts:

| `document_id` | Chunks | Prose | Table rows | FAO Table 1 lines |
| --- | --- | --- | --- | --- |
| `kitchen-companion` | 174 | 101 | 73 | 0 |
| `cold-food-storage` | 54 | 1 | 53 | 0 |
| `eatwell-guide` | 43 | 23 | 20 | 0 |
| `who-five-keys` | 27 | 27 | 0 | 0 |
| `fao-who-healthy-diets` | 24 | 17 | 0 | 7 |
| `who-healthy-diet` | 12 | 12 | 0 | 0 |
| `fsa-chill` | 5 | 5 | 0 | 0 |
| Total | 339 | 186 | 146 | 7 |

## Ingest

Scored by `tests/test_ingest.py` against the join rules in `src/ingest.py`. These cases use a small fixture catalog. They do not call the network.

| Case | Pass |
| --- | --- |
| Block id not in the catalog | `IngestError` whose message contains `unknown document_id: not-a-document`. No blocks written. |
| A catalog id never appears | `IngestError` naming that id. |
| Page furniture | The paragraph that is only `N What are healthy diets? Joint statement by the Food and Agriculture Organization of the United Nations and the World Health Organization` is dropped. A paragraph that continues past that title is kept. A heading that repeats a title is kept. |
| Order | Kept blocks are sorted by `document_id`, then `ordinal`. |
| Count drift | A raw count that differs from the expected snapshot is a warning, not a failure. The expected raw counts are `cold-food-storage` 3, `who-healthy-diet` 92, `fao-who-healthy-diets` 98, `who-five-keys` 174, `eatwell-guide` 120, `fsa-chill` 45, `kitchen-companion` 469. |

A download error is a fail of `python -m src.ingest` (exit code 1) and must leave the previous `data/blocks.jsonl` in place. The unit suite does not cover the network.

## Chunking

Scored by `tests/test_chunk.py`.

| Case | Pass |
| --- | --- |
| Headings | A heading emits no chunk. Two sections do not share a chunk. |
| Long paragraph | One block over the token cap stays one chunk. The text is not a fixed-size character window. |
| Mid-list split | When a list is flushed for the 500-token cap, every following chunk still contains the introducing paragraph. That paragraph's ordinal is only on the first chunk. |
| Empty cell | The country-ham style row keeps `Time:` empty. It does not copy the time from the row above. |
| Two tables, one heading | `chunk_id` uses the table ordinal. A caption is copied onto every row of that table and not onto the next table. The markdown chart in `text` is not the chunk body. |
| Raw eggs | `cold-food-storage:2:35` contains `Raw eggs in shell`, `3 to 5 weeks`, and `Refrigerator [40°F (4°C) or below]`. It does not contain ham, fish, leftovers, or a markdown separator. |
| FAO Table 1 | `fao-who-healthy-diets:23:0` is source `fao_table1`, ordinals `[23]`, and contains `Saturated 10% or less`, `proportion of dietary energy intake`, and `Adults`. It does not contain the protein essay. The seven lines are `fao-who-healthy-diets:23:0` through `fao-who-healthy-diets:29:0`. |
| Oils | The prose section ending in `A closer look at Oils and spreads` and the table row `eatwell-guide:105:4` are different chunks. The table row does not contain the prose sentence `Although some fat in the diet is essential`. |
| Turkey caption | Every `kitchen-companion` row from ordinal 252 contains `325 °F` and `165 °F`. |
| Country ham | `kitchen-companion:216:10` contains `Country` and an empty `Timing (Approximate):`. It does not contain `10 to 18 minutes per lb.`. The ordinal-216 rows do not contain `Beef`. |
| Citation fields | Every chunk has a non-empty `section_heading`, and `document_name`, `publisher`, `year`, and `source_url` equal that document's catalog row. `embed_text` is the section heading, a newline, then `text`. |
| List fragments | A list item under a heading that has an introducing paragraph includes that paragraph. Each block ordinal has exactly one owning chunk. FAO Table 1 lines are the exception to the lead-in rule. |
| WHO fats | `who-healthy-diet` has one chunk whose section ends in `Fats`. It contains both `less than 30% of total energy` and `reducing saturated fats to less than 10% of total energy intake`, and it is under `TOKEN_LIMIT`. |

## Index

Scored by `LiveIndexTests` in `tests/test_retrieve.py`.

| Case | Pass |
| --- | --- |
| Rebuild | `build_index` returns 339, `collection.count()` is 339, and metadata `hnsw:space` is `cosine`. |
| Duplicate text, two ids | `kitchen-companion:215:0` and `kitchen-companion:217:0` are both stored. |
| Full row text | `cold-food-storage:2:35` and `kitchen-companion:285:0` each contain `3 to 5 weeks`. `eatwell-guide:105:4` is stored. |
| Missing chunk file, bad JSON, duplicate `chunk_id`, or a missing metadata field | `IndexBuildError` and exit code 1. These paths are implemented in `src/index_corpus.py` and are not covered by the current unit tests. |

The vector is the embedding of `embed_text`. The stored document is the full `text`, including the tail past the model's 256-token window. A pass does not require the truncated tail to be inside the vector.

## Retrieval

Rule checks in `tests/test_retrieve.py` do not load the model. Live checks do.

Phase 7 left these values unchanged. The eight acceptance questions passed at this floor.

| Constant | Value |
| --- | --- |
| `SIMILARITY_FLOOR` | `0.0` |
| `CANDIDATE_POOL` | 32 |
| `MAX_CHUNKS` | 8 |
| `MAX_PER_DOCUMENT` | 3 |
| `SINGLE_DOCUMENT_K` | 5 |

| Case | Pass |
| --- | --- |
| Distance | `similarity_from_distance(0.25)` is `0.75`. |
| Floor | A chunk with similarity `-0.1` is dropped before the cap. A later chunk at `0.4` is kept. |
| Per-document cap | Ten `kitchen-companion` hits followed by `cold-food-storage:2:35` keep 3 kitchen-companion chunks and still keep the egg row. The kept list is at most 8. |
| Empty question | `RetrieveError`. The CLI with no argument exits 2. |
| Missing collection | `RetrieveError` that tells you to run `python -m src.index_corpus`. |

### Name detection

One matched id filters search. Zero or two or more matched ids leave it unfiltered. An explicit `document_id` argument wins over the question text.

| Question | Filter |
| --- | --- |
| According to the Eatwell Guide, what does it say about oils? | `eatwell-guide` |
| Five Keys to safer food | `who-five-keys` |
| What are healthy diets? | `fao-who-healthy-diets` |
| the healthy diet fact sheet | `who-healthy-diet` |
| What is a healthy diet? | Unfiltered. Matched ids are `who-healthy-diet` and `fao-who-healthy-diets`. |
| What do the Eatwell Guide and the Kitchen Companion say about oil? | Unfiltered |
| What share of energy does WHO recommend from fat? | Unfiltered. A bare WHO matches no id. |
| How long for eggs? with `document_id="cold-food-storage"` | `cold-food-storage`, even though the question names no document |

### Live probes

Run against the rebuilt index. Every hit must have similarity `>= 0.0`. Retrieval must not call a chat model.

| Probe | Pass |
| --- | --- |
| How long can raw eggs stay in the refrigerator? | Kept chunks include `cold-food-storage:2:35`. That hit's text contains `3 to 5 weeks` and `Refrigerator`, and its `source_url` contains `foodsafety.gov`. At most 8 chunks, at most 3 from any one document. `kitchen-companion:285:0` may also appear. It is a separate hit, not a substitute for the FoodSafety.gov row. |
| According to the Eatwell Guide, what does it say about oils? | Every hit is `eatwell-guide`. Length is 1 to 5. The set includes `eatwell-guide:105:4` or a chunk whose section heading ends with `A closer look at Oils and spreads`. |
| What do the Eatwell Guide and the Kitchen Companion say about fats? | Returns at least one chunk. `resolve_document_filter` is `None`. |
| What share of energy intake does WHO recommend from fat? | Returns at least one chunk. `resolve_document_filter` is `None`. |

CLI check:

```bash
python -m src.retrieve "How long can raw eggs stay in the refrigerator?"
```

The first line is `filter=all` and a kept count. `cold-food-storage:2:35` appears in the lines below it.

## Scope

Scored by `tests/test_scope.py`. Rules live in `src/scope.py`. The chat model is not called. Each out-of-scope case asserts that the retrieve function passed into `screen` is not called, and that the reply is the fixed template: a decline, a pointer to a qualified professional, no `http` link, and no document name.

| Question | Pass |
| --- | --- |
| I have diabetes. What diet should I follow? | `out_of_scope`. Retrieve is not called. |
| How many calories should I eat to lose 5 kg? | `out_of_scope`. Retrieve is not called. |
| What should I weigh? | `out_of_scope`. Retrieve is not called. |
| Using the WHO fat limit, how many calories should I eat? | `out_of_scope`. Naming a guideline does not let it through. |
| According to the Eatwell Guide, how many calories should I eat? | `out_of_scope`. Naming a document does not let it through. |
| What share of energy intake does WHO recommend from fat? | `in_scope_population_guidance`. Retrieve is called. |
| What calorie figures does the Eatwell Guide publish? | `in_scope_population_guidance`. Retrieve is called. |
| How long can raw eggs stay in the refrigerator? | `in_scope`. Retrieve is called. |
| How much protein is in 100 g of chicken? | `in_scope`. This is not the medical, calorie, or weight template. |

The CLI log for the weight and calorie questions is scored in Answers.

## Answers

Scored by running each question through `answer_question` in `src/app.py` and printing it with `format_result`, the same text `python -m src.app` prints. The chat model was `openai/gpt-oss-120b`. `SIMILARITY_FLOOR` stayed `0.0`. Retrieved ids on a `not_in_corpus` answer may be non-empty at that floor.

| Question | Pass |
| --- | --- |
| How long can raw eggs stay in the refrigerator? | `answered`, filter `all`. Retrieved ids include `cold-food-storage:2:35` and `kitchen-companion:285:0`. The Cold Food Storage Chart section cites FoodSafety.gov and says raw eggs in shell keep for 3 to 5 weeks. The Kitchen Companion section cites USDA and states the same refrigerator time. The two sections stay separate. Neither claim mentions ham, fish, or leftovers. |
| According to the Eatwell Guide, what does it say about oils? | `answered`, filter `eatwell-guide`. Five retrieved chunks, every one `eatwell-guide`, including `eatwell-guide:105:4`. The only cited document is The Eatwell Guide booklet. |
| What do the guidelines say about fats and oils? | `answered`, filter `all`. The question names no single document. Three sections, in catalog order: Healthy diet (Fact sheet), What are healthy diets? Joint statement, and The Eatwell Guide booklet. No merged "the guidelines say" claim. No food-safety section. The retrieved chunks are all from those three nutrition documents. |
| What is the smoke point of olive oil? | `not_in_corpus`, filter `all`. The message names all seven catalog documents. It contains no smoke-point number. Retrieved ids are non-empty. |
| How much protein is in 100 g of chicken? | `not_in_corpus`, filter `all`. The message names all seven catalog documents. It is not the medical, calorie, or weight template. Retrieved ids are non-empty. |
| What should I weigh? | `stage=out_of_scope`. The log has no `chunks=` field and `chunk_ids` is empty. The message is the fixed decline and points to a qualified professional. |
| How many calories should I eat to lose 5 kg? | Same out-of-scope log and template as the weight question. |
| What share of energy intake does WHO recommend from fat? | `answered`, filter `all`. Two sections: the WHO fact sheet cites less than 30% of total energy intake, and the FAO/WHO joint statement cites a population fat range. No personal calorie target. Eatwell chunks were retrieved and were not given a section. |

CLI log and reply for each question:

```text
stage=answered	filter=all	chunks=kitchen-companion:285:0,kitchen-companion:285:1,kitchen-companion:285:2,cold-food-storage:2:35,cold-food-storage:2:36,cold-food-storage:2:44,fsa-chill:37:0
Raw eggs in shell can be stored in the refrigerator for 3 to 5 weeks.
Cold Food Storage Chart, FoodSafety.gov (U.S. Department of Health and Human Services / FDA / USDA), 2023, https://www.foodsafety.gov/food-safety-charts/cold-food-storage-charts

Raw eggs in shell can be stored in the refrigerator for 3 to 5 weeks.
Kitchen Companion: Your Safe Food Handbook, USDA Food Safety and Inspection Service, 2008, https://www.fsis.usda.gov/sites/default/files/media_file/2020-12/Kitchen-Companion.pdf
```

```text
stage=answered	filter=eatwell-guide	chunks=eatwell-guide:4:0,eatwell-guide:48:0,eatwell-guide:105:4,eatwell-guide:22:0,eatwell-guide:1:0
Choose unsaturated oils and spreads and eat them in small amounts. Unsaturated oils such as vegetable, rapeseed and olive oil are healthier and swapping to them helps reduce blood cholesterol. Use oils sparingly because they are high in fat and calories; choose lower-fat spreads, check labels for high unsaturated and low saturated fat, and use oil sparingly when cooking. Unsaturated fats from plant sources (e.g., vegetable or olive oil) are healthier, but all types of fat are high in energy and should be eaten in small amounts.
The Eatwell Guide booklet, Public Health England (now Office for Health Improvement and Disparities), 2018, https://assets.publishing.service.gov.uk/media/5ba8a50540f0b605084c9501/Eatwell_Guide_booklet_2018v4.pdf
```

```text
stage=answered	filter=all	chunks=eatwell-guide:105:4,eatwell-guide:48:0,fao-who-healthy-diets:18:0,fao-who-healthy-diets:41:0,fao-who-healthy-diets:64:0,who-healthy-diet:3:0,who-healthy-diet:35:0,eatwell-guide:22:0
Total fat should not exceed 30% of total energy intake. Saturated fat should be less than 10% of total energy intake. Trans-fat should be less than 1% of total energy intake. Fat consumption should shift away from saturated and trans-fats toward unsaturated fats, especially polyunsaturated fats. Practical ways to reduce saturated and trans-fat intake include using oils rich in polyunsaturated fats (e.g., soybean, rapeseed, corn, safflower, sunflower) instead of butter, lard or ghee, and choosing steaming or boiling over frying.
Healthy diet (Fact sheet), World Health Organization, 2018, https://www.who.int/docs/default-source/healthy-diet/healthy-diet-fact-sheet-394.pdf

Adults should obtain 15-30% of daily calories from fat. Limiting fat intake to 30% of calories or less can help reduce the risk of unhealthy weight gain. Fat should be primarily unsaturated; 6-10% of total energy should come from polyunsaturated fats (including linoleic and alpha-linolenic acids). Monounsaturated fats from plant sources should make up the remainder of fat intake after accounting for polyunsaturated, saturated and trans-fat.
What are healthy diets? Joint statement, Food and Agriculture Organization of the United Nations and World Health Organization, 2024, https://www.who.int/publications/i/item/9789240101876

Unsaturated oils such as vegetable, rapeseed, olive and sunflower oil should be chosen and used sparingly because all fats are high in energy. Lower-fat spreads should be chosen instead of butter, and spreads should be used in small amounts. Labels should be checked to select oils high in unsaturated fat and low in saturated fat. All types of fat should be limited in the diet, with a focus on unsaturated fats from plant sources.
The Eatwell Guide booklet, Public Health England (now Office for Health Improvement and Disparities), 2018, https://assets.publishing.service.gov.uk/media/5ba8a50540f0b605084c9501/Eatwell_Guide_booklet_2018v4.pdf
```

```text
stage=not_in_corpus	filter=all	chunks=kitchen-companion:351:0,eatwell-guide:48:0,kitchen-companion:59:0,eatwell-guide:105:4,kitchen-companion:254:2,eatwell-guide:22:0,who-healthy-diet:35:0,who-five-keys:7:0
The guidance does not cover this question. Documents searched: Cold Food Storage Chart; Healthy diet (Fact sheet); What are healthy diets? Joint statement; Five keys to safer food manual; The Eatwell Guide booklet; How to chill, freeze and defrost food safely; Kitchen Companion: Your Safe Food Handbook.
```

```text
stage=not_in_corpus	filter=all	chunks=eatwell-guide:105:3,eatwell-guide:43:0,kitchen-companion:266:0,cold-food-storage:2:23,eatwell-guide:81:8,kitchen-companion:59:0,cold-food-storage:2:24,cold-food-storage:2:9
The guidance does not cover this question. Documents searched: Cold Food Storage Chart; Healthy diet (Fact sheet); What are healthy diets? Joint statement; Five keys to safer food manual; The Eatwell Guide booklet; How to chill, freeze and defrost food safely; Kitchen Companion: Your Safe Food Handbook.
```

```text
stage=out_of_scope
This assistant does not give medical advice, personal calorie targets, or weight targets. Please speak with a qualified professional.
```

The calorie question prints that same out-of-scope log and message.

```text
stage=answered	filter=all	chunks=fao-who-healthy-diets:41:0,who-healthy-diet:3:0,who-healthy-diet:14:0,who-healthy-diet:35:0,fao-who-healthy-diets:21:0,fao-who-healthy-diets:69:0,eatwell-guide:79:0,eatwell-guide:53:0
WHO recommends that total fat should not exceed 30% of total energy intake.
Healthy diet (Fact sheet), World Health Organization, 2018, https://www.who.int/docs/default-source/healthy-diet/healthy-diet-fact-sheet-394.pdf

WHO recommends that adults limit total fat intake to 30% of total energy intake or less (conditional recommendation). A minimum of 15-30% of calories consumed per day should be from fat.
What are healthy diets? Joint statement, Food and Agriculture Organization of the United Nations and World Health Organization, 2024, https://www.who.int/publications/i/item/9789240101876
```
