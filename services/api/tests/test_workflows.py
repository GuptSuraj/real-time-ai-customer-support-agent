import time
import uuid
import pytest
from sqlalchemy import func, select
from conftest import sign_in, verify
from support_api.domain import expire_escalations
from support_api.models import Audit, Call, Escalation, PendingAction, Refund, Return, Ticket, Verification


def prepare(client, headers, kind="ticket", **payload):
    if not payload:
        payload = {"title": "Refund delay", "description": "Headphones refund still processing"}
    return client.post(
        "/internal/actions", headers=headers, json={"request_id": str(uuid.uuid4()), "kind": kind, **payload}
    )


def test_authentication_and_csrf(harness):
    client, _ = harness
    assert client.get("/portal").status_code == 401
    assert (
        client.post("/auth/login", json={"email": "aarav@example.com", "password": "wrong"}).status_code
        == 401
    )
    sign_in(client)
    csrf = client.headers.pop("X-CSRF-Token")
    assert client.post("/calls", json={}).status_code == 403
    client.headers["X-CSRF-Token"] = csrf
    assert client.post("/calls", json={}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/auth/logout").status_code == 200
    assert client.get("/portal").status_code == 401


def test_customer_isolation_and_staff_authorization(call):
    client, _, c, headers = call
    context = client.get("/internal/context", headers=headers).json()
    assert {o["id"] for o in context["orders"]} == {f"ORD-100{i}" for i in range(1, 8)}
    assert client.get("/staff/dashboard").status_code == 403
    assert (
        client.post(
            "/staff/refunds/refund-processing/decision", json={"decision": "approve", "reason": "test"}
        ).status_code
        == 403
    )
    assert prepare(client, headers, "return", order_id="ORD-2001", reason="Not needed").status_code == 404
    sign_in(client, "meera@example.com")
    assert client.get(f"/calls/{c['id']}").status_code == 404
    assert client.post(f"/calls/{c['id']}/verification").status_code == 404


@pytest.mark.parametrize(
    "order_id, expected",
    [
        ("ORD-1002", "not been delivered"),
        ("ORD-1004", "window has closed"),
        ("ORD-1005", "non-returnable"),
        ("ORD-1001", "already exists"),
    ],
)
def test_return_rules(call, order_id, expected):
    client, _, _, headers = call
    response = prepare(client, headers, "return", order_id=order_id, reason="No longer required")
    assert response.status_code == 409
    assert expected in response.json()["detail"]


def test_prepare_never_writes_and_confirmation_requires_verification(call):
    client, factory, c, headers = call
    action = prepare(client, headers).json()
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Ticket)) == 1
    url = f"/calls/{c['id']}/actions/{action['id']}/confirm"
    assert client.post(url).status_code == 403
    verify(client, c["id"])
    result = client.post(url)
    assert result.status_code == 200
    assert client.post(url).json() == result.json()
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Ticket)) == 2
        assert (
            db.scalar(select(func.count()).select_from(Audit).where(Audit.event == "action_confirmed")) == 1
        )
    assert client.get(f"/calls/{c['id']}").json()["verified"] is False


def test_new_proposal_invalidates_old_and_cross_call_cannot_confirm(call):
    client, factory, c, headers = call
    first = prepare(client, headers).json()
    second = prepare(
        client, headers, "ticket", title="Different request", description="Delivery is delayed"
    ).json()
    verify(client, c["id"])
    assert client.post(f"/calls/{c['id']}/actions/{first['id']}/confirm").status_code == 409
    assert client.post(f"/calls/{c['id']}/actions/{second['id']}/confirm").status_code == 200


def test_idempotency_key_cannot_be_reused_for_different_payload(call):
    client, _, _, headers = call
    body = {
        "request_id": str(uuid.uuid4()),
        "kind": "ticket",
        "title": "One issue",
        "description": "Please help with issue one",
    }
    one = client.post("/internal/actions", headers=headers, json=body)
    two = client.post("/internal/actions", headers=headers, json=body)
    assert one.json()["id"] == two.json()["id"]
    body["title"] = "Another issue"
    assert client.post("/internal/actions", headers=headers, json=body).status_code == 409


def test_action_expiry_and_decline(call):
    client, factory, c, headers = call
    action = prepare(client, headers).json()
    verify(client, c["id"])
    with factory() as db:
        db.get(PendingAction, action["id"]).expires_at = time.time() - 1
        db.commit()
    assert client.post(f"/calls/{c['id']}/actions/{action['id']}/confirm").status_code == 409
    fresh = prepare(client, headers).json()
    assert client.post(f"/calls/{c['id']}/actions/{fresh['id']}/cancel").status_code == 200
    assert client.post(f"/calls/{c['id']}/actions/{fresh['id']}/confirm").status_code == 409


def test_challenge_expiry_replay_and_brute_force(call):
    client, factory, c, _ = call
    challenge = verify(client, c["id"])
    url = f"/calls/{c['id']}/verification/complete"
    assert (
        client.post(
            url, json={"challenge_id": challenge["challenge_id"], "code": challenge["demo_code"]}
        ).status_code
        == 409
    )
    challenge = client.post(f"/calls/{c['id']}/verification").json()
    wrong = "000000" if challenge["demo_code"] != "000000" else "111111"
    for _ in range(5):
        assert (
            client.post(url, json={"challenge_id": challenge["challenge_id"], "code": wrong}).status_code
            == 400
        )
    assert (
        client.post(
            url, json={"challenge_id": challenge["challenge_id"], "code": challenge["demo_code"]}
        ).status_code
        == 409
    )
    challenge = client.post(f"/calls/{c['id']}/verification").json()
    with factory() as db:
        db.get(Verification, challenge["challenge_id"]).expires_at = 0
        db.commit()
    assert (
        client.post(
            url, json={"challenge_id": challenge["challenge_id"], "code": challenge["demo_code"]}
        ).status_code
        == 409
    )


def test_return_creation_and_duplicate_protection(call):
    client, factory, c, headers = call
    action = prepare(client, headers, "return", order_id="ORD-1003", reason="Not needed").json()
    verify(client, c["id"])
    result = client.post(f"/calls/{c['id']}/actions/{action['id']}/confirm")
    assert result.status_code == 200
    assert prepare(client, headers, "return", order_id="ORD-1003", reason="Not needed").status_code == 409
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Return).where(Return.order_id == "ORD-1003")) == 1


def test_refund_requires_received_return_and_human_approval(call):
    client, factory, c, headers = call
    assert prepare(client, headers, "refund", order_id="ORD-1003", reason="Need refund").status_code == 409
    action = prepare(client, headers, "refund", order_id="ORD-1007", reason="Return received").json()
    verify(client, c["id"])
    response = client.post(f"/calls/{c['id']}/actions/{action['id']}/confirm")
    assert response.json()["status"] == "pending_approval"
    rid = response.json()["id"]
    assert (
        client.post(
            f"/staff/refunds/{rid}/decision",
            json={"decision": "approve", "reason": "Return checked"},
            headers=headers,
        ).status_code
        == 403
    )
    sign_in(client, "support@example.com")
    assert (
        client.post(f"/staff/refunds/{rid}/decision", json={"decision": "approve", "reason": ""}).status_code
        == 422
    )
    assert (
        client.post(
            f"/staff/refunds/{rid}/decision", json={"decision": "approve", "reason": "Return checked"}
        ).json()["status"]
        == "approved"
    )
    assert (
        client.post(
            f"/staff/refunds/{rid}/decision", json={"decision": "approve", "reason": "Again"}
        ).status_code
        == 409
    )
    with factory() as db:
        refund = db.get(Refund, rid)
        assert refund.decided_by == "user-staff"
        assert refund.status != "completed"


def test_live_handoff_gates_media_revokes_agent_and_single_claim(call):
    client, factory, c, headers = call
    esc = client.post(
        "/internal/escalate",
        headers=headers,
        json={"reason": "Customer requests live help; identity unverified; refund unresolved"},
    ).json()
    assert client.post("/internal/handoff/ack", headers=headers).status_code == 409
    assert prepare(client, headers).status_code == 409
    sign_in(client, "support@example.com")
    assert client.post(f"/staff/escalations/{esc['id']}/claim").status_code == 200
    sign_in(client, "support2@example.com")
    assert client.post(f"/staff/escalations/{esc['id']}/claim").status_code == 409
    assert client.post(f"/staff/escalations/{esc['id']}/join").status_code == 403
    sign_in(client, "support@example.com")
    assert client.post(f"/staff/escalations/{esc['id']}/join").status_code == 200
    assert (
        client.post(
            "/internal/handoff/media", headers=headers, json={"identity": "staff-user-staff2"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            "/internal/handoff/media", headers=headers, json={"identity": "staff-user-staff"}
        ).status_code
        == 200
    )
    assert client.post("/internal/handoff/ack", headers=headers).status_code == 200
    assert client.get("/internal/context", headers=headers).status_code == 403
    assert prepare(client, headers).status_code == 403
    with factory() as db:
        assert db.get(Call, c["id"]).status == "human_active"


def test_timeout_returns_to_ai_and_allows_confirmed_callback(call):
    client, factory, c, headers = call
    esc = client.post("/internal/escalate", headers=headers, json={"reason": "Need a human"}).json()
    with factory() as db:
        db.get(Escalation, esc["id"]).deadline = time.time() - 1
        expire_escalations(db)
        db.commit()
        assert db.get(Call, c["id"]).status == "active"
        assert db.get(Escalation, esc["id"]).status == "unavailable"
    assert prepare(client, headers).status_code == 200
    sign_in(client, "support@example.com")
    assert client.post(f"/staff/escalations/{esc['id']}/claim").status_code == 409


def test_end_call_cancels_escalation_actions_and_agent_access(call):
    client, factory, c, headers = call
    action = prepare(client, headers).json()
    esc = client.post("/internal/escalate", headers=headers, json={"reason": "Human please"}).json()
    assert client.post(f"/calls/{c['id']}/end").status_code == 200
    assert client.post(f"/calls/{c['id']}/end").status_code == 200
    assert client.get("/internal/context", headers=headers).status_code == 403
    with factory() as db:
        assert db.get(Escalation, esc["id"]).status == "cancelled"
        assert db.get(PendingAction, action["id"]).status == "cancelled"


def test_transcript_idempotency_and_internal_auth(call):
    client, factory, c, headers = call
    data = {"event_id": "turn-1", "role": "assistant", "text": "May I help?", "interrupted": True}
    assert client.post("/internal/transcripts", json=data).status_code == 401
    for _ in range(2):
        assert client.post("/internal/transcripts", headers=headers, json=data).status_code == 200
    detail = client.get(f"/calls/{c['id']}").json()
    assert len(detail["transcripts"]) == 1
    assert detail["transcripts"][0]["interrupted"] is True


def test_customer_cannot_control_other_call_through_token(call):
    client, factory, c, headers = call
    with factory() as db:
        other = Call(customer_id="cust-meera", room="another-room")
        db.add(other)
        db.commit()
    context = client.get("/internal/context", headers=headers, params={"customer_id": "cust-meera"}).json()
    assert context["call"]["customer_id"] == "cust-aarav"
    assert all(o["customer_id"] == "cust-aarav" for o in context["orders"])


def test_model_cannot_submit_confirmation(call):
    client, _, c, headers = call
    action = prepare(client, headers).json()
    verify(client, c["id"])
    client.cookies.clear()
    assert client.post(f"/calls/{c['id']}/actions/{action['id']}/confirm", headers=headers).status_code == 401


def test_invalid_webhook_rejected(customer):
    client, _ = customer
    assert client.post("/webhooks/livekit", content='{"event":"room_finished"}').status_code == 401


def test_five_customer_rooms_are_isolated(harness):
    client, factory = harness
    from support_api.models import Customer, User
    from support_api.security import passwords

    with factory() as db:
        for i in range(5):
            db.add(
                User(
                    id=f"load-user-{i}",
                    email=f"load{i}@example.com",
                    name=f"Caller {i}",
                    role="customer",
                    password_hash=passwords.hash("Demo-support-2026!"),
                )
            )
        db.flush()
        for i in range(5):
            db.add(Customer(id=f"load-customer-{i}", user_id=f"load-user-{i}"))
        db.commit()
    calls = []
    for i in range(5):
        sign_in(client, f"load{i}@example.com")
        response = client.post("/calls", json={}).json()
        calls.append(response["call"])
    assert len({c["room"] for c in calls}) == 5
    sign_in(client, "load0@example.com")
    for c in calls[1:]:
        assert client.get(f"/calls/{c['id']}").status_code == 404


def test_signed_webhook_is_idempotent_and_cancels_on_disconnect(call, monkeypatch):
    import base64
    import hashlib
    import json
    from livekit import api
    from support_api.config import settings
    from support_api.models import WebhookReceipt

    client, factory, c, headers = call
    monkeypatch.setattr(settings(), "livekit_api_key", "test-key")
    monkeypatch.setattr(settings(), "livekit_api_secret", "test-secret-with-32-characters-123456")
    body = json.dumps(
        {
            "id": "event-disconnect",
            "event": "participant_left",
            "room": {"name": c["room"]},
            "participant": {"identity": "customer-cust-aarav"},
        }
    )
    token = (
        api.AccessToken(settings().livekit_api_key, settings().livekit_api_secret)
        .with_sha256(base64.b64encode(hashlib.sha256(body.encode()).digest()).decode())
        .to_jwt()
    )
    for _ in range(2):
        assert (
            client.post("/webhooks/livekit", content=body, headers={"Authorization": token}).status_code
            == 200
        )
    with factory() as db:
        assert db.get(Call, c["id"]).status == "ended"
        assert db.scalar(select(func.count()).select_from(WebhookReceipt)) == 1
    assert (
        client.post("/webhooks/livekit", content=body + " ", headers={"Authorization": token}).status_code
        == 401
    )


def test_scoped_worker_can_report_disconnect_after_takeover_without_tool_authority(call):
    client, factory, c, headers = call
    with factory() as db:
        row = db.get(Call, c["id"])
        row.status = "human_active"
        row.agent_epoch += 1
        db.add(
            Escalation(
                call_id=row.id,
                reason="Human support",
                status="active",
                assigned_to="user-staff",
                deadline=time.time() + 60,
            )
        )
        db.commit()
    assert client.get("/internal/context", headers=headers).status_code == 403
    assert client.post("/internal/representative-left", headers=headers).status_code == 200
    assert client.post("/internal/customer-left", headers=headers).status_code == 200
    with factory() as db:
        assert db.get(Call, c["id"]).status == "ended"


def test_representative_disconnect_or_timeout_before_ack_cannot_activate_handoff(call):
    client, factory, c, headers = call
    response = client.post(
        "/internal/escalate", headers=headers, json={"reason": "Customer needs a representative"}
    )
    esc_id = response.json()["id"]
    sign_in(client, "support@example.com")
    assert client.post(f"/staff/escalations/{esc_id}/claim").status_code == 200
    assert client.post(f"/staff/escalations/{esc_id}/join").status_code == 200
    assert (
        client.post(
            "/internal/handoff/media", headers=headers, json={"identity": "staff-user-staff"}
        ).status_code
        == 200
    )
    assert client.post("/internal/representative-left", headers=headers).status_code == 200
    assert client.post("/internal/handoff/ack", headers=headers).status_code == 409
    with factory() as db:
        esc = db.get(Escalation, esc_id)
        esc.representative_connected = True
        esc.deadline = time.time() - 1
        db.commit()
    assert client.post("/internal/handoff/ack", headers=headers).status_code == 409
    with factory() as db:
        assert db.get(Call, c["id"]).status == "handoff_pending"
