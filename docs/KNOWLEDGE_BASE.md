# Hybrid knowledge retrieval

Mira's existing `search_store_knowledge` tool now calls the same authenticated `GET /internal/knowledge?q=...` endpoint, backed by API-owned hybrid RAG. Documents, embeddings, SQL retrieval, fusion and evaluation all live under `services/api/`. The voice worker has no vector database connection or ingestion logic.

## Enable it for your application

Your environment uses:

```env
EMBEDDING_MODEL=gemini-embedding-2
EMBEDDING_DIMENSION=768
```

The existing `GOOGLE_API_KEY` supplies embedding credentials. The voice model configuration is independent. Neither the model nor the embedding space is silently substituted. The dimension is validated against the fixed `vector(768)` migration; changing it requires a deliberate schema/pipeline change and full reindex.

From the project root:

```sh
# Build the updated database/API/worker images and run migrations without deleting saved data.
docker compose up -d --build

# Index the reviewed root knowledge_base/ directory; no worker or browser changes are needed.
docker compose --profile knowledge run --build --rm --no-deps index-knowledge
```

The database image extends the **original PostgreSQL 17 Alpine image** with pinned pgvector 0.8.7. It preserves the same named `postgres_data` volume and database base family. Migration `0002` adds the extension and knowledge tables/indexes without dropping commerce data. A temporary old-image-to-new-image volume upgrade was tested with all eight seeded orders and four saved policies preserved. Normal backup practices still apply; no reset or volume deletion is required for this upgrade.

Before indexing, read [the reconciliation report](POLICY_RECONCILIATION.md). The index command checks it automatically. To inspect the gate separately:

```sh
PYTHONPATH=services/api uv run python -m support_api.knowledge audit
```

For native operation, install pgvector on the PostgreSQL server, apply migrations, then run:

```sh
uv run alembic -c services/api/alembic.ini upgrade head
PYTHONPATH=services/api uv run python -m support_api.knowledge index
```

SQLite still supports the existing portal/tests and returns an explicit legacy fallback. It is not a pgvector/full-text backend.

## Ingestion and updates

- Discover UTF-8 `.txt` files under `policies/`, `faqs/`, and `product_guides/`. Validate Title, Document ID, Language, Version, source bounds, file size, duplicate IDs and symlinks. Ignore non-text files.
- Check the corpus and backend rule fingerprints before calling Google.
- Split by document section or FAQ question, with a 220-word maximum and 32-word overlap for long sections. Keep document ID, title, section, relative source path, version and checksums.
- Generate one 768-dimensional Embedding 2 vector **per chunk**, using explicit document formatting and separate `Content` objects. Validate counts, dimensions, finite values and normalization.
- Reuse unchanged chunk embeddings only when model, dimension and pipeline version match. An unchanged corpus is a no-op.
- Stage the complete generation, then publish it in one transaction protected by a PostgreSQL advisory lock. Exactly one generation is active. Provider/SQL failure never publishes a partial corpus.
- Removed files disappear from the next active generation. Retired generations remain stored for provenance and in-flight reads; there is no automatic pruning or retention claim.

After changing documents, compare every policy claim with the current handlers. Then explicitly record the completed source review and reindex:

```sh
PYTHONPATH=services/api uv run python -m support_api.knowledge review --approve-reviewed
PYTHONPATH=services/api uv run python -m support_api.knowledge index
```

The review manifest is source-controlled and copied into the API image. After recording a review locally, rebuild the container images before container indexing so they contain that review. The index service mounts root documents read-only; the review command should run in the source checkout.

## Retrieval

1. Authenticate the worker's existing call-scoped credential; ended or human-controlled calls cannot invoke the tool.
2. Embed the caller's original English, Hindi or Hinglish question with Embedding 2's search-query instruction. The English documents are not translated. A small Hindi/Hinglish vocabulary adds lexical search anchors; it is not a general translation system.
3. Query pgvector cosine distance with an HNSW index. Independently run weighted PostgreSQL English full-text search using `websearch_to_tsquery`, `ts_rank_cd` and a GIN index. Title/section weights are higher than body weights. The lexical query is parameterized, never interpolated SQL.
4. Fuse candidate ranks with **RRF**, `score = sum(1 / (60 + rank))`. Rank scores are not probabilities. Defaults are 24 candidates per leg and five returned chunks.
5. Deduplicate content, cap each source document at two chunks, and bound context to 7,000 characters. When semantic retrieval succeeds, both candidate lists apply the configured cosine relevance floor (default 0.60), so a keyword homonym cannot override a semantic no-match.
6. Return ranked source references, snippets, ranks, similarities, RRF scores, current catalog facts and the authoritative backend policy contract. The legacy `policies`/`products` response keys remain available. Omitting the query preserves the former saved-policy/catalog browse behavior without making an embedding request; an explicitly blank question is rejected.

Mira answers in the caller's language, treats sources as reference data rather than instructions, and can mention a source title. It does not read paths aloud. Empty/irrelevant sources require an honest no-answer/support response. Retrieved text cannot change eligibility, confirmation, refund authority or live inventory/order facts.

## Failure and latency behavior

- Embedding requests have a 1.5-second timeout and no hidden SDK retries.
- SQL retrieval legs have a 700-ms statement timeout and savepoints so one failing leg does not poison the session.
- Embedding/model mismatch or provider failure produces explicit `lexical_only` degradation; vector-only results are marked `semantic_only` if full-text fails.
- An unindexed installation returns explicit `legacy` degradation using existing saved policies. Backend-rule drift returns no indexed policy answer. Failures never become fabricated successful hybrid results.
- The worker's existing five-second total backend deadline and safe read retries are preserved.

## Langfuse and metrics

Existing Langfuse configuration receives `rag.retrieve`, `rag.embed_query`, `rag.vector_search`, `rag.full_text_search`, `rag.rrf` and `rag.ingest` OpenTelemetry spans. Retrieval observations are typed `RETRIEVER`. The exporter sends Langfuse's current v4 ingestion header.

Spans include model, mode, result count, timings and call correlation; RAG spans omit raw questions/source text and the API/worker redact the knowledge question from trace URLs/span names. Existing authenticated calls also persist `retrieval_latency_seconds` and per-stage timing metrics for the support analytics page.

Delivery was checked using Langfuse Observations API v2: `rag.retrieve` observations were visible. In the dashboard, filter observations by `rag.retrieve`, then inspect the embedding, SQL and fusion child spans. This measures retrieval latency, not full speech-response latency.

## Evaluation and tests

```sh
# Check evaluation definitions without external calls.
PYTHONPATH=services/api uv run python -m support_api.knowledge.evaluate --check

# Actual Google + PostgreSQL retrieval; use a separately indexed evaluation database.
PYTHONPATH=services/api uv run python -m support_api.knowledge.evaluate --require-targets
PYTHONPATH=services/api uv run python -m support_api.knowledge.evaluate \
  --cases services/api/evaluations/retrieval_holdout.json \
  --output evaluations/results/retrieval-holdout.json --require-targets

# Fast tests plus real SQL/pgvector tests when an isolated PostgreSQL URL is supplied.
POSTGRES_TEST_URL=postgresql+psycopg://user:password@localhost:5432/support_test uv run pytest -q
```

The 63-case suite covers 20 support topics in all three languages plus three unrelated questions. A separate 12-case holdout covers two further policy topics and six unrelated questions. Evaluation measures document-level Hit@k, Recall@k, MRR, nDCG, abstention and retrieval P50/P95. Duplicate chunks do not double-count a relevant document. The output records degraded/error runs rather than passing on fallback.

See [retrieval-verification.json](retrieval-verification.json) for the measured run summary. The 63-case suite was used to calibrate the 0.60 relevance floor; the holdout was run afterward. These are small synthetic benchmarks, not an open-domain or voice-quality guarantee. The original 50 spoken conversation scenarios remain separate.

Official references: [Gemini Embedding 2 task formatting and aggregation](https://ai.google.dev/gemini-api/docs/embeddings), [pgvector indexes and hybrid search](https://github.com/pgvector/pgvector), [PostgreSQL full-text controls](https://www.postgresql.org/docs/17/textsearch-controls.html), [Langfuse Observations API](https://langfuse.com/docs/api-and-data-platform/features/observations-api).
