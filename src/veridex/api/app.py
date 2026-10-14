"""FastAPI contract with an injected agent; importing this module starts no MCP servers."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Annotated, Protocol

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from veridex.agent.budgets import SessionCapacityError
from veridex.agent.mcp_service import MCPAgentService
from veridex.api.attribution import CorpusAttribution, load_attribution
from veridex.api.lifecycle import agent_lifespan
from veridex.api.limits import Admission, ChatLimitsMiddleware
from veridex.api.schemas import ChatRequest, ChatResponse, HealthResponse, ReadyResponse
from veridex.config import Settings, settings
from veridex.observability import execution, turn_context


class AsyncAgentService(Protocol):
    """The async chat surface already provided by MCPAgentService."""

    async def achat(self, query: str, session_id: str) -> str: ...


def get_agent_service(request: Request) -> AsyncAgentService:
    """Resolve a published service, also overridable through FastAPI dependencies.

    Lifespan publishes the service only after discovery and withdraws it before
    shutdown. The local usability check does not probe external providers.
    """
    service = request.app.state.agent_service
    if (
        request.app.state.shutting_down
        or service is None
        or (isinstance(service, MCPAgentService) and not service.is_usable)
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent service is unavailable.",
        )
    return service


def create_app(
    *,
    agent_service: AsyncAgentService | None = None,
    service_factory: Callable[[], AbstractAsyncContextManager[MCPAgentService]] | None = None,
    config: Settings | None = None,
) -> FastAPI:
    """Create an isolated app, optionally with an already initialized service.

    An injected service bypasses MCP creation. A factory permits real STDIO tests
    with deterministic models; production uses open_mcp_agent_service directly.
    """
    if agent_service is not None and service_factory is not None:
        raise ValueError("Choose an injected service or a service factory.")
    application = FastAPI(
        title="Veridex",
        version="0.1.0",
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
