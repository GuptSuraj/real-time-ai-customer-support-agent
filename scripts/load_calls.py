"""Hold five authenticated calls concurrently to exercise real dispatch and room isolation."""

import asyncio
import os
import time
import httpx
from livekit import rtc


async def caller(email, seconds):
    async with httpx.AsyncClient(base_url=os.getenv("EVAL_API_URL", "http://localhost:8000")) as client:
        response = await client.post(
            "/auth/login",
            json={"email": email, "password": os.getenv("EVAL_DEMO_PASSWORD", "Demo-support-2026!")},
        )
        response.raise_for_status()
        client.headers["X-CSRF-Token"] = response.json()["csrf"]
        response = await client.post("/calls", json={"language": "en"}, timeout=10)
        response.raise_for_status()
        connection = response.json()
        room = rtc.Room()
        source = rtc.AudioSource(24000, 1)
        try:
            await room.connect(connection["url"], connection["token"])
            track = rtc.LocalAudioTrack.create_audio_track("load-test", source)
            await room.local_participant.publish_track(track)
            print(email, connection["call"]["id"], "connected")
            started = time.monotonic()
            while time.monotonic() - started < seconds:
                await source.capture_frame(rtc.AudioFrame(bytes(960), 24000, 1, 480))
                await asyncio.sleep(0.02)
            detail = await client.get(f"/calls/{connection['call']['id']}")
            detail.raise_for_status()
            if detail.json()["call"]["status"] != "active":
                raise RuntimeError(f"Agent did not become active for {email}")
            return connection["call"]["room"]
        finally:
            await client.post(f"/calls/{connection['call']['id']}/end")
            await room.disconnect()
            await source.aclose()


async def main():
    rooms = await asyncio.gather(
        *(
            caller(email, 20)
            for email in [
                "aarav@example.com",
                "meera@example.com",
                "sim1@example.com",
                "sim2@example.com",
                "sim3@example.com",
            ]
        )
    )
    assert len(set(rooms)) == 5
    print(
        "Five simultaneous calls completed with distinct rooms. Run speech scenarios separately to assess task quality under load."
    )


if __name__ == "__main__":
    asyncio.run(main())
