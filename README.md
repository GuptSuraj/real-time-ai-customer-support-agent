# Real-Time AI Customer Support Agent

A working e-commerce support application with a customer portal, a support workspace, and a Python voice agent powered by **LiveKit + Gemini `gemini-3.1-flash-live-preview`**. The demo store is branded Northstar.

Customers can discuss orders, product information, returns, refunds and tickets in English or Hindi. The agent reads actual backend records. Customers verify and confirm exact proposed actions in the portal; refunds always require a staff decision. A representative can take over the same LiveKit room from the support workspace.

## Run with Docker

Requirements: Docker Compose, a LiveKit Cloud project, and a Google API key with access to the selected Live model.

```sh
cp .env.example .env
```

Edit `.env`:

- Set a random `SESSION_SECRET` of at least 32 characters.
- Set `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` from your existing LiveKit Cloud project.
- Set `GOOGLE_API_KEY`. The Google plugin connects directly to Google; it does not use LiveKit Inference billing.
- Keep `GEMINI_MODEL=gemini-3.1-flash-live-preview` unless you explicitly choose another supported model.

```sh
docker compose up --build
```

Open **http://localhost:3000**. Database migrations and idempotent demo seeding run before the API starts. API documentation: http://localhost:8000/docs. The worker registers under `commerce-support`; the API dispatches it explicitly for each call.

No credentials are included in this repository. If voice is unconfigured, the portal still works and reports the missing LiveKit configuration when a call is requested.

## Demo accounts

All seeded accounts use `Demo-support-2026!`.

| Account | Role |
| --- | --- |
| `aarav@example.com` | Customer with the full order/refund fixture set |
| `meera@example.com` | Separate customer for ownership tests and Hindi conversations |
| `support@example.com` | Support representative |
| `support2@example.com` | Second representative for claim contention |
| `sim1@example.com`, `sim2@example.com`, `sim3@example.com` | Additional customers for five-call load checks |

Sign in to customer and staff accounts in **different browser profiles or an incognito window**, so they do not share a session cookie.

## Run without Docker

Requirements: Python 3.12, `uv`, Node 22, pnpm 10.28.2, and PostgreSQL. Run all commands from the repository root.

```sh
uv sync --frozen
pnpm --dir apps/web install --frozen-lockfile
cp .env.example .env
# Configure .env, including DATABASE_URL and provider credentials.
uv run alembic -c services/api/alembic.ini upgrade head
PYTHONPATH=services/api uv run python -m support_api.seed
```

Start these in separate terminals:

```sh
# API
PYTHONPATH=services/api uv run uvicorn support_api.main:app --host 127.0.0.1 --port 8000

# Voice worker
PYTHONPATH=services/api:services/agent uv run python -m support_agent.worker dev

# Customer and staff UI
pnpm --dir apps/web dev
```

Use http://localhost:3000 to match `APP_ORIGIN`. If you use a different hostname or port, update `APP_ORIGIN` and restart the API.

For a quick portal-only exploration, set `DATABASE_URL=sqlite:///./support.db` in `.env`, then migrate and seed. SQLite is supported for local exploration and fast tests; PostgreSQL is required for concurrent row-lock guarantees.

## Demonstrate the product

See [the demo script](docs/DEMO.md).

- `ORD-1001`: headphones returned five days ago; refund processing. Ask Mira to check it and prepare a ticket.
- `ORD-1003`: delivered, returnable, within 30 days. Prepare a return, verify, and confirm it.
- `ORD-1007`: return received, no refund yet. Prepare and confirm a refund request, then approve it in the staff workspace.
- `ORD-1004`: outside the return window; `ORD-1005`: non-returnable earbuds.
- `ORD-1006`: simulated failed refund; `ORD-2001`: another customer's order, inaccessible to Aarav.

Refund approval changes `pending_approval` to `approved`. The demo processor moves it to `processing` and then `completed`; no payment provider is contacted. The pre-seeded processing refund remains pending so the five-day-delay example stays reproducible.

## How confirmation and takeover work

1. The customer signs in. The API derives ownership from the session, not from a model-supplied customer ID.
2. The agent prepares an action with immutable details and a five-minute expiry. Preparing another action supersedes the previous proposal.
3. The customer completes the two-minute on-screen demo challenge, then clicks **Confirm this action**. Verification authorizes one action. A spoken “yes” alone cannot execute anything.
4. The backend rechecks ownership, eligibility and call state, then commits once. Retrying the same confirmation returns its existing result.
5. Refunds are requests until a staff representative approves or rejects them with a reason.

For human takeover, the staff representative claims the escalation atomically and publishes a silent microphone track. The worker observes the assigned participant's audio track, disables AI input/output, acknowledges takeover, and loses its tool credentials. The representative's microphone opens only after this acknowledgment. The room stays the same. After 60 seconds without takeover, the AI offers a confirmed callback ticket. A disconnected representative can reconnect; the AI does not automatically resume.

The on-screen challenge is a **demo step-up interaction**, not an SMS/email second factor. Real identity verification and real payments are outside this delivery.

## Webhooks and local operation

The worker observes room media and disconnect events directly, so local browser takeover does not require an internet-facing API. For a second source of lifecycle events, configure signed LiveKit webhooks to `https://<reachable-api>/webhooks/livekit` for `track_published`, `participant_left`, and `room_finished`. Use the same LiveKit project credentials as the API. Webhook bodies are signature-verified and event IDs are deduplicated. A local API needs a tunnel if LiveKit Cloud is to reach this route.

Customer hangup cancels pending escalation/action work. A worker startup failure is reported to the API; calls stuck connecting expire after two minutes. Original worker credentials can report lifecycle/transcript events after takeover but cannot read customer context or invoke business tools.

## Verification

```sh
uv run pytest -q
pnpm --dir apps/web typecheck
pnpm --dir apps/web build
pnpm --dir apps/web exec playwright install chromium
pnpm --dir apps/web test:e2e
```

Browser tests start a disposable test-only API with mocked dispatch, and use a separate SQLite database under `/tmp`. They verify login, verification, confirmation, staff decisions, escalation claim/join, and responsive layouts. **They do not verify real media or Gemini responses.** The production entrypoint never loads that test API.

The optional PostgreSQL contention test runs automatically in CI, or locally with a disposable database:

```sh
POSTGRES_TEST_URL=postgresql+psycopg://support:support@localhost:5432/support_test uv run pytest services/api/tests/test_postgres.py -q
```

It creates and removes its own isolated schema. Migrations can be checked with `uv run alembic -c services/api/alembic.ini check`.

To regenerate API types:

```sh
make types
```

## Real audio evaluation

See [the evaluation guide](evaluations/README.md). There are **50 distinct scripted scenarios**, including Hindi, interruption, human takeover, backend faults, identity misuse and duplicate confirmation. The runner publishes actual audio into LiveKit and checks persisted backend outcomes. No live evaluation results or performance claims are fabricated.

```sh
uv run python scripts/preflight.py
uv run python evaluations/run_audio.py --check
PYTHONPATH=services/api:services/agent uv run python scripts/load_calls.py
```

Preflight verifies the LiveKit credentials and opens the requested Gemini Live session; it does not prove the complete voice experience. Running real calls, audio generation, and load checks consumes provider usage.

## Observability and data

The API and worker emit correlated OpenTelemetry spans. Set `OTEL_EXPORTER_OTLP_ENDPOINT` to an OTLP HTTP **base URL**, or set `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` and `LANGFUSE_BASE_URL` for Langfuse export. Backend calls propagate W3C trace headers and include `call.id`; structured API logs include request ID, route, status and duration. Tool audit records and measurements persist in PostgreSQL.

The staff analytics page displays recorded latency/token measurements and handoff outcomes. Browser audio timings are energy-based estimates, not transcript timing or certified latency measurements. The evaluation report separates tool-bearing turns from no-tool turns and records reviewed task completion/tool accuracy/handoff correctness.

Raw audio recording is disabled for the application. Evaluation output recording requires `--record-output`. Transcripts, summaries, audit events and demo business records persist locally; evaluation audio/results are ignored by Git. Human takeover audio is not transcribed; representatives record resolution notes on tickets.

## Repository

```text
apps/web/                 Next.js customer portal and support workspace
services/api/support_api/ FastAPI, authorization, policies, commerce and state machines
services/api/alembic/     Frozen initial migration
services/agent/           LiveKit worker, tools and bounded backend client
evaluations/              50 scenarios, audio preparation, runner and report
scripts/                  Credential preflight, load checks and API type export
docs/                     Architecture, demo, API schema and verification record
```

Detailed architecture and endpoint contracts: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md). Local verification and outstanding external checks: [docs/VERIFICATION.md](docs/VERIFICATION.md).

The project deliberately uses native LiveKit orchestration and keyword policy retrieval. LangGraph, Qdrant, Redis and MCP are deferred. Public hosting, telephony, email/SMS verification and real payment integrations are outside this local demo.
