import asyncio
import httpx
import pytest
from support_agent.client import Backend


async def make_backend(handler):
    backend = Backend("http://backend", "test", "call-test")
    await backend.http.aclose()
    backend.http = httpx.AsyncClient(base_url="http://backend", transport=httpx.MockTransport(handler))
    return backend


async def test_read_retries_once_and_records_metric():
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(503 if len(calls) == 1 else 200, json={"ok": True})

    backend = await make_backend(handler)
    observed = []
    backend.on_metric = lambda *args: observed.append(args)
    assert await backend.context() == {"ok": True}
    assert len(calls) == 2
    assert observed[0][0] == "tool_latency_seconds"
    await backend.close()


async def test_write_reuses_identical_idempotency_key_on_retry():
    requests = []

    async def handler(request):
        requests.append(request.content)
        return httpx.Response(503 if len(requests) == 1 else 200, json={"id": "action-1"})

    backend = await make_backend(handler)
    assert await backend.prepare("ticket", title="Issue", description="Test issue") == {"id": "action-1"}
    assert len(requests) == 2
    assert requests[0] == requests[1]
    await backend.close()


async def test_non_idempotent_write_is_not_retried():
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(503)

    backend = await make_backend(handler)
    with pytest.raises(httpx.HTTPStatusError):
        await backend.request("POST", "/internal/escalate", {"reason": "Help"})
    assert len(calls) == 1
    await backend.close()


async def test_total_deadline_includes_slow_request():
    async def handler(request):
        await asyncio.sleep(6)
        return httpx.Response(200, json={})

    backend = await make_backend(handler)
    started = asyncio.get_running_loop().time()
    with pytest.raises(TimeoutError):
        await backend.context()
    assert asyncio.get_running_loop().time() - started < 5.5
    await backend.close()


async def test_authorization_failure_is_not_retried():
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(403, json={"detail": "Agent no longer controls this call"})

    backend = await make_backend(handler)
    with pytest.raises(httpx.HTTPStatusError):
        await backend.context()
    assert len(calls) == 1
    await backend.close()
