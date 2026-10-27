import time
from .business_rules import RETURN_WINDOW_DAYS, ACTION_TTL_SECONDS
from fastapi import HTTPException
from sqlalchemy import select
from .models import (
    Audit,
    Call,
    Customer,
    Escalation,
    Order,
    OrderItem,
    PendingAction,
    Product,
    Refund,
    Return,
    Ticket,
    Transcript,
    User,
    Verification,
)


def serialize(obj):
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns}


def audit(db, actor, event, customer_id=None, call_id=None, **details):
    db.add(Audit(actor=actor, event=event, customer_id=customer_id, call_id=call_id, details=details))


def customer_for(db, user):
    customer = db.scalar(select(Customer).where(Customer.user_id == user.id))
    if not customer:
        raise HTTPException(403, "Customer account required")
    return customer


def owned_call(db, user, call_id, lock=False):
    query = select(Call).where(Call.id == call_id)
    if lock:
        query = query.with_for_update()
    call = db.scalar(query)
    if not call or (user.role != "staff" and call.customer_id != customer_for(db, user).id):
        raise HTTPException(404, "Call not found")
    return call


def owned_order(db, customer_id, order_id):
    order = db.get(Order, order_id)
    if not order or order.customer_id != customer_id:
        raise HTTPException(404, "Order not found")
    return order


def order_detail(db, order):
    data = serialize(order)
    data["items"] = [
        {**serialize(item), "product": serialize(db.get(Product, item.product_id))}
        for item in db.scalars(select(OrderItem).where(OrderItem.order_id == order.id))
    ]
    ret = db.scalar(select(Return).where(Return.order_id == order.id))
    refund = db.scalar(select(Refund).where(Refund.order_id == order.id))
    data["return"] = serialize(ret) if ret else None
    data["refund"] = serialize(refund) if refund else None
    data["return_eligibility"] = eligibility(db, order)
    return data


def eligibility(db, order):
    if order.status != "delivered" or order.delivered_at is None:
        return {"eligible": False, "reason": "Order has not been delivered"}
    if time.time() - order.delivered_at > RETURN_WINDOW_DAYS * 86400:
        return {"eligible": False, "reason": f"The {RETURN_WINDOW_DAYS}-day return window has closed"}
    items = list(db.scalars(select(OrderItem).where(OrderItem.order_id == order.id)))
    if not items or any(not db.get(Product, item.product_id).returnable for item in items):
        return {"eligible": False, "reason": "Order contains a non-returnable item"}
    if db.scalar(select(Return).where(Return.order_id == order.id)):
        return {"eligible": False, "reason": "A return already exists"}
    return {"eligible": True, "reason": f"Eligible within {RETURN_WINDOW_DAYS} days of delivery"}


def verified(db, call_id):
    return db.scalar(
        select(Verification).where(
            Verification.call_id == call_id,
            Verification.consumed.is_(True),
            Verification.verified_until > time.time(),
        )
    )


def validate_action(db, call, kind, payload):
    if kind in {"return", "refund"}:
        order = owned_order(db, call.customer_id, payload["order_id"])
        if kind == "return":
            result = eligibility(db, order)
            if not result["eligible"]:
                raise HTTPException(409, result["reason"])
        else:
            ret = db.scalar(select(Return).where(Return.order_id == order.id))
            if not ret or ret.status != "received":
                raise HTTPException(409, "A received return is required before requesting a refund")
            if db.scalar(select(Refund).where(Refund.order_id == order.id)):
                raise HTTPException(409, "Refund request already exists; check its status")


def prepare_action(db, call, kind, payload, request_id):
    # Lock the call to serialize prepare/confirm against takeover and other mutations.
    call = db.scalar(
        select(Call).where(Call.id == call.id).with_for_update().execution_options(populate_existing=True)
    )
    if call.status not in {"connecting", "active"}:
        raise HTTPException(409, "AI actions are unavailable during handoff or after the call")
    existing = db.get(PendingAction, request_id)
    if existing:
        if existing.call_id != call.id or existing.kind != kind or existing.payload != payload:
            raise HTTPException(409, "Idempotency key belongs to another action")
        return existing
    validate_action(db, call, kind, payload)
    for older in db.scalars(
        select(PendingAction).where(PendingAction.call_id == call.id, PendingAction.status == "pending")
    ):
        older.status = "superseded"
    action = PendingAction(
        id=request_id,
        call_id=call.id,
        kind=kind,
        payload=payload,
        expires_at=time.time() + ACTION_TTL_SECONDS,
    )
    db.add(action)
    audit(db, "agent", "action_prepared", call.customer_id, call.id, action_id=action.id, kind=kind)
    db.flush()
    return action


def confirm_action(db, call, action_id, actor):
    # Customer row also serializes actions for different calls belonging to this customer.
    db.scalar(select(Customer).where(Customer.id == call.customer_id).with_for_update())
    action = db.scalar(select(PendingAction).where(PendingAction.id == action_id).with_for_update())
    if not action or action.call_id != call.id:
        raise HTTPException(404, "Action not found")
    if action.status == "completed":
        return action.result
    if call.status not in {"active", "connecting"}:
        raise HTTPException(409, "Call is no longer controlled by the AI")
    if action.status != "pending" or action.expires_at < time.time():
        raise HTTPException(409, "Action expired or was replaced; ask the agent to prepare it again")
    verification = verified(db, call.id)
    if not verification:
        raise HTTPException(403, "Complete portal identity verification first")
    validate_action(db, call, action.kind, action.payload)
    p = action.payload
    if action.kind == "return":
        obj = Return(order_id=p["order_id"], reason=p["reason"])
    elif action.kind == "refund":
        order = owned_order(db, call.customer_id, p["order_id"])
        obj = Refund(order_id=order.id, amount_paise=order.total_paise, reason=p["reason"])
    else:
        obj = Ticket(
            customer_id=call.customer_id, call_id=call.id, title=p["title"], description=p["description"]
        )
    db.add(obj)
    db.flush()
    verification.verified_until = None  # A verification authorizes one confirmed action only.
    action.status = "completed"
    action.result = {"id": obj.id, "kind": action.kind, "status": obj.status}
    audit(db, actor, "action_confirmed", call.customer_id, call.id, action_id=action.id, result=action.result)
    return action.result


def expire_escalations(db):
    rows = list(
        db.scalars(
            select(Escalation).where(
                Escalation.status.in_(["queued", "claimed", "connecting"]), Escalation.deadline < time.time()
            )
        )
    )
    for candidate in rows:
        # Always lock call before escalation, matching takeover and disconnect handlers.
        call = db.scalar(
            select(Call)
            .where(Call.id == candidate.call_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        row = db.scalar(
            select(Escalation)
            .where(Escalation.id == candidate.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row.status not in {"queued", "claimed", "connecting"} or row.deadline >= time.time():
            continue
        row.status = "unavailable"
        if call.status not in {"ended", "failed", "human_active"}:
            call.status = "active"
        audit(db, "system", "handoff_unavailable", call.customer_id, call.id)


def end_call(db, call, status="ended"):
    if call.status in {"ended", "failed"}:
        return
    call.status = status
    call.ended_at = time.time()
    call.agent_epoch += 1
    esc = db.scalar(select(Escalation).where(Escalation.call_id == call.id))
    if esc:
        esc.status = "completed" if esc.status == "active" else "cancelled"
    for action in db.scalars(
        select(PendingAction).where(PendingAction.call_id == call.id, PendingAction.status == "pending")
    ):
        action.status = "cancelled"
    turns = list(
        db.scalars(select(Transcript).where(Transcript.call_id == call.id).order_by(Transcript.created_at))
    )
    if not call.summary:
        issues = [t.text for t in turns if t.role == "user"][-3:]
        call.summary = (
            "Customer issues: " + " | ".join(issues)
            if issues
            else "Call ended without a captured transcript."
        )
    completed = list(
        db.scalars(
            select(PendingAction).where(PendingAction.call_id == call.id, PendingAction.status == "completed")
        )
    )
    if completed:
        call.summary += " Completed actions: " + "; ".join(
            f"{a.kind}: {a.result['status']} ({a.result['id']})" for a in completed
        )
    if esc:
        call.summary += f" Human handoff: {esc.status}."
    audit(db, "system", "call_ended", call.customer_id, call.id, status=status)


def escalation_detail(db, esc):
    call = db.get(Call, esc.call_id)
    customer = db.get(Customer, call.customer_id)
    user = db.get(User, customer.user_id)
    return {
        **serialize(esc),
        "call": serialize(call),
        "customer": {"id": customer.id, "name": user.name},
        "verified": bool(verified(db, call.id)),
        "actions": [
            serialize(a) for a in db.scalars(select(PendingAction).where(PendingAction.call_id == call.id))
        ],
    }
