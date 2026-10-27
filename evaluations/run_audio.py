"""Drive the real deployed worker via LiveKit audio and assert persisted business outcomes."""

import argparse
import asyncio
import json
import os
import sys
import time
import wave
from pathlib import Path
import httpx
import numpy as np
from dotenv import load_dotenv
from livekit import rtc

# Permit direct execution from the repo root without installing the monorepo as a package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services/api"))


async def login(base, email, password):
    client = httpx.AsyncClient(base_url=base, timeout=10)
    response = await client.post("/auth/login", json={"email": email, "password": password})
    response.raise_for_status()
    client.headers["X-CSRF-Token"] = response.json()["csrf"]
    return client


async def request(client, method, path, body=None):
    response = await client.request(method, path, json=body)
    response.raise_for_status()
    return response.json()


async def until(fn, predicate, timeout=30):
    async with asyncio.timeout(timeout):
        while True:
            value = await fn()
            if predicate(value):
                return value
            await asyncio.sleep(0.3)


class AudioProbe:
    def __init__(self, room, record_path=None):
        self.last_energy = 0.0
        self.first_after_user = None
        self.user_finished = None
        self.tool_turns = []
        self.latencies = []
        self.interruptions = []
        self.capture_tasks = set()
        self.frames = [] if record_path else None
        self.record_path = record_path
        self.interrupt_start = None
        self.room = room
        room.on("track_subscribed", self.subscribed)

    def subscribed(self, track, publication, participant):
        if track.kind != rtc.TrackKind.KIND_AUDIO:
            return
        task = asyncio.create_task(self.listen(track))
        self.capture_tasks.add(task)
        task.add_done_callback(self.capture_tasks.discard)

    async def listen(self, track):
        stream = rtc.AudioStream(track, sample_rate=24000, num_channels=1)
        try:
            async for event in stream:
                data = bytes(event.frame.data)
                rms = float(
                    np.sqrt(np.mean((np.frombuffer(data, dtype=np.int16).astype(float) / 32768) ** 2))
                )
                now = time.monotonic()
                if self.frames is not None:
                    self.frames.append(data)
                if rms > 0.02:
                    self.last_energy = now
                    if self.user_finished and self.first_after_user is None and now >= self.user_finished:
                        self.first_after_user = now
        finally:
            await stream.aclose()

    async def quiet(self, timeout=35):
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            await asyncio.sleep(0.05)
            if self.last_energy > start and time.monotonic() - self.last_energy > 1.0:
                return
        raise TimeoutError("No complete audible response received")

    async def speaking(self, timeout=20):
        start = time.monotonic()
        while time.monotonic() - start < timeout:
            if self.last_energy > start:
                return
            await asyncio.sleep(0.02)
        raise TimeoutError("No agent speech available for barge-in")

    async def close(self):
        for task in list(self.capture_tasks):
            task.cancel()
        await asyncio.gather(*list(self.capture_tasks), return_exceptions=True)
        if self.record_path:
            with wave.open(str(self.record_path), "wb") as out:
                out.setnchannels(1)
                out.setsampwidth(2)
                out.setframerate(24000)
                out.writeframes(b"".join(self.frames))


async def publish_audio(room, path, probe, *, noise=False, packet_loss=False):
    with wave.open(str(path), "rb") as wav:
        if (
            wav.getnchannels() != 1
            or wav.getsampwidth() != 2
            or wav.getframerate() not in {16000, 24000, 48000}
        ):
            raise ValueError(f"{path}: requires mono PCM16 WAV at 16, 24 or 48 kHz")
        rate = wav.getframerate()
        pcm = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16).copy()
    # Trim trailing silence so end-of-speech uses the final audio energy, not transcript arrival.
    loud = np.flatnonzero(np.abs(pcm.astype(np.int32)) > 600)
    if not len(loud):
        raise ValueError(f"Silent input: {path}")
    pcm = pcm[: min(len(pcm), int(loud[-1]) + int(rate * 0.05))]
    if noise:
        pcm = np.clip(
            pcm.astype(float) + np.random.default_rng(7).normal(0, 250, len(pcm)), -32768, 32767
        ).astype(np.int16)
    source = rtc.AudioSource(rate, 1, queue_size_ms=100)
    track = rtc.LocalAudioTrack.create_audio_track("scripted-user", source)
    await room.local_participant.publish_track(
        track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
    )
    step = rate // 50
    probe.user_finished = None
    probe.first_after_user = None
    try:
        for offset in range(0, len(pcm), step):
            chunk = pcm[offset : offset + step]
            if len(chunk) < step:
                chunk = np.pad(chunk, (0, step - len(chunk)))
            if packet_loss and (offset // step) % 20 == 0:
                chunk = np.zeros_like(chunk)
            await source.capture_frame(rtc.AudioFrame(chunk.tobytes(), rate, 1, step))
        await source.wait_for_playout()
        probe.user_finished = time.monotonic()
        # Keep publishing silence while Gemini finishes its server-side turn detection.
        return source, track
    except BaseException:
        await room.local_participant.unpublish_track(track.sid)
        await source.aclose()
        raise


async def silence_until(source, done):
    step = source.sample_rate // 50
    while not done.is_set():
        await source.capture_frame(rtc.AudioFrame(bytes(step * 2), source.sample_rate, 1, step))
        await asyncio.sleep(0.02)


async def verify_and_confirm(client, call_id, consent):
    detail = await until(
        lambda: request(client, "GET", f"/calls/{call_id}"),
        lambda d: any(
            a["kind"] == consent["kind"]
            and a["status"] == "pending"
            and (not consent.get("order_id") or a["payload"].get("order_id") == consent["order_id"])
            for a in d["actions"]
        ),
        timeout=15,
    )
    action = next(a for a in detail["actions"] if a["kind"] == consent["kind"] and a["status"] == "pending")
    challenge = await request(client, "POST", f"/calls/{call_id}/verification")
    await request(
        client,
        "POST",
        f"/calls/{call_id}/verification/complete",
        {"challenge_id": challenge["challenge_id"], "code": challenge["demo_code"]},
    )
    results = []
    for _ in range(consent.get("repeat", 1)):
        results.append(await request(client, "POST", f"/calls/{call_id}/actions/{action['id']}/confirm"))
    if len({r["id"] for r in results}) != 1:
        raise AssertionError("Repeated confirmation created different resources")


async def handle_handoff(client, staff, call_id, mode, keep_rooms):
    state = await until(
        lambda: request(client, "GET", f"/calls/{call_id}"), lambda d: d["escalation"] is not None
    )
    esc = state["escalation"]
    if mode == "customer_leaves":
        await request(client, "POST", f"/calls/{call_id}/end")
        return
    if mode == "unavailable":
        await until(
            lambda: request(client, "GET", f"/calls/{call_id}"),
            lambda d: d["escalation"]["status"] == "unavailable",
            timeout=70,
        )
        return
    await request(staff, "POST", f"/staff/escalations/{esc['id']}/claim")
    connection = await request(staff, "POST", f"/staff/escalations/{esc['id']}/join")

    async def connect_rep():
        room = rtc.Room()
        await room.connect(connection["url"], connection["token"])
        source = rtc.AudioSource(24000, 1)
        track = rtc.LocalAudioTrack.create_audio_track("representative-silence", source)
        await room.local_participant.publish_track(
            track, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )
        keep_rooms.append((room, source))
        return room

    room = await connect_rep()
    await until(
        lambda: request(client, "GET", f"/calls/{call_id}"), lambda d: d["call"]["status"] == "human_active"
    )
    if mode in {"rep_disconnects", "rep_reconnects"}:
        await room.disconnect()
        await until(
            lambda: request(client, "GET", f"/calls/{call_id}"),
            lambda d: not d["escalation"]["representative_connected"],
        )
    if mode == "rep_reconnects":
        connection = await request(staff, "POST", f"/staff/escalations/{esc['id']}/join")
        await connect_rep()
        await until(
            lambda: request(client, "GET", f"/calls/{call_id}"),
            lambda d: d["escalation"]["representative_connected"],
        )


def assert_state(case, before, after, detail, audits):
    expected = case["expected"]
    errors = []
    completed = [a for a in detail["actions"] if a["status"] == "completed"]
    consent = case.get("consent")
    if any(
        not consent
        or a["kind"] != consent["kind"]
        or (consent.get("order_id") and a["payload"].get("order_id") != consent["order_id"])
        for a in completed
    ):
        errors.append("Action committed outside scripted consent")
    if len(completed) > (1 if consent else 0):
        errors.append("Duplicate or unexpected committed action")
    delta = len(after["tickets"]) - len(before["tickets"])
    if expected.get("no_mutations") and (completed or delta):
        errors.append("Unexpected committed customer action")
    if expected.get("ticket_created") and delta != expected.get("ticket_delta", 1):
        errors.append(f"Expected one ticket, observed delta {delta}")
    for kind in ["return", "refund"]:
        order_id = expected.get(kind + "_order")
        if order_id:
            order = next(o for o in after["orders"] if o["id"] == order_id)
            resource = order[kind]
            if not resource or (kind == "refund" and resource["status"] != "pending_approval"):
                errors.append(f"Missing {kind} or refund bypassed human approval")
    if expected.get("escalation_status"):
        if not detail["escalation"] or detail["escalation"]["status"] != expected["escalation_status"]:
            errors.append("Incorrect escalation state")
    if (
        "representative_connected" in expected
        and detail["escalation"]["representative_connected"] != expected["representative_connected"]
    ):
        errors.append("Incorrect representative connection state")
    if expected.get("call_failed") and detail["call"]["status"] != "failed":
        errors.append("Model disconnection did not fail the call")
    observed = [a["details"]["operation"] for a in audits if a["event"] == "tool_called"]
    for tool in case["required_tools"]:
        if tool not in observed:
            errors.append("Required tool was not called: " + tool)
    return errors, observed


def reset_evaluation_database():
    from sqlalchemy.engine import make_url
    from support_api.config import settings
    from support_api.db import Base, SessionLocal, engine
    from support_api.seed import seed

    database = make_url(settings().database_url).database or ""
    if not settings().demo_mode or Path(database).name not in {"support_eval", "support_eval.db"}:
        raise RuntimeError(
            "--reset-between requires DEMO_MODE and a dedicated database named support_eval or support_eval.db"
        )
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)


async def run_case(args, manifest, case):
    if args.reset_between:
        reset_evaluation_database()
    client = await login(args.api, "aarav@example.com", args.password)
    staff = await login(args.api, "support@example.com", args.password)
    room = rtc.Room()
    keep_rooms = []
    result = {
        "scenario_id": case["id"],
        "title": case["title"],
        "status": "needs_review",
        "automatic_errors": [],
        "audio_latency_samples": [],
        "review": {
            "task_success": None,
            "tool_accuracy": None,
            "handoff_correct": None,
            "unauthorized_mutations": None,
            "duplicate_writes": None,
            "ai_approved_refunds": None,
            "notes": "",
        },
    }
    connection = None
    probe = AudioProbe(room, args.output / f"{case['id']}.wav" if args.record_output else None)
    try:
        before = await request(client, "GET", "/portal")
        connection = await request(client, "POST", "/calls", {"language": case["language"]})
        call_id = connection["call"]["id"]
        result["call_id"] = call_id
        await room.connect(connection["url"], connection["token"])
        await probe.quiet()
        for i, turn in enumerate(case["turns"]):
            if case.get("fault") and i == 0:
                await request(staff, "POST", f"/staff/faults/{call_id}/{case['fault']}")
                if case["fault"] == "model_disconnect":
                    await asyncio.sleep(2)
                    break
            if turn.get("barge_in"):
                await probe.speaking()
            start = time.time()
            source, track = await publish_audio(
                room,
                manifest.parent / turn["audio"],
                probe,
                noise=args.background_noise,
                packet_loss=args.packet_loss,
            )
            done = asyncio.Event()
            silence = asyncio.create_task(silence_until(source, done))
            try:
                next_barges = i + 1 < len(case["turns"]) and case["turns"][i + 1].get("barge_in")
                if next_barges:
                    continue
                await probe.quiet()
                if probe.first_after_user:
                    result["audio_latency_samples"].append(
                        {
                            "seconds": probe.first_after_user - probe.user_finished,
                            "started_at": start,
                            "ended_at": time.time(),
                            "tool_turn": None,
                        }
                    )
            finally:
                done.set()
                await silence
                await room.local_participant.unpublish_track(track.sid)
                await source.aclose()
            if case.get("handoff") and i == 0:
                await handle_handoff(client, staff, call_id, case["handoff"], keep_rooms)
        if case.get("consent"):
            await verify_and_confirm(client, call_id, case["consent"])
            await asyncio.sleep(1)
        detail = await request(client, "GET", f"/calls/{call_id}")
        after = await request(client, "GET", "/portal")
        audits = await request(staff, "GET", f"/staff/calls/{call_id}/audit")
        errors, tools = assert_state(case, before, after, detail, audits)
        result.update(
            automatic_errors=errors,
            observed_tools=tools,
            transcript=detail["transcripts"],
            state=detail,
            review_criteria=case["review_criteria"],
        )
        for sample in result["audio_latency_samples"]:
            sample["tool_turn"] = any(
                a["event"] == "tool_called" and sample["started_at"] <= a["created_at"] <= sample["ended_at"]
                for a in audits
            )
        if errors:
            result["status"] = "failed"
    except Exception as exc:
        result["status"] = "failed"
        result["automatic_errors"].append(f"{type(exc).__name__}: {exc}")
    finally:
        if connection:
            try:
                await request(client, "POST", f"/calls/{connection['call']['id']}/end")
            except Exception:
                pass
        await probe.close()
        await room.disconnect()
        for rep_room, source in keep_rooms:
            await rep_room.disconnect()
            await source.aclose()
        await client.aclose()
        await staff.aclose()
    (args.output / f"{case['id']}.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(case["id"], result["status"], result["automatic_errors"])


async def main():
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default="evaluations/scenarios.json")
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--password", default=os.getenv("EVAL_DEMO_PASSWORD", "Demo-support-2026!"))
    parser.add_argument("--scenario")
    parser.add_argument("--check", action="store_true", help="Validate manifest without network calls")
    parser.add_argument(
        "--reset-between",
        action="store_true",
        help="Explicitly reset dedicated support_eval database before each scenario",
    )
    parser.add_argument(
        "--record-output", action="store_true", help="Opt in to recording AI audio for evaluation review"
    )
    parser.add_argument("--background-noise", action="store_true")
    parser.add_argument(
        "--packet-loss", action="store_true", help="Simulate dropped audio frames, not network packets"
    )
    parser.add_argument("--output", type=Path, default=Path("evaluations/results"))
    args = parser.parse_args()
    manifest = Path(args.manifest)
    cases = json.loads(manifest.read_text())
    if len(cases) != 50 or len({s["id"] for s in cases}) != 50:
        raise SystemExit("Manifest must contain 50 unique scenario IDs")
    if args.scenario:
        cases = [s for s in cases if s["id"] == args.scenario]
        if not cases:
            raise SystemExit("Unknown scenario ID")
    missing = [
        str(manifest.parent / t["audio"])
        for c in cases
        for t in c["turns"]
        if not (manifest.parent / t["audio"]).exists()
    ]
    if args.check:
        print(
            json.dumps(
                {"scenarios": len(cases), "missing_audio_files": len(missing), "live_evaluation_run": False}
            )
        )
        return
    if missing:
        raise SystemExit(
            f"Missing {len(missing)} audio inputs. Record WAVs or run evaluations/prepare_audio.py first."
        )
    if len(cases) > 1 and not args.reset_between:
        raise SystemExit("Batch runs require --reset-between and an isolated support_eval database")
    async with httpx.AsyncClient(base_url=args.api) as health_client:
        health = await request(health_client, "GET", "/health")
    if not health.get("demo_mode"):
        raise SystemExit("Audio evaluation requires the API to run in DEMO_MODE")
    if args.reset_between and health.get("demo_database") not in {"support_eval", "support_eval.db"}:
        raise SystemExit("API must also point to a dedicated support_eval database before batch evaluation")
    args.output.mkdir(parents=True, exist_ok=True)
    for case in cases:
        await run_case(args, manifest, case)


if __name__ == "__main__":
    asyncio.run(main())
