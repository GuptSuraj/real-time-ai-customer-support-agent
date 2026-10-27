import hashlib
import secrets
import time
from typing import Annotated
import jwt
from fastapi import Depends, Header, HTTPException, Request
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session
from .config import settings
from .db import get_db
from .models import Call, LoginSession, User

passwords = PasswordHash.recommended()
DUMMY_HASH = passwords.hash("dummy-password-for-constant-time")


def digest(value: str):
    return hashlib.sha256(value.encode()).hexdigest()


def user_session(request: Request, db: Session = Depends(get_db)):
    token = request.cookies.get("support_session", "")
    session = db.scalar(select(LoginSession).where(LoginSession.token_hash == digest(token)))
    if not session or session.expires_at < time.time():
        raise HTTPException(401, "Please sign in")
    user = db.get(User, session.user_id)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        csrf = request.headers.get("x-csrf-token", "")
        if not secrets.compare_digest(csrf, session.csrf):
            raise HTTPException(403, "Invalid CSRF token")
        if request.headers.get("origin") not in {None, settings().app_origin}:
            raise HTTPException(403, "Origin not allowed")
    return user, session


Auth = Annotated[tuple[User, LoginSession], Depends(user_session)]
DB = Annotated[Session, Depends(get_db)]


def staff(auth: Auth):
    if auth[0].role != "staff":
        raise HTTPException(403, "Staff access required")
    return auth[0]


Staff = Annotated[User, Depends(staff)]


def agent_token(call: Call):
    return jwt.encode(
        {"sub": call.id, "aud": "support-agent", "exp": int(time.time()) + 7200, "epoch": call.agent_epoch},
        settings().session_secret,
        algorithm="HS256",
    )


def agent_call(db: DB, authorization: Annotated[str, Header()] = ""):
    try:
        data = jwt.decode(
            authorization.removeprefix("Bearer "),
            settings().session_secret,
            algorithms=["HS256"],
            audience="support-agent",
        )
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid agent credential")
    call = db.get(Call, data["sub"])
    if (
        not call
        or call.agent_epoch != data.get("epoch")
        or call.status in {"ended", "failed", "human_active"}
    ):
        raise HTTPException(403, "Agent no longer controls this call")
    return call


AgentCall = Annotated[Call, Depends(agent_call)]


def lifecycle_call(db: DB, authorization: Annotated[str, Header()] = ""):
    """Original worker may report room disconnects after takeover, but cannot use tools."""
    try:
        data = jwt.decode(
            authorization.removeprefix("Bearer "),
            settings().session_secret,
            algorithms=["HS256"],
            audience="support-agent",
        )
    except jwt.PyJWTError:
        raise HTTPException(401, "Invalid agent credential")
    call = db.get(Call, data["sub"])
    if not call or data.get("epoch", -1) > call.agent_epoch:
        raise HTTPException(403, "Unknown call")
    return call


LifecycleCall = Annotated[Call, Depends(lifecycle_call)]
