# Verification record

Local implementation checks on 27 October 2026. No provider secrets were present in the project.

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
