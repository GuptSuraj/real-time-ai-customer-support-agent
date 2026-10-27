import asyncio
import time
import uuid
import httpx
from opentelemetry import trace
from opentelemetry.propagate import inject


class Backend:
    """Five-second total operation deadline, including one safe retry."""

    def __init__(self, url, token, call_id, on_metric=None):
        self.call_id = call_id
        self.http = httpx.AsyncClient(base_url=url, headers={"Authorization": f"Bearer {token}"}, timeout=4)
        self.on_metric = on_metric
        self.tracer = trace.get_tracer("support-agent")

    async def request(self, method, path, body=None, *, idempotent=False, operation=None):
        started = time.monotonic()
        with self.tracer.start_as_current_span("backend." + path.strip("/").replace("/", ".")) as span:
            span.set_attribute("call.id", self.call_id)
            span.set_attribute("http.request.method", method)
            try:
                async with asyncio.timeout(5):
                    for attempt in range(2):
                        try:
                            headers = {"X-Agent-Operation": operation} if operation else {}
                            inject(headers)
                            response = await self.http.request(method, path, json=body, headers=headers)
                            if (
                                response.status_code >= 500
                                and attempt == 0
                                and (method == "GET" or idempotent)
                            ):
                                await asyncio.sleep(0.15)
                                continue
                            response.raise_for_status()
                            return response.json()
                        except (httpx.TimeoutException, httpx.NetworkError):
                            if attempt or not (method == "GET" or idempotent):
                                raise
                            await asyncio.sleep(0.15)
            except Exception as exc:
                span.record_exception(exc)
                raise
            finally:
                elapsed = time.monotonic() - started
                span.set_attribute("tool.duration_seconds", elapsed)
                if self.on_metric and operation:
                    self.on_metric(
                        "tool_latency_seconds", elapsed, {"operation": operation, "method": method}
                    )

    async def context(self, *, tool=True):
        return await self.request(
            "GET", "/internal/context", operation="check_support_context" if tool else None
        )

    async def prepare(self, kind, **payload):
        return await self.request(
            "POST",
            "/internal/actions",
            {"request_id": str(uuid.uuid4()), "kind": kind, **payload},
            idempotent=True,
            operation={
                "return": "prepare_return_request",
                "refund": "prepare_refund_request",
                "ticket": "prepare_support_ticket",
            }[kind],
        )

    async def close(self):
        await self.http.aclose()
