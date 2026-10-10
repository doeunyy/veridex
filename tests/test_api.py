import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest
import pytest_asyncio

from veridex.api.app import app, create_app, get_agent_service
from veridex.api.schemas import MAX_QUERY_LENGTH, MAX_SESSION_ID_LENGTH

pytestmark = pytest.mark.asyncio


@pytest.fixture
def service():
    return AsyncMock(achat=AsyncMock(return_value="Verified answer."))


@pytest_asyncio.fixture
async def client(service):
    application = create_app(agent_service=service)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://test"
    ) as client:
        yield client


async def test_chat_exact_response_and_arguments(client, service):
    body = {"query": " Explain Self-RAG. ", "session_id": " session-a "}
    result = await client.post("/chat", json=body)
    assert result.status_code == 200
    assert result.json() == {"response": "Verified answer."}
    service.achat.assert_awaited_once_with(**body)
    service.achat_with_trace.assert_not_called()


@pytest.mark.parametrize("field", ["query", "session_id"])
@pytest.mark.parametrize("value", [None, 123, 1.5, True, [], {}, "", " \t\n", "\u2003"])
async def test_invalid_field_values(client, service, field, value):
    body = {"query": "Hello", "session_id": "session-a", field: value}
    result = await client.post("/chat", json=body)
    assert result.status_code == 422
    assert "detail" in result.json()
    service.achat.assert_not_awaited()


@pytest.mark.parametrize("body", [{}, {"query": "Hello"}, {"session_id": "session-a"}])
async def test_required_fields(client, service, body):
    result = await client.post("/chat", json=body)
    assert result.status_code == 422
    service.achat.assert_not_awaited()


@pytest.mark.parametrize(
    ("field", "limit"), [("query", MAX_QUERY_LENGTH), ("session_id", MAX_SESSION_ID_LENGTH)]
)
async def test_length_boundaries(client, service, field, limit):
    body = {"query": "Hello", "session_id": "session-a", field: "x" * limit}
    assert (await client.post("/chat", json=body)).status_code == 200
    service.achat.assert_awaited_once_with(**body)
    service.achat.reset_mock()
    body[field] += "x"
    assert (await client.post("/chat", json=body)).status_code == 422
    service.achat.assert_not_awaited()


async def test_extra_fields_rejected(client, service):
    result = await client.post(
        "/chat", json={"query": "Hello", "session_id": "session-a", "trace": True}
    )
    assert result.status_code == 422
    service.achat.assert_not_awaited()


@pytest.mark.parametrize("body", [None, [], "Hello"])
async def test_non_object_body(client, service, body):
    result = await client.post("/chat", content="null" if body is None else None, json=body)
    assert result.status_code == 422
    service.achat.assert_not_awaited()


async def test_malformed_json(client, service):
    result = await client.post("/chat", content="{", headers={"Content-Type": "application/json"})
    assert result.status_code == 422
    service.achat.assert_not_awaited()


@pytest.mark.parametrize("error", [RuntimeError, ValueError, TimeoutError])
async def test_internal_failures_are_safe(client, service, error):
    service.achat.side_effect = error("SECRET provider token and /private/internal/path")
    result = await client.post("/chat", json={"query": "Hello", "session_id": "session-a"})
    assert result.status_code == 500
    assert result.json() == {"detail": "Agent request failed."}
    assert "SECRET" not in result.text


@pytest.mark.parametrize(
    "response", [None, 123, {"response": "answer", "tool_results": ["SECRET"]}, ["SECRET"]]
)
async def test_invalid_service_responses_are_safe(client, service, response):
    service.achat.return_value = response
    result = await client.post("/chat", json={"query": "Hello", "session_id": "session-a"})
    assert result.status_code == 500
    assert result.json() == {"detail": "Agent request failed."}


async def test_cancellation_is_not_converted_to_internal_error(client, service):
    service.achat.side_effect = asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await client.post("/chat", json={"query": "Hello", "session_id": "session-a"})


async def test_health_and_readiness_publication_and_removal(service):
    application = create_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://test"
    ) as client:
        assert (await client.get("/health")).json() == {"status": "ok"}
        result = await client.get("/ready")
        assert result.status_code == 503
        assert result.json() == {"detail": "Agent service is unavailable."}
        result = await client.post("/chat", json={"query": "Hello", "session_id": "session-a"})
        assert result.status_code == 503
        assert result.json() == {"detail": "Agent service is unavailable."}

        application.state.agent_service = service
        result = await client.get("/ready")
        assert result.status_code == 200
        assert result.json() == {"status": "ready"}
        result = await client.get("/health")
        assert result.status_code == 200
        service.achat.assert_not_awaited()
        assert (
            await client.post("/chat", json={"query": "Hello", "session_id": "session-a"})
        ).status_code == 200

        application.state.agent_service = None
        assert (await client.get("/ready")).status_code == 503
        assert (await client.get("/health")).status_code == 200


async def test_dependency_override_and_app_isolation(service):
    application = create_app()
    application.dependency_overrides[get_agent_service] = lambda: service
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application), base_url="http://test"
    ) as client:
        assert (await client.get("/ready")).status_code == 200
        result = await client.post("/chat", json={"query": "Hello", "session_id": "session-b"})
        assert result.json() == {"response": "Verified answer."}
        service.achat.assert_awaited_once_with(query="Hello", session_id="session-b")
    assert create_app().state.agent_service is None
    assert app.state.agent_service is None


async def test_openapi_contract(client):
    schema = (await client.get("/openapi.json")).json()
    models = schema["components"]["schemas"]
    request = models["ChatRequest"]
    assert set(request["required"]) == {"query", "session_id"}
    assert request["additionalProperties"] is False
    assert request["properties"]["query"]["maxLength"] == MAX_QUERY_LENGTH
    assert request["properties"]["session_id"]["maxLength"] == MAX_SESSION_ID_LENGTH
    assert set(models["ChatResponse"]["properties"]) == {"response"}
    assert models["ChatResponse"]["required"] == ["response"]
    assert {"200", "422", "500", "503"} <= set(schema["paths"]["/chat"]["post"]["responses"])
