import asyncio
import json
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import ValidationError
from test_api_lifecycle import Lifespan

from veridex.api.app import create_app
from veridex.config import Settings

pytestmark = pytest.mark.asyncio
BODY = {"query": "Hello", "session_id": "a"}


def config(**kwargs):
    return Settings(_env_file=None, **kwargs)


def client_for(application):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=application), base_url="http://test")


async def wait_count(application, *, active=None, waiting=None):
    async with asyncio.timeout(2):
        while (active is not None and application.state.admission.active != active) or (
            waiting is not None and application.state.admission.waiting != waiting
        ):
            await asyncio.sleep(0.001)


@pytest.mark.parametrize("streamed", [False, True])
async def test_body_byte_boundary_and_oversized_body(streamed):
    service = AsyncMock(achat=AsyncMock(return_value="Answer"))
    application = create_app(agent_service=service, config=config(api_max_request_body_bytes=1024))
    body = json.dumps(BODY).encode()
    boundary = body + b" " * (1024 - len(body))

    async def chunks(data):
        yield data[:100]
        yield data[100:]

    async with client_for(application) as client:
        result = await client.post(
            "/chat",
            content=chunks(boundary) if streamed else boundary,
            headers={"Content-Type": "application/json"},
        )
        assert result.status_code == 200
        service.achat.reset_mock()
        result = await client.post(
            "/chat", content=chunks(boundary + b"x") if streamed else boundary + b"x"
        )
        assert result.status_code == 413
        assert result.json() == {"detail": "Request body is too large."}
        service.achat.assert_not_awaited()
    assert application.state.admission.active == 0


async def test_oversized_actual_body_with_false_content_length():
    service = AsyncMock()
    application = create_app(agent_service=service, config=config(api_max_request_body_bytes=1024))
    async with client_for(application) as client:
        result = await client.post("/chat", content=b"x" * 1025, headers={"Content-Length": "1"})
        assert result.status_code == 413
        service.achat.assert_not_awaited()


@pytest.mark.parametrize("length", ["SECRET", "-1", "1.5"])
async def test_invalid_content_length_is_safe(length):
    application = create_app(agent_service=AsyncMock())
    async with client_for(application) as client:
        result = await client.post("/chat", content=b"{}", headers={"Content-Length": length})
        assert result.status_code == 400
        assert result.json() == {"detail": "Invalid request headers."}


async def test_validation_does_not_echo_rejected_secrets():
    application = create_app(agent_service=AsyncMock())
    async with client_for(application) as client:
        result = await client.post("/chat", json={**BODY, "credential": "SECRET document contents"})
        assert result.status_code == 422
        assert result.json() == {"detail": "Invalid request."}
        assert "SECRET" not in result.text


async def test_concurrency_queue_overload_and_probe_independence():
    entered, release = asyncio.Event(), asyncio.Event()
    calls = 0

    async def answer(**kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            entered.set()
        await release.wait()
        return "Answer"

    service = AsyncMock(achat=AsyncMock(side_effect=answer))
    application = create_app(
        agent_service=service, config=config(api_max_active_requests=2, api_max_waiting_requests=1)
    )
    async with client_for(application) as client:
        tasks = [asyncio.create_task(client.post("/chat", json=BODY)) for _ in range(3)]
        try:
            await wait_count(application, active=2, waiting=1)
            await asyncio.wait_for(entered.wait(), 2)
            assert service.achat.await_count == 2
            result = await client.post("/chat", json=BODY)
            assert result.status_code == 429
            assert result.json() == {"detail": "Too many requests."}
            assert result.headers["Retry-After"] == "1"
            assert (await client.get("/health")).status_code == 200
            assert (await client.get("/ready")).status_code == 200
        finally:
            release.set()
            responses = await asyncio.gather(*tasks)
        assert all(r.json() == {"response": "Answer"} for r in responses)
        assert service.achat.await_count == 3
    assert application.state.admission.active == application.state.admission.waiting == 0
    assert not application.state.chat_tasks


async def test_zero_waiting_capacity():
    entered, release = asyncio.Event(), asyncio.Event()

    async def answer(**kwargs):
        entered.set()
        await release.wait()
        return "Answer"

    application = create_app(
        agent_service=AsyncMock(achat=answer),
        config=config(api_max_active_requests=1, api_max_waiting_requests=0),
    )
    async with client_for(application) as client:
        first = asyncio.create_task(client.post("/chat", json=BODY))
        await entered.wait()
        try:
            assert (await client.post("/chat", json=BODY)).status_code == 429
        finally:
            release.set()
            await first


async def test_queue_wait_timeout_does_not_invoke_service():
    entered, release = asyncio.Event(), asyncio.Event()

    async def answer(**kwargs):
        entered.set()
        await release.wait()
        return "Answer"

    service = AsyncMock(achat=AsyncMock(side_effect=answer))
    application = create_app(
        agent_service=service,
        config=config(
            api_max_active_requests=1, api_max_waiting_requests=1, api_queue_timeout_seconds=0.03
        ),
    )
    async with client_for(application) as client:
        first = asyncio.create_task(client.post("/chat", json=BODY))
        await entered.wait()
        try:
            result = await client.post("/chat", json=BODY)
            assert result.status_code == 504
            assert result.json() == {"detail": "Request queue wait timed out."}
            assert service.achat.await_count == 1
            assert application.state.admission.waiting == 0
        finally:
            release.set()
            await first


async def test_total_deadline_includes_queue_and_execution():
    first_entered, release_first, second_cancelled = (asyncio.Event() for _ in range(3))

    async def answer(query, session_id):
        if session_id == "a":
            first_entered.set()
            await release_first.wait()
            return "Answer"
        try:
            await asyncio.sleep(0.08)
            return "Too late"
        except asyncio.CancelledError:
            second_cancelled.set()
            raise

    application = create_app(
        agent_service=AsyncMock(achat=answer),
        config=config(
            api_max_active_requests=1, api_max_waiting_requests=1, api_request_timeout_seconds=0.12
        ),
    )
    async with client_for(application) as client:
        first = asyncio.create_task(client.post("/chat", json=BODY))
        await first_entered.wait()
        second = asyncio.create_task(client.post("/chat", json={**BODY, "session_id": "b"}))
        await wait_count(application, waiting=1)
        asyncio.get_running_loop().call_later(0.07, release_first.set)
        assert (await first).status_code == 200
        result = await second
        assert result.status_code == 504
        assert result.json() == {"detail": "Request deadline exceeded."}
        assert second_cancelled.is_set()
        assert application.state.admission.active == 0


async def test_body_read_is_inside_total_deadline():
    service = AsyncMock()
    application = create_app(agent_service=service, config=config(api_request_timeout_seconds=0.03))

    async def slow_body():
        yield b"{"
        await asyncio.Event().wait()

    async with client_for(application) as client:
        result = await client.post("/chat", content=slow_body())
        assert result.status_code == 504
        assert result.json() == {"detail": "Request deadline exceeded."}
        service.achat.assert_not_awaited()
    assert not application.state.chat_tasks
    assert application.state.admission.active == 0


async def test_cancelled_waiter_frees_capacity():
    entered, release = asyncio.Event(), asyncio.Event()

    async def answer(**kwargs):
        entered.set()
        await release.wait()
        return "Answer"

    application = create_app(
        agent_service=AsyncMock(achat=answer),
        config=config(api_max_active_requests=1, api_max_waiting_requests=1),
    )
    async with client_for(application) as client:
        first = asyncio.create_task(client.post("/chat", json=BODY))
        await entered.wait()
        waiter = asyncio.create_task(client.post("/chat", json=BODY))
        await wait_count(application, waiting=1)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert application.state.admission.waiting == 0
        release.set()
        await first
        assert (await client.post("/chat", json=BODY)).status_code == 200


async def test_shutdown_cancels_active_and_queued_requests():
    entered = asyncio.Event()

    async def answer(**kwargs):
        entered.set()
        await asyncio.Event().wait()

    application = create_app(
        agent_service=AsyncMock(achat=answer),
        config=config(api_max_active_requests=1, api_max_waiting_requests=1),
    )
    owner = Lifespan(application)
    await owner.start()
    async with client_for(application) as client:
        first = asyncio.create_task(client.post("/chat", json=BODY))
        await entered.wait()
        waiting = asyncio.create_task(client.post("/chat", json=BODY))
        await wait_count(application, waiting=1)
        await owner.stop()
        for task in (first, waiting):
            with pytest.raises(asyncio.CancelledError):
                await task
        assert (await client.get("/ready")).status_code == 503
        assert (await client.post("/chat", json=BODY)).status_code == 503
    assert not application.state.chat_tasks
    assert application.state.admission.active == application.state.admission.waiting == 0


@pytest.mark.parametrize(
    "name,value",
    [
        ("api_max_request_body_bytes", 0),
        ("api_max_active_requests", 0),
        ("api_max_waiting_requests", -1),
        ("api_request_timeout_seconds", 0),
        ("api_queue_timeout_seconds", float("inf")),
    ],
)
async def test_invalid_limits_rejected(name, value):
    with pytest.raises(ValidationError):
        config(**{name: value})


async def test_disconnect_after_complete_body_cancels_turn_and_releases_capacity():
    entered, cancelled = asyncio.Event(), asyncio.Event()
    messages = asyncio.Queue()
    await messages.put(
        {"type": "http.request", "body": json.dumps(BODY).encode(), "more_body": False}
    )

    async def answer(**kwargs):
        entered.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    service = AsyncMock(achat=answer)
    application = create_app(agent_service=service)
    sent = []

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/chat",
        "raw_path": b"/chat",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "scheme": "http",
        "http_version": "1.1",
        "server": ("test", 80),
        "client": ("test", 1234),
        "root_path": "",
    }
    task = asyncio.create_task(application(scope, messages.get, send))
    await asyncio.wait_for(entered.wait(), 2)
    await messages.put({"type": "http.disconnect"})
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert cancelled.is_set()
    assert not sent
    assert application.state.admission.active == 0
    assert application.state.chat_tasks == set()
    assert not [t for t in asyncio.all_tasks() if t.get_name() == "veridex-http-disconnect"]
