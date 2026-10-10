"""FastAPI contract with an injected agent; importing this module starts no MCP servers."""

from typing import Annotated, Protocol

from fastapi import Depends, FastAPI, HTTPException, Request, status

from veridex.api.schemas import ChatRequest, ChatResponse, HealthResponse, ReadyResponse


class AsyncAgentService(Protocol):
    """The async chat surface already provided by MCPAgentService."""

    async def achat(self, query: str, session_id: str) -> str: ...


def get_agent_service(request: Request) -> AsyncAgentService:
    """Resolve a published service, also overridable through FastAPI dependencies.

    The owner must publish only a fully initialized, usable service and clear this
    slot before shutdown or on loss of usability. Presence is the readiness signal;
    this API layer does not open sessions or probe providers.
    """
    service = request.app.state.agent_service
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent service is unavailable.",
        )
    return service


def create_app(*, agent_service: AsyncAgentService | None = None) -> FastAPI:
    """Create an isolated app, optionally with an already initialized service.

    Real lifecycle ownership will be added in Step 4.2. Until then, the default
    application is live but unready and rejects chat requests with HTTP 503.
    """
    application = FastAPI(title="Veridex", version="0.1.0")
    application.state.agent_service = agent_service

    @application.post(
        "/chat",
        response_model=ChatResponse,
        responses={
            503: {"description": "Agent service unavailable"},
            500: {"description": "Agent request failed"},
        },
    )
    async def chat(
        body: ChatRequest,
        service: Annotated[AsyncAgentService, Depends(get_agent_service)],
    ) -> ChatResponse:
        try:
            response = await service.achat(query=body.query, session_id=body.session_id)
            return ChatResponse(response=response)
        except Exception:  # noqa: BLE001 — never expose provider or internal exception details
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Agent request failed.",
            ) from None

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
