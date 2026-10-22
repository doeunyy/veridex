"""Durable conversation state outside the process.

Each completed turn is stored as one record: the question, the answer, the cited
source IDs and a compact routing summary. Before a turn, the recent records are
loaded and replayed into the graph as messages, so a follow-up works on any Cloud
Run instance, after a restart, or after scaling.

Backends: Firestore (Cloud Run), SQLite (local development) and memory (tests).
"""

import asyncio
import json
import sqlite3
import time
from pathlib import Path
from typing import Protocol

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

from veridex.config import Settings, settings

MAX_STORED_CHARACTERS = 20_000


class ConversationStore(Protocol):
    backend: str

    async def load(self, session_id: str, turns: int) -> list[dict]: ...

    async def append(self, session_id: str, turn: dict) -> None: ...

    async def delete(self, session_id: str) -> None: ...


def make_turn(question: str, output: dict) -> dict:
    return {
        "question": question[:MAX_STORED_CHARACTERS],
        "answer": output["response"][:MAX_STORED_CHARACTERS],
        "citations": [c["id"] for c in output.get("citations", [])],
        "routing": [
            {k: r[k] for k in ("agent", "provider", "model", "rule", "fallback_from")}
            for r in output.get("routing", [])
        ],
        "created_at": time.time(),
    }


def to_messages(turns: list[dict]) -> list[AnyMessage]:
    messages: list[AnyMessage] = []
    for turn in turns:
        messages += [HumanMessage(content=turn["question"]), AIMessage(content=turn["answer"])]
    return messages


class MemoryStore:
    backend = "memory"

    def __init__(self):
        self._turns: dict[str, list[dict]] = {}

    async def load(self, session_id: str, turns: int) -> list[dict]:
        return list(self._turns.get(session_id, [])[-turns:])

    async def append(self, session_id: str, turn: dict) -> None:
        self._turns.setdefault(session_id, []).append(dict(turn))

    async def delete(self, session_id: str) -> None:
        self._turns.pop(session_id, None)


class SqliteStore:
    """Local durable store; survives restarts of a single machine, not Cloud Run."""

    backend = "sqlite"

    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS turns ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, "
                "created_at REAL NOT NULL, turn TEXT NOT NULL)"
            )
            connection.execute("CREATE INDEX IF NOT EXISTS turns_session ON turns (session_id, id)")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path, timeout=5)

    def _load(self, session_id: str, turns: int) -> list[dict]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT turn FROM turns WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, turns),
            ).fetchall()
        return [json.loads(row[0]) for row in reversed(rows)]

    def _append(self, session_id: str, turn: dict) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO turns (session_id, created_at, turn) VALUES (?, ?, ?)",
                (session_id, turn["created_at"], json.dumps(turn, ensure_ascii=False)),
            )

    def _delete(self, session_id: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM turns WHERE session_id = ?", (session_id,))

    async def load(self, session_id: str, turns: int) -> list[dict]:
        return await asyncio.to_thread(self._load, session_id, turns)

    async def append(self, session_id: str, turn: dict) -> None:
        await asyncio.to_thread(self._append, session_id, turn)

    async def delete(self, session_id: str) -> None:
        await asyncio.to_thread(self._delete, session_id)


class FirestoreStore:
    """conversations/{session_id}/turns/{auto-id}; reads the latest N turns by time."""

    backend = "firestore"

    def __init__(self, client, collection: str):
        self._collection = client.collection(collection)

    def _turns(self, session_id: str):
        return self._collection.document(session_id).collection("turns")

    async def load(self, session_id: str, turns: int) -> list[dict]:
        query = self._turns(session_id).order_by("created_at", direction="DESCENDING")
        documents = [document async for document in query.limit(turns).stream()]
        return [document.to_dict() for document in reversed(documents)]

    async def append(self, session_id: str, turn: dict) -> None:
        await self._collection.document(session_id).set(
            {"updated_at": turn["created_at"]}, merge=True
        )
        await self._turns(session_id).add(dict(turn))

    async def delete(self, session_id: str) -> None:
        async for document in self._turns(session_id).stream():
            await document.reference.delete()
        await self._collection.document(session_id).delete()


def create_store(config: Settings | None = None) -> ConversationStore:
    config = config or settings
    if config.state_backend == "memory":
        return MemoryStore()
    if config.state_backend == "sqlite":
        return SqliteStore(config.state_sqlite_path)
    from google.cloud import firestore

    client = firestore.AsyncClient(project=config.firestore_project_id)
    return FirestoreStore(client, config.firestore_collection)
