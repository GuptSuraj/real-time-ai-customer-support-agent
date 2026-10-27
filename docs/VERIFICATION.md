# Verification record

Initial implementation checks on 27 October 2026. No provider secrets were present at that initial checkpoint. Current hybrid RAG checks are recorded below.

| Check | Result |
| --- | --- |
| Python API and bounded-client tests | 32 passed |
| PostgreSQL row-lock contention test | Skipped locally; `POSTGRES_TEST_URL` unavailable. Included in PostgreSQL-backed CI |
| Chromium browser flows | 4 passed: customer confirmation, staff approval/CRM, escalation claim/join, mobile layout |
| Frontend TypeScript | Passed |
| Next.js production build | Passed |
| Initial Alembic migration, seed, schema comparison | Passed on temporary SQLite database; no pending model changes |
| Unmodified API smoke | Passed: startup, login, owned-order lookup and explicit missing-provider 503 |
| Installed LiveKit SDK compatibility | Version 1.8.9 imported; exact Gemini configuration and six tool definitions constructed successfully |
| Evaluation manifest | 50 unique scenarios validated, 61 audio input turns specified |
| Credential preflight | Not configured: LiveKit URL/key/secret and Google API key missing |
| Real Gemini audio scenarios | Not run |
| Actual media takeover / Hindi / barge-in | Not verified against provider |
| Five simultaneous LiveKit calls | Harness implemented, not run against cloud |
| P95 latency, task completion, tool accuracy and handoff correctness | Unmeasured; evaluation report leaves missing results null |
| Docker Compose and PostgreSQL runtime | Prepared, not executed on this host; Docker/PostgreSQL executables unavailable |
| Langfuse/OTLP export | Configured in code; external delivery not verified |

The browser suite substitutes only test dispatch/media credentials in `scripts/e2e_server.py`. Customer/staff operations still use the real API, auth, verification, business rules, transactions and database. No test bypass is imported by the production API or worker. These tests do not certify voice behavior.

The PostgreSQL test creates a unique schema in a disposable database, runs concurrent confirmations, and checks that exactly one ticket is committed. SQLite tests check ownership and state boundaries but do not prove PostgreSQL locking behavior.

Generated screenshots: [customer portal](images/customer-portal.png), [mobile portal](images/mobile-portal.png).

To finish external verification: configure `.env`, run `scripts/preflight.py`, start the real stack, follow `docs/DEMO.md`, run the isolated audio evaluation suite and five-call check, review the results, and produce the report. Do not claim the target performance thresholds until those results exist.


## Hybrid RAG verification — 27 October 2026

- **71 Python tests passed**, including the original workflows, real PostgreSQL contention and 11 pgvector/full-text integration tests. No PostgreSQL tests were skipped in this run.
- **Four browser tests passed** for customer verification/confirmation, staff approval/CRM, escalation claim/join, and mobile layout. TypeScript and the Next.js production build passed.
- Reviewed **33 English documents**, corrected policy contradictions, and indexed **96 chunks** using actual `gemini-embedding-2` vectors at **768 dimensions** in an isolated database.
- The live **63-case** relevance/latency suite passed: Hit@5 and Recall@5 1.0, MRR 0.9722, P95 retrieval 1,031.89 ms, all three unrelated questions abstained. The separate **12-case holdout** also passed, including all six unrelated questions. See [the measured report](retrieval-verification.json) for per-language results and benchmark limitations.
- Exercised the **actual worker HTTP client → authenticated FastAPI endpoint → Google embeddings → PostgreSQL/pgvector** path in English, Hindi and Hinglish. End-to-end HTTP samples were 0.944 s, 0.806 s and 0.825 s respectively; these three samples are not a P95 estimate.
- Langfuse Observations API v2 returned HTTP 200 and a visible `rag.retrieve` observation of type `RETRIEVER`. New API tests verify question text is redacted from trace URL attributes.
- Built the API image and the PostgreSQL 17 Alpine + pgvector 0.8.7 image. Tested an **in-place upgrade of a temporary old Alpine database volume**, preserving eight orders and four policies, then successfully applied migration `0002` and compared the schema.
- PostgreSQL and SQLite migration/schema checks passed. The packaged API's policy audit and PostgreSQL schema check passed.
- The original application and its database volume were left stopped and unchanged; all live indexing/evaluations used isolated test data. Rebuild/start and run the one-off indexing command in [the knowledge guide](KNOWLEDGE_BASE.md) to enable RAG on the application's database.

These checks validate retrieval and existing application regressions. They do not certify full live voice quality, human media takeover, spoken conversation completion rates, or speech-response P95. The original 50 audio conversation scenarios remain separate.
