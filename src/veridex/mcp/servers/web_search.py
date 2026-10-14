"""Independent MCP boundary for asynchronous Tavily web search."""

import asyncio
from typing import Annotated, NotRequired, TypedDict

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import Field, TypeAdapter
from tavily import AsyncTavilyClient
from tavily.errors import TimeoutError as TavilyTimeoutError

from veridex.config import settings

SEARCH_TIMEOUT_SECONDS = 20


class WebSearchResult(TypedDict):
    title: str
    url: str
    content: str
    published_date: NotRequired[str]


class WebSearchResponse(TypedDict):
    query: str
    results: list[WebSearchResult]


_response_adapter = TypeAdapter(WebSearchResponse)


def create_server() -> FastMCP:
    """Construct a server without creating a client or making requests."""
    server = FastMCP(name="Veridex Web Search")

    @server.tool
    async def search_web(
        query: Annotated[str, Field(strict=True, min_length=1)],
        max_results: Annotated[int, Field(strict=True, ge=1, le=10)] = 5,
    ) -> WebSearchResponse:
        """Search the web with Tavily, returning provider snippets and exact source URLs.

        Publication dates appear only when supplied by Tavily.
        """
        if not query.strip():
            raise ToolError("Search query cannot be empty.")
        api_key = settings.tavily_api_key
        if not api_key or not api_key.strip():
            raise ToolError("Web search is unavailable: TAVILY_API_KEY is not configured.")

        try:
            # The outer deadline bounds the entire operation, including client cleanup.
            async with asyncio.timeout(SEARCH_TIMEOUT_SECONDS):
                async with AsyncTavilyClient(api_key=api_key) as client:
                    response = await client.search(
                        query=query,
                        max_results=max_results,
                        search_depth="basic",
                        include_answer=False,
                        include_raw_content=False,
                        timeout=SEARCH_TIMEOUT_SECONDS,
                    )
                results = []
                for item in response["results"]:
                    result = {key: item[key] for key in ("title", "url", "content")}
                    if item.get("published_date") is not None:
                        result["published_date"] = item["published_date"]
                    results.append(result)
                return _response_adapter.validate_python(
                    {"query": query, "results": results}, strict=True
                )
        except (TimeoutError, TavilyTimeoutError):
            raise ToolError("Web search timed out. Please try again.") from None
        except Exception:  # noqa: BLE001 — sanitize all SDK/response failures at this boundary
            # Never surface/log raw provider exceptions, response bodies, or request metadata.
            raise ToolError("Web search provider request failed. Please try again.") from None

    return server


if __name__ == "__main__":
    create_server().run(transport="stdio")
