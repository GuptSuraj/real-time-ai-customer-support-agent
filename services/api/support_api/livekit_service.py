import json
from datetime import timedelta
from livekit import api
from fastapi import HTTPException
from .config import settings
from .security import agent_token


def configured():
    cfg = settings()
    return bool(cfg.livekit_url and cfg.livekit_api_key and cfg.livekit_api_secret)


def join_token(call, identity, name):
    cfg = settings()
    return (
        api.AccessToken(cfg.livekit_api_key, cfg.livekit_api_secret)
        .with_identity(identity)
        .with_name(name)
        .with_ttl(timedelta(minutes=10))
        .with_grants(
            api.VideoGrants(
                room_join=True,
                room=call.room,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=False,
                can_publish_sources=["microphone"],
                can_update_own_metadata=False,
            )
        )
        .to_jwt()
    )


async def dispatch(call):
    if not configured():
        raise HTTPException(503, "LiveKit credentials are not configured. Add them to .env and restart.")
    cfg = settings()
    async with api.LiveKitAPI(cfg.livekit_url, cfg.livekit_api_key, cfg.livekit_api_secret) as lk:
        await lk.room.create_room(
            api.CreateRoomRequest(name=call.room, empty_timeout=120, max_participants=3)
        )
        await lk.agent_dispatch.create_dispatch(
            api.CreateAgentDispatchRequest(
                room=call.room,
                agent_name=cfg.agent_name,
                metadata=json.dumps(
                    {"call_id": call.id, "token": agent_token(call), "language": call.language}
                ),
            )
        )


async def remove_participant(call, identity):
    if not configured():
        return
    cfg = settings()
    async with api.LiveKitAPI(cfg.livekit_url, cfg.livekit_api_key, cfg.livekit_api_secret) as lk:
        try:
            await lk.room.remove_participant(api.RoomParticipantIdentity(room=call.room, identity=identity))
        except api.TwirpError as exc:
            if exc.code != "not_found":
                raise


async def delete_room(call):
    if not configured():
        return
    cfg = settings()
    async with api.LiveKitAPI(cfg.livekit_url, cfg.livekit_api_key, cfg.livekit_api_secret) as lk:
        try:
            await lk.room.delete_room(api.DeleteRoomRequest(room=call.room))
        except api.TwirpError as exc:
            if exc.code != "not_found":
                raise
