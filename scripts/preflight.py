"""Validate credentialed LiveKit and Gemini connections without exposing secrets."""

import asyncio
import json
import os
from dotenv import load_dotenv
from google import genai
from google.genai import types
from livekit import api


async def main():
    load_dotenv()
    required = ["LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET", "GOOGLE_API_KEY"]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        print(json.dumps({"status": "not_configured", "missing": missing, "live_verified": False}))
        raise SystemExit(1)
    async with api.LiveKitAPI() as lk:
        await lk.room.list_rooms(api.ListRoomsRequest())
    client = genai.Client(api_key=os.environ["GOOGLE_API_KEY"])
    async with client.aio.live.connect(
        model=os.getenv("GEMINI_MODEL", "gemini-3.1-flash-live-preview"),
        config=types.LiveConnectConfig(response_modalities=["AUDIO"]),
    ):
        print(
            json.dumps(
                {
                    "status": "connected",
                    "livekit_credentials": "valid",
                    "gemini_session": "connected",
                    "full_audio_evaluation": "still_required",
                }
            )
        )
    await client.aio.aclose()


if __name__ == "__main__":
    asyncio.run(main())
