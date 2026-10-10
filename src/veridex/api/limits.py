"""Bound chat admission, body reads, and total elapsed HTTP time in the request task.

The deadline starts at ASGI entry, including queueing, body parsing and session-lock
waits. Cooperative cancellation permits AgentService history repair before a 504;
cleanup can exceed the HTTP deadline if a provider ignores cancellation. Lifespan
retains its independent total shutdown budget. These are per-process limits, not
per-user quotas, authentication, or a checkpoint retention policy.
"""

import asyncio
from contextlib import asynccontextmanager

from starlette.responses import JSONResponse


class RequestRejected(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail


class Admission:
    """Event-loop-local bounded semaphore with a bounded FIFO waiting population."""

    def __init__(self, config):
        self.config = config
        self.active = 0
        self.waiting = 0
        self._semaphore = asyncio.Semaphore(config.api_max_active_requests)

    @asynccontextmanager
    async def acquire(self):
        queued = self.active >= self.config.api_max_active_requests or self.waiting > 0
        if queued:
            if self.waiting >= self.config.api_max_waiting_requests:
                raise RequestRejected(429, "Too many requests.")
            self.waiting += 1
        try:
            if queued:
                try:
                    async with asyncio.timeout(self.config.api_queue_timeout_seconds):
                        await self._semaphore.acquire()
                except TimeoutError:
                    raise RequestRejected(504, "Request queue wait timed out.") from None
            else:
                await self._semaphore.acquire()
        finally:
            if queued:
                self.waiting -= 1
        self.active += 1
        try:
            yield
        finally:
            self.active -= 1
            self._semaphore.release()


class ChatLimitsMiddleware:
    """Pure ASGI middleware: no extra request tasks or unbounded body buffering."""

    def __init__(self, app, *, state, config):
        self.app = app
        self.state = state
        self.config = config

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or scope["method"] != "POST"
            or scope["path"].rstrip("/") != "/chat"
        ):
            await self.app(scope, receive, send)
            return
        task = asyncio.current_task()
        self.state.chat_tasks.add(task)
        deadline = asyncio.timeout(self.config.api_request_timeout_seconds)
        started = False

        async def tracked_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            async with deadline:
                self.check_available()
                lengths = [v for k, v in scope["headers"] if k.lower() == b"content-length"]
                if lengths:
                    if len(lengths) != 1 or not lengths[0].isdigit():
                        raise RequestRejected(400, "Invalid request headers.")
                    # Avoid parsing unbounded integers from untrusted headers.
                    value = lengths[0].lstrip(b"0") or b"0"
                    if len(value) > 10 or int(value) > self.config.api_max_request_body_bytes:
                        raise RequestRejected(413, "Request body is too large.")
                async with self.state.admission.acquire():
                    self.check_available()
                    body = bytearray()
                    while True:
                        message = await receive()
                        if message["type"] == "http.disconnect":
                            raise asyncio.CancelledError
                        chunk = message.get("body", b"")
                        if len(body) + len(chunk) > self.config.api_max_request_body_bytes:
                            raise RequestRejected(413, "Request body is too large.")
                        body.extend(chunk)
                        if not message.get("more_body", False):
                            break
                    delivered = False

                    async def replay():
                        nonlocal delivered
                        if not delivered:
                            delivered = True
                            return {"type": "http.request", "body": bytes(body), "more_body": False}
                        return await receive()

                    await self.app(scope, replay, tracked_send)
        except RequestRejected as exc:
            await JSONResponse(
                {"detail": exc.detail},
                status_code=exc.status_code,
                headers={"Retry-After": "1"} if exc.status_code == 429 else None,
            )(scope, receive, send)
        except TimeoutError:
            if started:
                raise  # A response already began; never emit a second response.
            await JSONResponse({"detail": "Request deadline exceeded."}, status_code=504)(
                scope, receive, send
            )
        finally:
            self.state.chat_tasks.discard(task)

    def check_available(self):
        if self.state.shutting_down:
            raise RequestRejected(503, "Agent service is unavailable.")
