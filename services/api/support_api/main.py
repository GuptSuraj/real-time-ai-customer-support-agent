import asyncio
import json
import logging
import secrets
import time
from contextlib import asynccontextmanager
from collections import defaultdict, deque
from fastapi import FastAPI, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from livekit import api as lkapi
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from . import livekit_service as lk
from .business_rules import ACTION_TTL_SECONDS, CHALLENGE_TTL_SECONDS, HANDOFF_TIMEOUT_SECONDS
from .knowledge.retrieval import retrieve
from .config import settings
from .db import SessionLocal
from .domain import (
    audit,
    confirm_action,
    customer_for,
    end_call,
    escalation_detail,
    expire_escalations,
    order_detail,
    owned_call,
    prepare_action,
    serialize,
    verified,
)
from .models import (
    Audit,
    Call,
    Customer,
    Escalation,
    LoginSession,
    Metric,
    Order,
    PendingAction,
    Policy,
    Product,
    Refund,
    Return,
    Ticket,
    Transcript,
    User,
    Verification,
    WebhookReceipt,
    uid,
)
from .schemas import (
    KnowledgeResponse,
    ActionOut,
    CallDetailOut,
    ConnectionOut,
    DashboardOut,
    PortalOut,
    SessionOut,
    ActionInput,
    CallInput,
    CustomerUpdate,
    DecisionInput,
    LoginInput,
    MetricInput,
    ReasonInput,
    SummaryInput,
    TicketUpdate,
    TranscriptInput,
    VerifyInput,
)
from .security import AgentCall, Auth, DB, DUMMY_HASH, LifecycleCall, Staff, digest, passwords
from .telemetry import configure

log = logging.getLogger("support.api")
tracer = configure("support-api")
login_attempts = defaultdict(deque)


async def maintenance():
    while True:
        await asyncio.sleep(2)
        try:
            with SessionLocal() as db:
                expire_escalations(db)
                for stale in db.scalars(
                    select(Call)
                    .where(Call.status == "connecting", Call.created_at < time.time() - 120)
                    .with_for_update()
                ):
                    end_call(db, stale, "failed")
                for refund in db.scalars(select(Refund).where(Refund.status == "approved").with_for_update()):
                    refund.status = "processing"
                    refund.processing_at = time.time()
                for refund in db.scalars(
                    select(Refund)
                    .where(Refund.status == "processing", Refund.processing_at < time.time() - 10)
                    .with_for_update()
                ):
                    refund.status = "completed"
                    order = db.get(Order, refund.order_id)
                    audit(
                        db, "simulated-processor", "refund_completed", order.customer_id, refund_id=refund.id
                    )
                db.commit()
        except Exception:
            log.exception("maintenance_failed")


@asynccontextmanager
async def lifespan(_):
    if not settings().demo_mode and (
        not settings().cookie_secure or settings().session_secret.startswith("local-")
    ):
        raise RuntimeError("Non-demo mode requires a unique SESSION_SECRET and COOKIE_SECURE=true")
    task = asyncio.create_task(maintenance())
    yield
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


app = FastAPI(title="Realtime Support API", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings().app_origin],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH"],
    allow_headers=["Content-Type", "X-CSRF-Token"],
)


def redact_knowledge_query(span, scope):
    if span and span.is_recording() and scope.get("path") == "/internal/knowledge":
        # Preserve trace timing and correlation without exporting the caller's question in URLs.
        path = scope.get("path", "")
        span.set_attribute("http.url", path)
        span.set_attribute("http.target", path)
        span.set_attribute("url.full", path)
        span.set_attribute("url.query", "[redacted]")


FastAPIInstrumentor.instrument_app(app, server_request_hook=redact_knowledge_query)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = uid()
    from opentelemetry import trace

    trace.get_current_span().set_attribute("request.id", request_id)
    start = time.monotonic()
    if (
        settings().demo_mode
        and settings().enable_fault_injection
        and request.url.path in {"/internal/context", "/internal/actions", "/internal/knowledge"}
    ):
        import jwt
        from .faults import consume

        try:
            claims = jwt.decode(
                request.headers.get("authorization", "").removeprefix("Bearer "),
                settings().session_secret,
                algorithms=["HS256"],
                audience="support-agent",
            )
            with SessionLocal() as fault_db:
                fault = consume(fault_db, claims["sub"])
            if fault == "backend_timeout":
                await asyncio.sleep(6)
            elif fault == "database_error":
                from fastapi.responses import JSONResponse

                return JSONResponse(status_code=503, content={"detail": "Injected database failure (demo)"})
        except jwt.PyJWTError:
            pass
    response = await call_next(request)
    operation = request.headers.get("x-agent-operation")
    if operation in {
        "check_support_context",
        "search_store_knowledge",
        "prepare_return_request",
        "prepare_refund_request",
        "prepare_support_ticket",
        "request_human_support",
    } and request.url.path.startswith("/internal/"):
        import jwt

        try:
            claims = jwt.decode(
                request.headers.get("authorization", "").removeprefix("Bearer "),
                settings().session_secret,
                algorithms=["HS256"],
                audience="support-agent",
            )
            with SessionLocal() as operation_db:
                operation_call = operation_db.get(Call, claims["sub"])
                if operation_call:
                    audit(
                        operation_db,
                        "agent",
                        "tool_called",
                        operation_call.customer_id,
                        operation_call.id,
                        operation=operation,
                        status=response.status_code,
                        request_id=request_id,
                    )
                    operation_db.commit()
        except jwt.PyJWTError:
            pass
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    log.info(
        json.dumps(
            {
                "request_id": request_id,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.monotonic() - start) * 1000, 1),
            }
        )
    )
    return response


@app.exception_handler(IntegrityError)
async def conflict(_, exc):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=409, content={"detail": "Conflicting operation; refresh and retry"})


@app.get("/health")
def health(db: DB):
    db.execute(text("SELECT 1"))
    from pathlib import Path
    from sqlalchemy.engine import make_url

    return {
        "status": "ok",
        "voice_configured": lk.configured(),
        "demo_mode": settings().demo_mode,
        "demo_database": Path(make_url(settings().database_url).database or "").name
        if settings().demo_mode
        else None,
    }


@app.post("/auth/login", response_model=SessionOut)
def login(body: LoginInput, request: Request, response: Response, db: DB):
    key = request.client.host if request.client else "unknown"
    attempts = login_attempts[key]
    while attempts and attempts[0] < time.time() - 60:
        attempts.popleft()
    if len(attempts) >= 10:
        raise HTTPException(429, "Too many login attempts; wait a minute")
    attempts.append(time.time())
    if request.headers.get("origin") not in {None, settings().app_origin}:
        raise HTTPException(403, "Origin not allowed")
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    valid = passwords.verify(body.password, user.password_hash if user else DUMMY_HASH)
    if not user or not valid:
        raise HTTPException(401, "Incorrect email or password")
    token = secrets.token_urlsafe(32)
    session = LoginSession(
        user_id=user.id,
        token_hash=digest(token),
        csrf=secrets.token_urlsafe(24),
        expires_at=time.time() + 8 * 3600,
    )
    db.add(session)
    db.commit()
    response.set_cookie(
        "support_session",
        token,
        httponly=True,
        secure=settings().cookie_secure,
        samesite="lax",
        max_age=8 * 3600,
    )
    return {"user": {"id": user.id, "name": user.name, "role": user.role}, "csrf": session.csrf}


@app.get("/auth/me", response_model=SessionOut)
def me(auth: Auth):
    user, session = auth
    return {"user": {"id": user.id, "name": user.name, "role": user.role}, "csrf": session.csrf}


@app.post("/auth/logout")
def logout(auth: Auth, db: DB, response: Response):
    db.delete(auth[1])
    db.commit()
    response.delete_cookie("support_session")
    return {"ok": True}


@app.get("/portal", response_model=PortalOut)
def portal(auth: Auth, db: DB):
    customer = customer_for(db, auth[0])
    return {
        "customer": serialize(customer),
        "orders": [
            order_detail(db, o) for o in db.scalars(select(Order).where(Order.customer_id == customer.id))
        ],
        "tickets": [
            serialize(t) for t in db.scalars(select(Ticket).where(Ticket.customer_id == customer.id))
        ],
        "calls": [
            serialize(c)
            for c in db.scalars(
                select(Call).where(Call.customer_id == customer.id).order_by(Call.created_at.desc()).limit(20)
            )
        ],
    }


@app.get("/products")
def products(auth: Auth, db: DB):
    return [serialize(p) for p in db.scalars(select(Product))]


@app.get("/policies")
def policies(auth: Auth, db: DB, q: str = ""):
    query = select(Policy)
    if q:
        # Keyword retrieval remains grounded in saved policy text; no model-generated policy.
        terms = q.lower().split()[:8]
        rows = list(db.scalars(query))
        rows.sort(key=lambda p: sum(term in (p.title + " " + p.body).lower() for term in terms), reverse=True)
        return [serialize(p) for p in rows[:4]]
    return [serialize(p) for p in db.scalars(query)]


@app.post("/calls", response_model=ConnectionOut)
async def start_call(body: CallInput, auth: Auth, db: DB):
    customer = customer_for(db, auth[0])
    db.scalar(select(Customer).where(Customer.id == customer.id).with_for_update())
    active = db.scalar(
        select(Call).where(Call.customer_id == customer.id, Call.status.not_in(["ended", "failed"]))
    )
    if active:
        raise HTTPException(409, "End your existing call before starting another")
    call = Call(id=uid(), customer_id=customer.id, room="support-" + uid(), language=body.language)
    db.add(call)
    db.commit()  # Dispatch only after scoped credentials can resolve the committed call.
    try:
        await asyncio.wait_for(lk.dispatch(call), timeout=5)
    except Exception as exc:
        call.status = "failed"
        call.ended_at = time.time()
        db.commit()
        if isinstance(exc, HTTPException):
            raise
        log.warning("dispatch_failed call_id=%s type=%s", call.id, type(exc).__name__)
        raise HTTPException(
            503, "Could not connect the voice worker. Check LiveKit configuration and worker logs."
        )
    audit(db, auth[0].id, "call_started", customer.id, call.id)
    db.commit()
    return {
        "call": serialize(call),
        "url": settings().livekit_url,
        "token": lk.join_token(call, "customer-" + customer.id, auth[0].name),
    }


@app.get("/calls/{call_id}", response_model=CallDetailOut)
def call_detail(call_id: str, auth: Auth, db: DB):
    call = owned_call(db, auth[0], call_id)
    esc = db.scalar(select(Escalation).where(Escalation.call_id == call.id))
    return {
        "call": serialize(call),
        "verified": bool(verified(db, call.id)),
        "transcripts": [
            serialize(t)
            for t in db.scalars(
                select(Transcript).where(Transcript.call_id == call.id).order_by(Transcript.created_at)
            )
        ],
        "actions": [
            serialize(a)
            for a in db.scalars(
                select(PendingAction)
                .where(PendingAction.call_id == call.id)
                .order_by(PendingAction.created_at)
            )
        ],
        "escalation": serialize(esc) if esc else None,
        "metrics": [serialize(m) for m in db.scalars(select(Metric).where(Metric.call_id == call.id))],
    }


@app.post("/calls/{call_id}/end")
async def finish_call(call_id: str, auth: Auth, db: DB):
    call = owned_call(db, auth[0], call_id, lock=True)
    end_call(db, call)
    db.commit()
    try:
        await asyncio.wait_for(lk.delete_room(call), 5)
    except Exception:
        log.exception("room_cleanup_failed call_id=%s", call.id)
    return {"ok": True}


@app.post("/calls/{call_id}/verification")
def challenge(call_id: str, auth: Auth, db: DB):
    customer_for(db, auth[0])
    call = owned_call(db, auth[0], call_id, lock=True)
    if call.status not in {"connecting", "active"}:
        raise HTTPException(409, "Verification unavailable for this call")
    for previous in db.scalars(select(Verification).where(Verification.call_id == call.id)):
        previous.expires_at = 0
        previous.verified_until = None
    code = f"{secrets.randbelow(1000000):06}"
    challenge = Verification(
        call_id=call.id, code_hash=digest(code), expires_at=time.time() + CHALLENGE_TTL_SECONDS
    )
    db.add(challenge)
    db.commit()
    # Demo-only challenge is shown to the authenticated customer, never sent to the model.
    return {"challenge_id": challenge.id, "demo_code": code, "expires_at": challenge.expires_at}


@app.post("/calls/{call_id}/verification/complete")
def complete_verification(call_id: str, body: VerifyInput, auth: Auth, db: DB):
    customer_for(db, auth[0])
    call = owned_call(db, auth[0], call_id, lock=True)
    challenge = db.get(Verification, body.challenge_id)
    if (
        not challenge
        or challenge.call_id != call.id
        or challenge.consumed
        or challenge.expires_at < time.time()
        or challenge.attempts >= 5
    ):
        raise HTTPException(409, "Challenge expired or used")
    challenge.attempts += 1
    if not secrets.compare_digest(challenge.code_hash, digest(body.code)):
        db.commit()
        raise HTTPException(400, "Incorrect code")
    challenge.consumed = True
    challenge.verified_until = time.time() + ACTION_TTL_SECONDS
    audit(db, auth[0].id, "identity_verified", call.customer_id, call.id)
    db.commit()
    return {"verified": True}


@app.post("/calls/{call_id}/actions/{action_id}/confirm")
def confirm(call_id: str, action_id: str, auth: Auth, db: DB):
    customer_for(db, auth[0])
    call = owned_call(db, auth[0], call_id, lock=True)
    result = confirm_action(db, call, action_id, auth[0].id)
    db.commit()
    return result


@app.post("/calls/{call_id}/actions/{action_id}/cancel")
def cancel(call_id: str, action_id: str, auth: Auth, db: DB):
    customer_for(db, auth[0])
    call = owned_call(db, auth[0], call_id, lock=True)
    action = db.get(PendingAction, action_id)
    if not action or action.call_id != call.id:
        raise HTTPException(404, "Action not found")
    if action.status == "pending":
        action.status = "cancelled"
    db.commit()
    return {"ok": True}


@app.get("/staff/dashboard", response_model=DashboardOut)
def dashboard(user: Staff, db: DB):
    return {
        "tickets": [serialize(t) for t in db.scalars(select(Ticket).order_by(Ticket.created_at.desc()))],
        "refunds": [serialize(r) for r in db.scalars(select(Refund).order_by(Refund.created_at.desc()))],
        "returns": [serialize(r) for r in db.scalars(select(Return))],
        "escalations": [
            escalation_detail(db, e)
            for e in db.scalars(select(Escalation).order_by(Escalation.created_at.desc()))
        ],
        "calls": [serialize(c) for c in db.scalars(select(Call).order_by(Call.created_at.desc()).limit(100))],
        "customers": [
            {**serialize(c), "name": db.get(User, c.user_id).name, "email": db.get(User, c.user_id).email}
            for c in db.scalars(select(Customer))
        ],
    }


@app.get("/staff/customers/{customer_id}")
def customer_detail(customer_id: str, user: Staff, db: DB):
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    return {
        "customer": serialize(customer),
        "orders": [
            order_detail(db, o) for o in db.scalars(select(Order).where(Order.customer_id == customer.id))
        ],
        "tickets": [
            serialize(t) for t in db.scalars(select(Ticket).where(Ticket.customer_id == customer.id))
        ],
    }


@app.patch("/staff/customers/{customer_id}")
def update_customer(customer_id: str, body: CustomerUpdate, user: Staff, db: DB):
    customer = db.get(Customer, customer_id)
    if not customer:
        raise HTTPException(404, "Customer not found")
    customer.notes = body.notes
    customer.preferred_language = body.preferred_language
    audit(db, user.id, "customer_updated", customer.id)
    db.commit()
    return serialize(customer)


@app.patch("/staff/tickets/{ticket_id}")
def update_ticket(ticket_id: str, body: TicketUpdate, user: Staff, db: DB):
    ticket = db.get(Ticket, ticket_id)
    if not ticket:
        raise HTTPException(404, "Ticket not found")
    ticket.status = body.status
    ticket.notes = body.notes
    if body.assign_to_me:
        ticket.assigned_to = user.id
    audit(db, user.id, "ticket_updated", ticket.customer_id, ticket.call_id, ticket_id=ticket.id)
    db.commit()
    return serialize(ticket)


@app.post("/staff/returns/{return_id}/receive")
def receive_return(return_id: str, user: Staff, db: DB):
    ret = db.scalar(select(Return).where(Return.id == return_id).with_for_update())
    if not ret:
        raise HTTPException(404, "Return not found")
    if ret.status != "received":
        ret.status = "received"
        order = db.get(Order, ret.order_id)
        audit(db, user.id, "return_received", order.customer_id, return_id=ret.id)
    db.commit()
    return serialize(ret)


@app.post("/staff/refunds/{refund_id}/decision")
def decide_refund(refund_id: str, body: DecisionInput, user: Staff, db: DB):
    refund = db.scalar(select(Refund).where(Refund.id == refund_id).with_for_update())
    if not refund:
        raise HTTPException(404, "Refund not found")
    if refund.status != "pending_approval":
        raise HTTPException(409, "Refund already decided")
    refund.status = "approved" if body.decision == "approve" else "rejected"
    refund.decided_by = user.id
    refund.decision_reason = body.reason
    order = db.get(Order, refund.order_id)
    audit(db, user.id, "refund_decided", order.customer_id, refund_id=refund.id, decision=body.decision)
    db.commit()
    return serialize(refund)


@app.post("/staff/escalations/{escalation_id}/claim")
def claim_escalation(escalation_id: str, user: Staff, db: DB):
    result = db.execute(
        update(Escalation)
        .where(
            Escalation.id == escalation_id, Escalation.status == "queued", Escalation.deadline > time.time()
        )
        .values(status="claimed", assigned_to=user.id)
    )
    if result.rowcount != 1:
        raise HTTPException(409, "Escalation already claimed or expired")
    esc = db.get(Escalation, escalation_id)
    call = db.get(Call, esc.call_id)
    audit(db, user.id, "escalation_claimed", call.customer_id, call.id)
    db.commit()
    return serialize(esc)


@app.post("/staff/escalations/{escalation_id}/join", response_model=ConnectionOut)
def join_escalation(escalation_id: str, user: Staff, db: DB):
    esc = db.scalar(select(Escalation).where(Escalation.id == escalation_id).with_for_update())
    if not esc or esc.assigned_to != user.id:
        raise HTTPException(403, "Only the assigned representative can join")
    if esc.status not in {"claimed", "connecting", "active"}:
        raise HTTPException(409, "Escalation is unavailable")
    if esc.status != "active" and esc.deadline < time.time():
        raise HTTPException(409, "Escalation expired")
    call = db.get(Call, esc.call_id)
    if esc.status != "active":
        esc.status = "connecting"
    db.commit()
    return {
        "call": serialize(call),
        "url": settings().livekit_url,
        "token": lk.join_token(call, "staff-" + user.id, user.name),
        "escalation_id": esc.id,
    }


@app.get("/staff/analytics")
def analytics(user: Staff, db: DB):
    grouped = {}
    for metric in db.scalars(select(Metric)):
        grouped.setdefault(metric.name, []).append(metric.value)

    def aggregate(values):
        values = sorted(values)
        import math

        return {
            "count": len(values),
            "mean": sum(values) / len(values),
            "p95": values[max(0, math.ceil(len(values) * 0.95) - 1)],
        }

    return {
        "calls": db.scalar(select(func.count()).select_from(Call)),
        "metrics": {key: aggregate(values) for key, values in grouped.items()},
        "handoffs": {
            status: count
            for status, count in db.execute(
                select(Escalation.status, func.count()).group_by(Escalation.status)
            )
        },
    }


@app.get("/events")
async def events(request: Request, auth: Auth):
    user_id, role = auth[0].id, auth[0].role
    session_id = auth[1].id

    async def stream():
        last = ""
        while not await request.is_disconnected():
            with SessionLocal() as db:
                session = db.get(LoginSession, session_id)
                if not session or session.expires_at < time.time():
                    yield "event: session_expired\ndata: {}\n\n"
                    return
                query = select(Audit.id, Audit.created_at).order_by(Audit.created_at.desc()).limit(1)
                if role != "staff":
                    customer = db.scalar(select(Customer).where(Customer.user_id == user_id))
                    query = query.where(Audit.customer_id == customer.id)
                latest = db.execute(query).first()
                stamp = str(latest) if latest else "initial"
                if stamp != last:
                    last = stamp
                    yield f"event: refresh\ndata: {json.dumps({'version': stamp})}\n\n"
                else:
                    yield ": heartbeat\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@app.get("/internal/context")
def agent_context(call: AgentCall, db: DB):
    esc = db.scalar(select(Escalation).where(Escalation.call_id == call.id))
    return {
        "call": serialize(call),
        "verified": bool(verified(db, call.id)),
        "orders": [
            order_detail(db, o)
            for o in db.scalars(select(Order).where(Order.customer_id == call.customer_id))
        ],
        "tickets": [
            serialize(t) for t in db.scalars(select(Ticket).where(Ticket.customer_id == call.customer_id))
        ],
        "actions": [
            serialize(a) for a in db.scalars(select(PendingAction).where(PendingAction.call_id == call.id))
        ],
        "escalation": serialize(esc) if esc else None,
    }


@app.get("/internal/knowledge", response_model=KnowledgeResponse)
def agent_knowledge(
    call: AgentCall, db: DB, q: str | None = Query(default=None, min_length=1, max_length=500)
):
    if q is not None and not q.strip():
        raise HTTPException(422, "Knowledge question cannot be blank")
    result = retrieve(db, q, call_id=call.id)
    db.commit()
    return result


@app.post("/internal/actions", response_model=ActionOut)
def agent_prepare(body: ActionInput, call: AgentCall, db: DB):
    action = prepare_action(db, call, body.kind, body.payload(), body.request_id)
    db.commit()
    return serialize(action)


@app.post("/internal/escalate")
def agent_escalate(body: ReasonInput, call: AgentCall, db: DB):
    call = db.scalar(
        select(Call).where(Call.id == call.id).with_for_update().execution_options(populate_existing=True)
    )
    esc = db.scalar(select(Escalation).where(Escalation.call_id == call.id))
    if not esc:
        esc = Escalation(call_id=call.id, reason=body.reason, deadline=time.time() + HANDOFF_TIMEOUT_SECONDS)
        db.add(esc)
    elif esc.status == "unavailable":
        raise HTTPException(409, "No representative available; offer a confirmed callback ticket")
    call.status = "handoff_pending"
    call.summary = body.reason
    for action in db.scalars(
        select(PendingAction).where(PendingAction.call_id == call.id, PendingAction.status == "pending")
    ):
        action.status = "cancelled"
    audit(db, "agent", "handoff_requested", call.customer_id, call.id)
    db.commit()
    return serialize(esc)


@app.post("/internal/transcripts")
def agent_transcript(body: TranscriptInput, call: LifecycleCall, db: DB):
    existing = db.scalar(
        select(Transcript).where(Transcript.call_id == call.id, Transcript.event_id == body.event_id)
    )
    if not existing:
        db.add(Transcript(call_id=call.id, **body.model_dump()))
        audit(db, "agent", "transcript_added", call.customer_id, call.id)
    db.commit()
    return {"ok": True}


@app.post("/internal/metrics")
def agent_metric(body: MetricInput, call: LifecycleCall, db: DB):
    db.add(Metric(call_id=call.id, **body.model_dump()))
    db.commit()
    return {"ok": True}


@app.post("/internal/summary")
def agent_summary(body: SummaryInput, call: LifecycleCall, db: DB):
    call.summary = body.summary
    db.commit()
    return {"ok": True}


@app.post("/internal/ready")
def agent_ready(call: AgentCall, db: DB):
    if call.status == "connecting":
        call.status = "active"
        audit(db, "agent", "agent_ready", call.customer_id, call.id)
        db.commit()
    return {"ok": True}


@app.post("/internal/handoff/ack")
def agent_handoff_ack(call: AgentCall, db: DB):
    call = db.scalar(
        select(Call).where(Call.id == call.id).with_for_update().execution_options(populate_existing=True)
    )
    esc = db.scalar(select(Escalation).where(Escalation.call_id == call.id).with_for_update())
    if (
        not esc
        or not esc.representative_connected
        or esc.status != "connecting"
        or esc.deadline < time.time()
    ):
        raise HTTPException(409, "Representative has not connected media")
    # Worker disables its I/O before this acknowledgment. Epoch invalidates all its credentials.
    esc.status = "active"
    call.status = "human_active"
    call.agent_epoch += 1
    audit(db, "agent", "human_takeover_active", call.customer_id, call.id)
    db.commit()
    return {"ok": True}


@app.post("/internal/failure")
def agent_failure(call: AgentCall, db: DB):
    end_call(db, call, "failed")
    db.commit()
    return {"ok": True}


@app.post("/webhooks/livekit")
async def livekit_webhook(request: Request, db: DB):
    cfg = settings()
    try:
        receiver = lkapi.WebhookReceiver(lkapi.TokenVerifier(cfg.livekit_api_key, cfg.livekit_api_secret))
        event = receiver.receive((await request.body()).decode(), request.headers.get("authorization", ""))
    except Exception:
        raise HTTPException(401, "Invalid webhook signature")
    if not event.id:
        raise HTTPException(400, "Webhook event ID required")
    if db.get(WebhookReceipt, event.id):
        return {"ok": True}
    call = db.scalar(select(Call).where(Call.room == event.room.name).with_for_update())
    db.add(WebhookReceipt(id=event.id))
    if call:
        identity = event.participant.identity
        esc = db.scalar(select(Escalation).where(Escalation.call_id == call.id).with_for_update())
        if event.event == "track_published" and esc and identity == "staff-" + str(esc.assigned_to):
            # An authenticated server webhook proves the assigned rep published an audio track.
            from livekit.protocol.models import TrackType

            if (
                event.track.type == TrackType.AUDIO
                and esc.status == "connecting"
                and esc.deadline > time.time()
            ):
                esc.representative_connected = True
                audit(db, "livekit", "representative_media_connected", call.customer_id, call.id)
        if event.event == "participant_left":
            if identity == "customer-" + call.customer_id:
                end_call(db, call)
            elif esc and identity == "staff-" + str(esc.assigned_to):
                esc.representative_connected = False
                audit(db, "livekit", "representative_disconnected", call.customer_id, call.id)
        if event.event == "room_finished":
            end_call(db, call)
    db.commit()
    return {"ok": True}


@app.post("/staff/faults/{call_id}/{fault}")
async def inject_fault(call_id: str, fault: str, user: Staff, db: DB):
    if not settings().enable_fault_injection or not settings().demo_mode:
        raise HTTPException(404, "Not found")
    call = owned_call(db, user, call_id)
    if fault == "model_disconnect":
        await lk.remove_participant(call, "agent-" + call.id)
        end_call(db, call, "failed")
    elif fault in {"backend_timeout", "database_error"}:
        audit(db, user.id, "fault_requested", call.customer_id, call.id, fault=fault)
    else:
        raise HTTPException(400, "Unknown fault")
    db.commit()
    return {"fault": fault, "call_id": call.id}


@app.post("/internal/handoff/media")
def agent_observed_media(body: dict, call: AgentCall, db: DB):
    esc = db.scalar(select(Escalation).where(Escalation.call_id == call.id).with_for_update())
    if (
        not esc
        or esc.status != "connecting"
        or esc.deadline < time.time()
        or body.get("identity") != "staff-" + str(esc.assigned_to)
    ):
        raise HTTPException(409, "Assigned representative is not connecting")
    esc.representative_connected = True
    db.commit()
    return {"ok": True}


@app.post("/internal/customer-left")
async def agent_customer_left(call: LifecycleCall, db: DB):
    call = db.scalar(
        select(Call).where(Call.id == call.id).with_for_update().execution_options(populate_existing=True)
    )
    end_call(db, call)
    db.commit()
    try:
        await asyncio.wait_for(lk.delete_room(call), 5)
    except Exception:
        log.exception("customer_exit_cleanup_failed call_id=%s", call.id)
    return {"ok": True}


@app.post("/calls/{call_id}/metrics")
def browser_metric(call_id: str, body: MetricInput, auth: Auth, db: DB):
    call = owned_call(db, auth[0], call_id)
    if (
        body.name not in {"audio_response_seconds", "audio_interruption_seconds"}
        or not 0 <= body.value <= 120
    ):
        raise HTTPException(400, "Unsupported browser metric")
    db.add(
        Metric(
            call_id=call.id,
            name=body.name,
            value=body.value,
            tags={"source": "browser_audio_energy", "tool_turn": body.tags.get("tool_turn", "unknown")},
        )
    )
    db.commit()
    return {"ok": True}


@app.post("/internal/representative-left")
def representative_left(call: LifecycleCall, db: DB):
    esc = db.scalar(select(Escalation).where(Escalation.call_id == call.id).with_for_update())
    if esc:
        esc.representative_connected = False
        audit(db, "agent", "representative_disconnected", call.customer_id, call.id)
        db.commit()
    return {"ok": True}


@app.post("/internal/representative-rejoined")
def representative_rejoined(body: dict, call: LifecycleCall, db: DB):
    esc = db.scalar(select(Escalation).where(Escalation.call_id == call.id).with_for_update())
    if esc and esc.status == "active" and body.get("identity") == "staff-" + str(esc.assigned_to):
        esc.representative_connected = True
        audit(db, "agent", "representative_reconnected", call.customer_id, call.id)
        db.commit()
    return {"ok": True}


@app.get("/staff/calls/{call_id}/audit")
def call_audit(call_id: str, user: Staff, db: DB):
    owned_call(db, user, call_id)
    return [
        serialize(a)
        for a in db.scalars(select(Audit).where(Audit.call_id == call_id).order_by(Audit.created_at))
    ]
