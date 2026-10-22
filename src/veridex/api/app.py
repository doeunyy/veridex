"""FastAPI contract with an injected agent; importing this module starts no MCP servers."""

import json
import logging
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from pathlib import Path
from typing import Annotated, Protocol

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from veridex.agents.service import MultiAgentService, SessionCapacityError
from veridex.api.attribution import CorpusAttribution, load_attribution
from veridex.api.lifecycle import agent_lifespan
from veridex.api.limits import Admission, ChatLimitsMiddleware
from veridex.api.schemas import ChatRequest, ChatResponse, HealthResponse, ReadyResponse
from veridex.config import Settings, settings
from veridex.observability import exception_class, execution, turn_context

STATIC_DIR = Path(__file__).resolve().parents[1] / "web" / "static"
_LOG = logging.getLogger("uvicorn.error.veridex")
_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


class AsyncAgentService(Protocol):
    """The async chat surface provided by MultiAgentService."""

    async def achat(self, query: str, session_id: str) -> str: ...

    def astream_turn(self, query: str, session_id: str) -> AsyncIterator[tuple[str, dict]]: ...


def sse(event: str, data: dict) -> str:
    """One Server-Sent Event; JSON never contains raw newlines, so one data line suffices."""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


def get_agent_service(request: Request) -> AsyncAgentService:
    """Resolve a published service, also overridable through FastAPI dependencies.

    Lifespan publishes the service only after discovery and withdraws it before
    shutdown. The local usability check does not probe external providers.
    """
    service = request.app.state.agent_service
    if (
        request.app.state.shutting_down
        or service is None
        or (isinstance(service, MultiAgentService) and not service.is_usable)
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent service is unavailable.",
        )
    return service


def create_app(
    *,
    agent_service: AsyncAgentService | None = None,
    service_factory: Callable[[], AbstractAsyncContextManager[MultiAgentService]] | None = None,
    config: Settings | None = None,
) -> FastAPI:
    """Create an isolated app, optionally with an already initialized service.

    An injected service bypasses MCP creation. A factory permits real STDIO tests
    with deterministic models; production uses open_multi_agent_service directly.
    """
    if agent_service is not None and service_factory is not None:
        raise ValueError("Choose an injected service or a service factory.")
    application = FastAPI(
        title="Veridex",
        version="2.0.0.dev0",
        lifespan=agent_lifespan(injected_service=agent_service, service_factory=service_factory),
    )
    application.state.agent_service = agent_service
    application.state.shutting_down = False
    application.state.lifecycle_started = False
    application.state.chat_tasks = set()
    config = config or settings
    attribution = load_attribution(config.corpus_attribution_path)
    application.state.admission = Admission(config)
    application.add_middleware(ChatLimitsMiddleware, state=application.state, config=config)

    @application.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # Default validation errors echo rejected inputs, including arbitrary secrets.
        return JSONResponse(status_code=422, content={"detail": "Invalid request."})

    @application.post(
        "/chat",
        response_model=ChatResponse,
        responses={
            400: {"description": "Invalid request headers"},
            413: {"description": "Request body too large"},
            429: {"description": "Request capacity exhausted"},
            504: {"description": "Request deadline or queue wait expired"},
            503: {"description": "Agent service unavailable"},
            500: {"description": "Agent request failed"},
        },
    )
    async def chat(
        body: ChatRequest,
        http_response: Response,
        service: Annotated[AsyncAgentService, Depends(get_agent_service)],
    ) -> ChatResponse:
        if application.state.shutting_down:
            raise HTTPException(status_code=503, detail="Agent service is unavailable.")
        try:
            with turn_context(), execution("chat"):
                response = await service.achat(query=body.query, session_id=body.session_id)
            if attribution is not None:
                http_response.headers["Link"] = '</attribution>; rel="describedby"'
            return ChatResponse(response=response)
        except SessionCapacityError:
            raise HTTPException(status_code=429, detail="Session capacity exhausted.") from None
        except Exception:  # noqa: BLE001 — never expose provider or internal exception details
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Agent request failed.",
            ) from None

    @application.post(
        "/api/chat/stream",
        response_class=StreamingResponse,
        responses={
            200: {"content": {"text/event-stream": {}}, "description": "Turn events"},
            413: {"description": "Request body too large"},
            429: {"description": "Request capacity exhausted"},
            503: {"description": "Agent service unavailable"},
        },
    )
    async def chat_stream(
        body: ChatRequest,
        service: Annotated[AsyncAgentService, Depends(get_agent_service)],
    ) -> StreamingResponse:
        """Stream one turn as SSE: route, trace, token, citations, done (or error)."""

        async def events():
            with turn_context(), execution("chat"):
                try:
                    async for event, data in service.astream_turn(body.query, body.session_id):
                        yield sse(event, data)
                except SessionCapacityError:
                    yield sse("error", {"message": "Session capacity exhausted. Try later."})
                except TimeoutError:
                    yield sse("error", {"message": "The request took too long. Please retry."})
                except Exception as exc:  # noqa: BLE001 — never stream internal details
                    _LOG.info(
                        json.dumps(
                            {"event": "stream_failed", "exception_class": exception_class(exc)}
                        )
                    )
                    yield sse("error", {"message": "Agent request failed."})

        return StreamingResponse(events(), media_type="text/event-stream", headers=_SSE_HEADERS)

    @application.get("/api/info")
    async def info(
        service: Annotated[AsyncAgentService, Depends(get_agent_service)],
    ) -> dict:
        """Agents, tools, shared MCP tools and models, for the UI side panel."""
        return service.describe() if hasattr(service, "describe") else {}

    @application.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    application.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @application.get("/attribution", response_model=CorpusAttribution)
    async def corpus_attribution() -> CorpusAttribution:
        if attribution is None:
            raise HTTPException(status_code=503, detail="Corpus attribution is unavailable.")
        return attribution

    @application.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse()

    @application.get(
        "/ready",
        response_model=ReadyResponse,
        responses={503: {"description": "Agent service unavailable"}},
    )
    async def ready(
        service: Annotated[AsyncAgentService, Depends(get_agent_service)],
    ) -> ReadyResponse:
        return ReadyResponse()

    return application


app = create_app()
