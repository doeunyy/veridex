"""MCP boundary for the read-only SQLite paper catalog used by the Data agent."""

import asyncio
from typing import Annotated

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel, Field

from veridex.config import settings
from veridex.data.catalog import CatalogQueryError, describe_schema, query_catalog

_READ_ONLY = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": False,
}


class CatalogSchema(BaseModel):
    dialect: str = "sqlite"
    schema_sql: str


class CatalogResult(BaseModel):
    sql: str
    columns: list[str]
    rows: list[list[str | int | float | None]]
    truncated: bool = Field(description="True if more rows matched than were returned.")


def create_server() -> FastMCP:
    """Construct a server without opening the database."""
    server = FastMCP(name="Veridex Catalog")

    @server.tool(annotations=_READ_ONLY)
    async def describe_catalog() -> CatalogSchema:
        """Return the SQL schema of the paper catalog (papers, authors, categories)."""
        return CatalogSchema(schema_sql=describe_schema())

    @server.tool(annotations=_READ_ONLY)
    async def query_catalog_sql(
        sql: Annotated[str, Field(strict=True, min_length=1, max_length=4000)],
        max_rows: Annotated[int, Field(strict=True, ge=1, le=50)] = 20,
    ) -> CatalogResult:
        """Run ONE read-only SQLite SELECT against the paper catalog.

        Writes, PRAGMA, ATTACH and multiple statements are rejected.
        """
        try:
            result = await asyncio.to_thread(query_catalog, settings.catalog_path, sql, max_rows)
        except CatalogQueryError as exc:
            raise ToolError(str(exc)) from None
        except Exception:  # noqa: BLE001 — hide host paths and driver details
            raise ToolError("Paper catalog is unavailable.") from None
        return CatalogResult(sql=sql, **result)

    return server


if __name__ == "__main__":
    create_server().run(transport="stdio")
