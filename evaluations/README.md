# Audio evaluation

`scenarios.json` contains 50 scripted conversations: 8 order/product, 8 return, 8 refund, 6 policy/ticket, 6 handoff, 6 language/interruption and 8 resilience cases. Each has actual user utterances, expected backend outcomes, required tool evidence and review criteria.

## Prepare an isolated environment

Run a separate API configured with `DATABASE_URL` pointing to a dedicated PostgreSQL database named **support_eval**. Start the actual voice worker against that API. Use `DEMO_MODE=true`, `ENABLE_FAULT_INJECTION=true`, and the real provider credentials. Do not run batch evaluations against your demonstration data.

The batch runner's `--reset-between` option explicitly drops and recreates application tables **only** in a database named `support_eval` (or `support_eval.db` for exploration). It then reseeds the same fixtures before each scenario. Do not have other sessions open against this evaluation database. Real concurrency validation uses PostgreSQL.

Check provider access and the manifest:

```sh
uv run python scripts/preflight.py
uv run python evaluations/run_audio.py --check
```

Preflight opens the exact configured Gemini Live model. A successful preflight is not a passed conversation evaluation. Missing credentials or audio files are reported explicitly.

## Supply user audio

Record each turn as a mono PCM16 WAV at 16, 24 or 48 kHz using the paths in the manifest, or explicitly generate synthetic user audio:

```sh
uv run python evaluations/prepare_audio.py --tts-model gemini-2.5-flash-preview-tts
```

This optional, billed TTS step creates **test caller fixtures only**. Production voice uses Gemini Live directly, without separate STT/TTS services. Audio files are ignored by Git. You can generate one case with `--scenario orders-01`.

## Run real audio

```sh
# One case, using a fresh seeded dataset
uv run python evaluations/run_audio.py --scenario orders-01

# All 50; API and this runner must use the same dedicated DATABASE_URL
uv run python evaluations/run_audio.py --reset-between

# Degraded caller audio (dropped frames approximate audio loss, not WebRTC network loss)
uv run python evaluations/run_audio.py --reset-between --background-noise --packet-loss
```

The driver logs in through real auth, creates an actual dispatched call, joins LiveKit, publishes WAV audio, listens to returned audio, and obtains transcript/action/tool audit evidence from the API. Scripted consent cases complete the same customer verification and exact-action confirmation endpoints used by the portal. Handoff cases join an actual assigned representative participant, exercise timeout/disconnect/reconnect, and check the committed state.

The separate five-call check is:

```sh
PYTHONPATH=services/api:services/agent uv run python scripts/load_calls.py
```

Raw output recording requires `--record-output`. It is off by default. Audio streaming to the voice provider still occurs during every audio evaluation.

## Review and report

Each run produces `evaluations/results/<scenario-id>.json`. Automatic checks verify actual business state, consent boundaries, required tool calls and duplicate behavior. Successful automatic checks leave the result at **needs_review**.

Review the captured transcript and, when opted in, audio. Fill these fields in each result's `review` object:

- `task_success`: true/false based on the expected customer outcome and factual explanation.
- `tool_accuracy`: true/false for correct tool choice and arguments. Required-tool presence alone is insufficient.
- `handoff_correct`: true/false for the six handoff cases; leave null for unrelated cases.
- `unauthorized_mutations`, `duplicate_writes`, `ai_approved_refunds`: observed counts, each required to be zero.
- `notes`: evidence and reasons, particularly for failures or ambiguous audio.

```sh
uv run python evaluations/report.py
```

No completed runs means rates and P95 remain null, not zero or a fabricated pass. Release readiness requires 50 distinct reviewed results, no automatic failures, at least 90% task completion, at least 95% reviewed tool accuracy, at least six correct handoff reviews, completed safety review and no-tool audio P95 below 2.5 seconds.

The harness times final published user audio to first detected remote speech energy. It trims trailing input silence and classifies tool-bearing turns using server audit timestamps. Use a synchronized host for the API and driver. Audio-energy timing is an estimate; corroborate key measurements with recordings/provider traces. Interrupted turns and missing responses are reviewed separately. Browser interruption stopping estimates are persisted under `audio_interruption_seconds`.

## Current execution status

The manifest and runner are implemented and validated structurally. The 50 real audio runs, provider availability, handoff media behavior and performance thresholds require credentials and have **not** been certified by local mocked tests. Keep actual reports separate from this source manifest.
