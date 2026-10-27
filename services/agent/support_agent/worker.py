import asyncio
import json
import logging
import os
from dotenv import load_dotenv
from opentelemetry import trace
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobRequest,
    cli,
    function_tool,
    room_io,
)
from livekit.plugins import google
from google.genai import types
from .client import Backend
from .prompts import INSTRUCTIONS
from support_api.telemetry import configure

load_dotenv()
tracer = configure("support-agent")
log = logging.getLogger("support.agent")
server = AgentServer()


class SupportAgent(Agent):
    def __init__(self, backend, language):
        super().__init__(
            instructions=INSTRUCTIONS.format(language="Hindi" if language == "hi" else "English")
        )
        self.backend = backend

    async def safe(self, operation):
        try:
            return await operation
        except Exception as exc:
            import httpx

            if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code < 500:
                detail = exc.response.json().get("detail", "Operation rejected")
                return {"error": detail, "completed": False}
            log.exception("tool_failed call_id=%s", self.backend.call_id)
            return {
                "error": "Backend unavailable or operation rejected. Do not claim success. Check context or offer human support."
            }

    @function_tool
    async def check_support_context(self):
        """Read this customer's orders, items, return/refund status, tickets, verification and action results."""
        return await self.safe(self.backend.context())

    @function_tool
    async def search_store_knowledge(self, query: str):
        """Retrieve saved store policies and product descriptions. Do not invent policy or product facts."""
        from urllib.parse import quote

        return await self.safe(
            self.backend.request(
                "GET", "/internal/knowledge?q=" + quote(query), operation="search_store_knowledge"
            )
        )

    @function_tool
    async def prepare_return_request(self, order_id: str, reason: str):
        """Propose an eligible whole-order return. Customer must verify and confirm in portal."""
        return await self.safe(self.backend.prepare("return", order_id=order_id, reason=reason))

    @function_tool
    async def prepare_refund_request(self, order_id: str, reason: str):
        """Propose a refund request for HUMAN approval after a received return. Does not issue money."""
        return await self.safe(self.backend.prepare("refund", order_id=order_id, reason=reason))

    @function_tool
    async def prepare_support_ticket(self, title: str, description: str):
        """Propose a ticket/callback with exact details for customer verification and portal confirmation."""
        return await self.safe(self.backend.prepare("ticket", title=title, description=description))

    @function_tool
    async def request_human_support(self, summary: str):
        """Queue live browser takeover. Include issue, verification, completed actions and unresolved questions."""
        return await self.safe(
            self.backend.request(
                "POST", "/internal/escalate", {"reason": summary}, operation="request_human_support"
            )
        )


async def accept_job(req: JobRequest):
    metadata = json.loads(req.job.metadata)
    await req.accept(name="Mira · AI support", identity="agent-" + metadata["call_id"])


async def run_session(ctx: JobContext):
    metadata = json.loads(ctx.job.metadata)
    call_id = metadata["call_id"]
    backend = Backend(os.getenv("INTERNAL_API_URL", "http://localhost:8000"), metadata["token"], call_id)
    managed_cleanup = False

    async def startup_cleanup():
        if not managed_cleanup:
            await backend.close()

    ctx.add_shutdown_callback(startup_cleanup)
    await ctx.connect()
    context = await backend.context(tool=False)
    identity = "customer-" + context["call"]["customer_id"]
    await asyncio.wait_for(ctx.wait_for_participant(identity=identity), timeout=120)
    session = AgentSession(
        llm=google.realtime.RealtimeModel(
            model=os.getenv("GEMINI_MODEL", "gemini-3.1-flash-live-preview"),
            voice=os.getenv("GEMINI_VOICE", "Puck"),
            input_audio_transcription=types.AudioTranscriptionConfig(),
            output_audio_transcription=types.AudioTranscriptionConfig(),
            thinking_config=types.ThinkingConfig(thinking_level="minimal"),
        )
    )
    tasks = set()
    closing = False
    transferred = False

    def spawn(coroutine):
        task = asyncio.create_task(coroutine)
        tasks.add(task)

        def done(t):
            tasks.discard(t)
            if not t.cancelled() and t.exception():
                log.warning(
                    "event_delivery_failed call_id=%s error=%s", call_id, type(t.exception()).__name__
                )

        task.add_done_callback(done)

    def metric(name, value, tags=None):
        if not closing:
            spawn(
                backend.request(
                    "POST", "/internal/metrics", {"name": name, "value": value, "tags": tags or {}}
                )
            )

    backend.on_metric = metric

    @session.on("conversation_item_added")
    def transcript(event):
        item = event.item
        if getattr(item, "role", None) in {"user", "assistant"} and item.text_content:
            spawn(
                backend.request(
                    "POST",
                    "/internal/transcripts",
                    {
                        "event_id": item.id,
                        "role": item.role,
                        "text": item.text_content,
                        "interrupted": getattr(item, "interrupted", False),
                    },
                    idempotent=True,
                )
            )

    @session.on("metrics_collected")
    def metrics(event):
        values = event.metrics.model_dump()
        for name in [
            "ttft",
            "input_tokens",
            "output_tokens",
            "duration",
            "detection_delay",
            "num_interruptions",
            "num_backchannels",
        ]:
            value = values.get(name)
            if isinstance(value, (int, float)) and value >= 0:
                metric("model_" + name, value, {"type": values.get("type", "unknown")})

    @session.on("error")
    def error(event):
        if not getattr(event.error, "recoverable", False):
            log.error("model_error call_id=%s", call_id)
            spawn(backend.request("POST", "/internal/failure"))

    async def watch():
        nonlocal transferred
        previous_actions = {}
        notified_unavailable = False
        while not closing:
            await asyncio.sleep(1)
            try:
                state = await backend.context(tool=False)
                esc = state.get("escalation")
                if esc and esc["status"] == "connecting":
                    rep_id = "staff-" + str(esc["assigned_to"])
                    rep = next(
                        (p for p in ctx.room.remote_participants.values() if p.identity == rep_id), None
                    )
                    has_audio = rep and any(
                        p.kind == rtc.TrackKind.KIND_AUDIO and not p.muted
                        for p in rep.track_publications.values()
                    )
                    if has_audio:
                        # Room membership/track comes from LiveKit SDK, never a browser's assertion.
                        await backend.request("POST", "/internal/handoff/media", {"identity": rep_id})
                        session.input.set_audio_enabled(False)
                        session.output.set_audio_enabled(False)
                        await session.interrupt(force=True)
                        # The representative may leave while the AI playout is being drained.
                        current_rep = next(
                            (p for p in ctx.room.remote_participants.values() if p.identity == rep_id), None
                        )
                        if not current_rep or not any(
                            p.kind == rtc.TrackKind.KIND_AUDIO and not p.muted
                            for p in current_rep.track_publications.values()
                        ):
                            await backend.request("POST", "/internal/representative-left")
                            session.input.set_audio_enabled(True)
                            session.output.set_audio_enabled(True)
                            continue
                        try:
                            await backend.request("POST", "/internal/handoff/ack")
                        except Exception as ack_error:
                            import httpx

                            if (
                                isinstance(ack_error, httpx.HTTPStatusError)
                                and ack_error.response.status_code == 409
                            ):
                                session.input.set_audio_enabled(True)
                                session.output.set_audio_enabled(True)
                                continue
                            raise
                        transferred = True
                        await session.aclose()
                        return
                if esc and esc["status"] == "unavailable" and not notified_unavailable:
                    notified_unavailable = True
                    session.generate_reply(
                        instructions="No representative accepted within 60 seconds. Explain the delay and offer to prepare a callback ticket for portal confirmation."
                    )
                for action in state["actions"]:
                    old_status = previous_actions.get(action["id"])
                    if action["status"] == "completed" and old_status != "completed":
                        session.generate_reply(
                            instructions="The customer confirmed this exact backend action; report its result briefly: "
                            + json.dumps(action["result"])
                        )
                    previous_actions[action["id"]] = action["status"]
            except Exception as exc:
                import httpx

                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {401, 403}:
                    session.input.set_audio_enabled(False)
                    session.output.set_audio_enabled(False)
                    await session.aclose()
                    return
                log.warning("watch_retry call_id=%s error=%s", call_id, type(exc).__name__)

    async def cleanup():
        nonlocal closing
        closing = True
        watcher.cancel()
        await asyncio.gather(watcher, return_exceptions=True)
        if not transferred:
            await session.aclose()
        if tasks:
            await asyncio.gather(*list(tasks), return_exceptions=True)
        await backend.close()

    await session.start(
        agent=SupportAgent(backend, metadata.get("language", "en")),
        room=ctx.room,
        room_options=room_io.RoomOptions(
            participant_identity=identity, text_input=False, video_input=False, close_on_disconnect=False
        ),
        session_host=False,
        record=False,
    )
    await backend.request("POST", "/internal/ready")
    session.generate_reply(
        instructions="Greet the customer as Mira from Northstar support. Ask how you can help today."
    )
    watcher = asyncio.create_task(watch())
    managed_cleanup = True
    ctx.add_shutdown_callback(cleanup)

    @ctx.room.on("participant_disconnected")
    def left(participant):
        if participant.identity == identity:
            spawn(backend.request("POST", "/internal/customer-left"))
        elif participant.identity.startswith("staff-"):
            # Keep the AI stopped; the UI offers representative reconnection.
            spawn(backend.request("POST", "/internal/representative-left"))

    @ctx.room.on("track_published")
    def rep_rejoined(publication, participant):
        if (
            transferred
            and participant.identity.startswith("staff-")
            and publication.kind == rtc.TrackKind.KIND_AUDIO
        ):
            spawn(
                backend.request(
                    "POST", "/internal/representative-rejoined", {"identity": participant.identity}
                )
            )


@server.rtc_session(agent_name=os.getenv("AGENT_NAME", "commerce-support"), on_request=accept_job)
async def entrypoint(ctx: JobContext):
    metadata = json.loads(ctx.job.metadata)
    span = tracer.start_span("support.call", attributes={"call.id": metadata["call_id"]})

    async def end_span():
        span.end()

    ctx.add_shutdown_callback(end_span)
    with trace.use_span(span, end_on_exit=False):
        try:
            await run_session(ctx)
        except Exception as exc:
            span.record_exception(exc)
            log.exception("session_start_failed call_id=%s", metadata["call_id"])
            backend = Backend(
                os.getenv("INTERNAL_API_URL", "http://localhost:8000"), metadata["token"], metadata["call_id"]
            )
            try:
                await backend.request("POST", "/internal/failure")
            finally:
                await backend.close()
            raise


if __name__ == "__main__":
    cli.run_app(server)
