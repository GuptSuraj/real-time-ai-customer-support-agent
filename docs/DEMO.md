# Demonstration script

Start the stack, run credential preflight, and open customer/staff portals in separate browser profiles. Use headphones. Keep the worker logs visible in a separate terminal.

## 1. Refund delay and a confirmed support ticket

1. Sign in as `aarav@example.com`.
2. Start an English call. Say: “I returned my headphones five days ago, but I haven't received my refund. My order is ORD-1001.”
3. Mira should check the record and explain that it is processing. It must not promise a payment date.
4. Ask Mira to prepare a ticket. Check the exact proposed title and description in the call panel.
5. Click **Verify identity**, enter the displayed demo code in the portal, then **Confirm this action**.
6. Confirm the ticket appears in both portals. End the call and review its transcript and summary.

## 2. A real return workflow

1. Start another call and request a return for `ORD-1003` because it is no longer needed.
2. Verify and confirm the exact proposal. A real return row should appear.
3. In the staff workspace, open **Tickets & approvals** and mark that return received.
4. Ask Mira to prepare a refund request for the received return. Confirm it as the customer.
5. The request must show **pending approval**, with no money issued.
6. As staff, enter a reason and approve. Watch the simulated states move through approved, processing and completed.

Use `ORD-1007` to demonstrate an already-received return without first creating a return. `ORD-1004` and `ORD-1005` demonstrate rejected eligibility.

## 3. Human takeover in the same room

1. Ask Mira: “Please connect me to a human about my refund.”
2. In the staff workspace, review the customer summary and completed actions.
3. Click **Accept**, then **Join call**, and allow microphone access.
4. Verify that the staff microphone opens only after takeover is active and AI audio stops.
5. Speak to the customer. Leave the room and reconnect using the same assignment; the AI must stay stopped.
6. Add resolution notes to the ticket. End the customer's call.

For the no-staff path, leave an escalation unaccepted for 60 seconds. Mira should offer a callback ticket. The customer must confirm it before it exists.

## 4. Hindi and interruptions

Start a Hindi call and say: “मेरे ऑर्डर ORD-1002 की स्थिति क्या है?” Switch to English midway. While Mira explains a policy, interrupt with: “Wait, just check my refund instead.” The agent should stop speaking and follow the new request. Check the available-turn transcript's interrupted marker.

## 5. Failure injection and load

Set `ENABLE_FAULT_INJECTION=true` only for a local demo and restart the API. The staff-only endpoint accepts `backend_timeout`, `database_error`, or `model_disconnect`:

```text
POST /staff/faults/{call_id}/{fault}
```

The timeout/error affects the next internal context/action/knowledge operation and is one-shot. The worker's background poll may consume it; the tool client must still remain bounded and recover safely. Model disconnection ends the call as failed. Faults are disabled by default.

Run `scripts/load_calls.py` against the actual configured API to hold five distinct authenticated rooms concurrently. The script verifies workers become active; use spoken audio scenarios separately to evaluate task quality and latency under load.

## Resetting

Seeding is idempotent and does not overwrite changed business records. For a fresh Docker demonstration, explicitly remove the named Compose volume with `docker compose down -v`, then start again. This deletes all local demo history.

Automated evaluation resets are restricted to a dedicated database named `support_eval` or `support_eval.db`; see the evaluation guide.
